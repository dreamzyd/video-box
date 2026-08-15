# Video Box 1.0

一个面向小型 Linux 服务器的轻量视频上传、自动转码、公开播放、二维码分享与资源管理工具。

默认按 **2 核 / 2 GB 内存** 的小型服务器设计：单 Worker 串行转码，视频统一转为适合手机和浏览器播放的 H.264 + AAC MP4。

> **安全默认值**：1.0 默认只监听 `127.0.0.1:8080`，不会直接把 8080 端口暴露到公网。推荐通过 SSH 隧道使用，或者由宿主机 Nginx/Caddy 反向代理。确实需要直接开放时再设置 `BIND_ADDRESS=0.0.0.0`。

## 功能

- 登录后上传视频，支持上传进度显示与重复提交保护。
- FFmpeg 自动转码为 H.264 + AAC MP4，支持横屏、竖屏和自动方向。
- 上传完成后自动回到统一管理中心。
- 公开视频使用简洁的全屏播放器，观看者不需要登录。
- 资源可随时暂停 / 恢复访问，原播放链接和原二维码不变。
- Nginx 通过 `X-Accel-Redirect` 发送视频，大文件不经过 Python 进程转发。
- 统一管理所有视频：状态、观看次数、播放、二维码、暂停/恢复、详情和日志。
- 二维码按需生成，支持自定义下方备注，支持 SVG / PNG 下载。
- 支持为任意外部 URL 生成临时二维码。
- 每个视频保存任务事件、FFmpeg 输出和转码进度日志。
- SQLite 持久化，无需额外部署 MySQL / Redis。
- 国内构建默认使用阿里云 Debian / PyPI 镜像，可在 `.env` 切换。

## 权限模型

| 路径 / 功能 | 是否需要登录 |
|---|---|
| `/` 上传页 | 是 |
| `/upload` 上传动作 | 是 |
| `/admin` 管理中心 | 是 |
| `/manage/<slug>` 详情 / 日志 | 是 |
| 生成二维码、暂停 / 恢复资源 | 是 |
| `/v/<slug>` 播放页 | **否** |
| `/stream/<slug>` 视频流 | **否** |
| `/poster/<slug>` 封面 | **否** |

公开视频虽然不要求密码，但仍受“暂停访问”控制。资源暂停后，播放页、视频流和封面都会被阻止；恢复后原 URL 和原二维码继续有效。

## 架构

```text
浏览器
  │
  ▼
宿主机 127.0.0.1:8080（默认）
  │
  ▼
Docker Nginx
  ├─ Web 请求 ──────────────► Flask / Gunicorn
  │                            ├─ 登录 / 上传 / 管理
  │                            ├─ SQLite
  │                            └─ 二维码
  │
  └─ 受保护视频流 ◄─ X-Accel-Redirect
                               ▲
                               │
                         FFmpeg Worker
                               │
                      data/uploads → data/media
```

## 快速部署

目标环境建议：Ubuntu 22.04 LTS + Docker Engine + Docker Compose plugin。

```bash
git clone <你的仓库地址> video-box
cd video-box
chmod +x deploy.sh
./deploy.sh
```

首次运行会：

1. 从 `.env.example` 创建 `.env`；
2. 自动生成 `APP_SECRET`；
3. 自动生成上传 / 管理登录口令 `APP_PASSWORD`；
4. 创建 `data/` 持久化目录；
5. 构建镜像并启动 `app`、`worker`、`nginx`。

首次生成的登录口令会打印在终端，请保存好。

### 默认如何访问

1.0 默认：

```env
BIND_ADDRESS=127.0.0.1
VIDEO_PORT=8080
```

因此服务器公网 IP 的 `:8080` **默认访问不到**。

最简单的远程使用方式是 SSH 隧道：

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

然后在自己的电脑打开：

```text
http://127.0.0.1:8080/
```

管理中心：

```text
http://127.0.0.1:8080/admin
```

### 直接开放端口

明确需要直接通过服务器 IP 访问时，在 `.env` 修改：

```env
BIND_ADDRESS=0.0.0.0
VIDEO_PORT=8080
```

然后：

```bash
docker compose up -d
```

此时还需要按你的云服务器 / 防火墙策略决定是否放行 8080。

## 宿主机 Nginx 反向代理

推荐继续让 Docker 只监听：

```env
BIND_ADDRESS=127.0.0.1
VIDEO_PORT=8080
```

宿主机 Nginx 反代：

```nginx
server {
    listen 443 ssl http2;
    server_name video.example.com;

    client_max_body_size 5g;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

项目里也提供了示例：`docs/nginx-reverse-proxy.conf.example`。

启用 HTTPS 后建议：

```env
PUBLIC_BASE_URL=https://video.example.com
COOKIE_SECURE=true
```

## 二维码与地址规则

本站视频二维码实际编码的是完整播放地址，例如：

```text
https://video.example.com/v/fsCFsRsNZ5Ss
```

资源 ID `/v/fsCFsRsNZ5Ss` 本身不会因为重启或重新构建 Docker 而变化，只要数据库和媒体文件仍然保留。

### `PUBLIC_BASE_URL` 留空

系统会根据**生成二维码时当前管理页面的访问地址**产生 URL。

例如从：

```text
http://10.0.0.8:8080/admin
```

生成，则二维码可能写入：

```text
http://10.0.0.8:8080/v/xxxxx
```

### 设置 `PUBLIC_BASE_URL`

如果已经确定长期地址：

```env
PUBLIC_BASE_URL=https://video.example.com
```

之后无论从 SSH 隧道、IP 还是域名进入后台，本站视频二维码都固定使用：

```text
https://video.example.com/v/xxxxx
```

> 注意：已经下载或打印出来的旧二维码不会自动改变内容。更换域名后需要重新生成二维码，除非旧地址仍能跳转到新地址。

### SSH 隧道下生成二维码

如果通过 `http://127.0.0.1:8080` 的 SSH 隧道管理，并且 `PUBLIC_BASE_URL` 留空，那么二维码也会写入 `127.0.0.1`，手机扫码无法访问服务器。

要让二维码能被手机使用，需要给视频提供手机可访问的地址，并设置 `PUBLIC_BASE_URL`，或者通过对应的公网反代地址进入管理后台。

## 视频转码

上传后状态通常经历：

```text
uploading → queued → processing → ready
```

失败则：

```text
error
```

默认转码策略：

- 视频：H.264 / libx264
- 音频：AAC
- 输出：MP4 + faststart
- 自动方向：横屏保持横屏，竖屏保持竖屏
- 强制横屏：1280×720，不裁切
- 强制竖屏：720×1280，不裁切
- 默认 `FFMPEG_THREADS=1`
- 默认只启动一个 Worker，避免 2 核 2G 机器并行跑多个 FFmpeg

主要参数：

```env
FFMPEG_THREADS=1
VIDEO_CRF=24
VIDEO_PRESET=veryfast
KEEP_ORIGINAL=false
```

`KEEP_ORIGINAL=false` 表示转码成功后删除原上传文件，仅保留最终 MP4、封面和日志。

## 关键配置

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `BIND_ADDRESS` | `127.0.0.1` | Docker 对宿主机监听地址 |
| `VIDEO_PORT` | `8080` | 服务端口 |
| `APP_PASSWORD` | 首次部署自动生成 | 上传 + 管理登录口令 |
| `APP_SECRET` | 首次部署自动生成 | Flask Session 签名密钥，不是登录密码 |
| `APP_SESSION_HOURS` | `12` | 登录有效时间 |
| `COOKIE_SECURE` | `false` | 外层 HTTPS 时建议 `true` |
| `PUBLIC_BASE_URL` | 空 | 固定公开视频 / 二维码基础 URL |
| `MAX_UPLOAD_GB` | `5` | Flask 上传大小限制 |
| `CLIENT_MAX_BODY_SIZE` | `5g` | Nginx 上传大小限制 |
| `KEEP_ORIGINAL` | `false` | 是否保留原始视频 |
| `FFMPEG_THREADS` | `1` | FFmpeg 线程数 |
| `VIDEO_CRF` | `24` | H.264 质量 / 压缩参数 |
| `VIDEO_PRESET` | `veryfast` | x264 编码速度参数 |

### `APP_SECRET` 是什么

`APP_SECRET` 用于给 Flask 登录 Session Cookie 和 flash 消息签名。它不是管理员需要输入的密码。

- `APP_PASSWORD`：人输入，用来登录上传页和管理中心。
- `APP_SECRET`：程序内部使用，不需要记忆，但必须保密。

修改 `APP_SECRET` 不会改变视频、数据库或播放 URL，但会让所有已经登录的浏览器 Session 立即失效，需要重新登录。

## 数据与目录

```text
data/
├── db/
│   └── video.db            SQLite 数据库
├── uploads/                待处理原始上传
├── media/
│   └── <slug>/
│       ├── video.mp4       最终视频
│       └── poster.jpg      封面
└── logs/
    └── <slug>/
        ├── events.log      任务事件
        ├── ffmpeg.log      FFmpeg 输出
        ├── progress.log    转码进度
        └── poster.log      封面生成日志
```

`.gitignore` 已经排除 `.env`、数据库、上传文件、视频和日志，只保留目录中的 `.gitkeep`。

## 常用运维命令

查看容器：

```bash
docker compose ps
```

查看应用日志：

```bash
docker compose logs -f app
```

查看转码 Worker：

```bash
docker compose logs -f worker
```

查看 Nginx：

```bash
docker compose logs -f nginx
```

重启：

```bash
docker compose restart
```

停止：

```bash
docker compose down
```

更新代码后重新构建 Web 应用：

```bash
docker compose build app
docker compose up -d
```

如果 `worker.py`、FFmpeg 配置或 Python 依赖也变化，则：

```bash
docker compose build app worker
docker compose up -d
```

一般升级**不要随便使用 `--no-cache`**，否则会重新下载 FFmpeg 等大量 Debian 软件包。

## 备份与恢复

最低限度请备份：

```text
.env
data/
```

推荐停服后整体备份：

```bash
docker compose down
tar czf video-box-backup-$(date +%Y%m%d-%H%M%S).tar.gz .env data/
docker compose up -d
```

只备份 SQLite：

```bash
cp data/db/video.db data/db/video.db.bak.$(date +%Y%m%d-%H%M%S)
```

## 从 v6.3 升级到 1.0

1. 先备份：

```bash
cp data/db/video.db data/db/video.db.bak.$(date +%Y%m%d-%H%M%S)
cp .env .env.bak.$(date +%Y%m%d-%H%M%S)
```

2. 停止旧版本：

```bash
docker compose down
```

3. 用 1.0 代码覆盖程序文件，**保留原 `.env` 和整个 `data/` 目录**。

4. 执行：

```bash
./deploy.sh
```

旧 `.env` 没有 `BIND_ADDRESS` 时，1.0 会自动采用并写入：

```env
BIND_ADDRESS=127.0.0.1
```

因此升级后默认不再直接对公网暴露 8080。若你之前就是依靠公网 `IP:8080` 访问，需要明确改成：

```env
BIND_ADDRESS=0.0.0.0
```

已有数据库会继续使用，不需要重新上传或重新转码。

## 保存到 Git

本项目已经准备好 `.gitignore` 和 `.gitattributes`。如果当前目录还不是 Git 仓库：

```bash
git init
git add .
git commit -m "release: Video Box 1.0"
git tag v1.0
```

如果已经有仓库：

```bash
git add .
git commit -m "release: Video Box 1.0"
git tag v1.0
```

推送前建议执行：

```bash
git status
```

确认 `.env`、`data/db/video.db`、媒体文件和日志没有被加入版本控制。

## 项目结构

```text
video-box/
├── app/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── app.py
│   ├── db.py
│   ├── worker.py
│   ├── requirements.txt
│   └── templates/
├── data/
│   ├── db/
│   ├── uploads/
│   ├── media/
│   └── logs/
├── docs/
│   └── nginx-reverse-proxy.conf.example
├── nginx/
│   └── default.conf.template
├── .env.example
├── .gitignore
├── .gitattributes
├── CHANGELOG.md
├── SECURITY.md
├── VERSION
├── docker-compose.yml
└── deploy.sh
```

## 1.0 设计原则

- **默认安全**：Docker 端口仅绑定本地。
- **观看简单**：公开视频保持无登录、纯净播放器。
- **管理集中**：上传、资源状态、二维码和访问控制集中在管理工作台。
- **小机可跑**：尽量减少常驻组件和并行转码。
- **数据可迁移**：业务数据全部落在 `.env` + `data/`，重建容器不丢视频。
