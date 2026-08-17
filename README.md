# Video Box

Video Box 是一个自托管的资源上传、转换、浏览与二维码分享工具。

它可以统一管理视频和常用办公文档：视频上传后自动转码为适合浏览器和手机播放的 MP4；PDF、Word、PowerPoint、Excel 等文档会转换为适合手机连续浏览的页面。每个资源都可以生成二维码，并支持暂停访问、恢复访问、查看处理日志和彻底删除。

当前版本：**1.1.1**

## 功能概览

- 视频上传与自动转码
- PDF、Word、PowerPoint、Excel / OpenDocument 上传与转换
- 点击选择或拖拽文件上传
- 浏览器上传进度显示
- 手机端视频播放与文档连续阅读
- 视频横屏 / 竖屏 / 自动方向处理
- 统一资源管理中心
- 资源暂停 / 恢复访问
- 资源彻底删除，并同步删除相关文件和日志
- 二维码按需生成
- 二维码支持自定义备注文字
- SVG / PNG 二维码下载
- 外部 URL 二维码生成
- 视频观看次数与文档浏览次数统计
- FFmpeg、Office 转换和页面渲染日志
- SQLite 数据持久化
- Nginx `X-Accel-Redirect` 提供受控文件访问
- 默认仅监听本机地址，适合配合 SSH 隧道或反向代理使用

## 支持格式

### 视频

支持：

```text
.mp4 .mov .m4v .avi .mkv .webm
.mpeg .mpg .mts .m2ts .3gp
```

视频统一转换为：

```text
H.264 + AAC + MP4
```

支持三种输出方向：

- 自动：保持原视频横屏或竖屏方向
- 横屏：输出 16:9，不裁切画面
- 竖屏：输出 9:16，不裁切画面

### 文档

支持：

| 类型 | 格式 |
|---|---|
| PDF | `.pdf` |
| Word | `.doc` `.docx` `.odt` |
| PowerPoint | `.ppt` `.pptx` `.odp` |
| Excel | `.xls` `.xlsx` `.ods` |

处理方式：

```text
PDF
 └─→ 页面渲染 → 手机连续阅读

Word / PowerPoint / Excel
 └─→ LibreOffice → PDF → 页面渲染 → 手机连续阅读
```

公开文档页面不依赖手机安装 Word、WPS、PowerPoint 或 Excel。

## 页面与权限

| 地址 / 功能 | 登录要求 |
|---|---|
| `/` 上传资源 | 需要登录 |
| `/admin` 管理中心 | 需要登录 |
| `/manage/<slug>` 视频详情 / 日志 | 需要登录 |
| `/manage/document/<slug>` 文档详情 / 日志 | 需要登录 |
| 二维码生成、暂停、恢复、删除 | 需要登录 |
| `/v/<slug>` 视频播放 | 无需登录 |
| `/stream/<slug>` 视频流 | 无需登录 |
| `/r/<slug>` 文档阅读 | 无需登录 |
| 文档下载 | 由管理员单独控制 |

上传与管理共用 `APP_PASSWORD`。

公开视频和公开文档不要求登录，但资源被管理员暂停后将无法访问；恢复后原地址和原二维码继续有效。

## 快速部署

需要：

- Linux
- Docker Engine
- Docker Compose plugin（`docker compose`）

克隆项目：

```bash
git clone https://github.com/dreamzyd/video-box.git
cd video-box
```

执行部署脚本：

```bash
chmod +x deploy.sh
./deploy.sh
```

首次运行会自动：

1. 从 `.env.example` 创建 `.env`
2. 生成 `APP_SECRET`
3. 生成登录口令 `APP_PASSWORD`
4. 创建 `data/` 持久化目录
5. 构建并启动 `app`、`worker`、`nginx`

首次自动生成的登录口令会显示在终端中，请保存好。

## 默认访问方式

默认配置：

```env
BIND_ADDRESS=127.0.0.1
VIDEO_PORT=8080
```

因此 Docker 默认只监听宿主机本地地址。

服务器本机可以访问：

```text
http://127.0.0.1:8080/
http://127.0.0.1:8080/admin
```

### SSH 隧道

远程机器可以通过 SSH 本地转发：

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

然后在本机浏览器打开：

```text
http://127.0.0.1:8080/
```

### 直接监听外部地址

如果明确需要直接开放服务端口，在 `.env` 中设置：

```env
BIND_ADDRESS=0.0.0.0
VIDEO_PORT=8080
```

然后重新创建容器：

```bash
docker compose up -d
```

是否能够从公网访问还取决于宿主机防火墙和云平台安全策略。

## Nginx 反向代理

推荐让 Video Box 继续监听 `127.0.0.1`，再通过宿主机 Nginx 提供域名和 HTTPS。

示例：

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

项目中也提供：

```text
docs/nginx-reverse-proxy.conf.example
```

启用 HTTPS 后建议在 `.env` 设置：

```env
PUBLIC_BASE_URL=https://video.example.com
COOKIE_SECURE=true
```

## 二维码

### 视频

视频二维码指向：

```text
https://video.example.com/v/<slug>
```

### 文档

文档二维码指向：

```text
https://video.example.com/r/<slug>
```

二维码只有在点击生成时才会创建，可以设置下方备注，并下载为：

```text
SVG
PNG
```

### `PUBLIC_BASE_URL`

如果设置：

```env
PUBLIC_BASE_URL=https://video.example.com
```

系统生成的视频和文档二维码会固定使用这个地址。

如果留空，系统会根据生成二维码时当前管理页面使用的域名、IP 和端口生成链接。

例如通过 SSH 隧道访问：

```text
http://127.0.0.1:8080/admin
```

如果 `PUBLIC_BASE_URL` 为空，生成的二维码也可能包含 `127.0.0.1`，手机将无法通过这个地址访问服务器。因此正式使用二维码时建议配置一个手机可以访问的 `PUBLIC_BASE_URL`。

已经下载或打印出来的二维码内容不会自动变化。

## 资源管理

管理中心统一显示视频和文档，并提供：

- 查看 / 播放
- 二维码
- 暂停访问
- 恢复访问
- 浏览次数
- 详情与日志
- 删除资源

### 暂停与删除的区别

**暂停访问**：

- 文件仍然保留
- 数据库记录仍然保留
- 原二维码仍然保留
- 恢复后原链接继续有效

**删除资源**：

- 删除数据库记录
- 删除媒体或转换文件
- 删除上传临时文件
- 删除该资源日志
- 原链接和二维码永久失效

删除操作会进行二次确认。正在上传或正在处理的资源不会被删除。

## 文档阅读与下载

文档处理完成后，公开页面 `/r/<slug>` 会按页连续显示文档内容，适合手机上下滑动阅读。

Office 文档会先转换为 PDF，再生成页面图片。

典型文件结构：

```text
data/media/<slug>/
├── document.pdf
├── original.docx
└── pages/
    ├── page-1.jpg
    ├── page-2.jpg
    └── ...
```

管理员可以为每个文档决定是否允许公开下载原文件。

## 主要配置

编辑 `.env`：

| 配置 | 默认值 | 说明 |
|---|---|---|
| `BIND_ADDRESS` | `127.0.0.1` | Docker 对宿主机监听地址 |
| `VIDEO_PORT` | `8080` | 服务端口 |
| `APP_PASSWORD` | 首次部署生成 | 上传和管理登录口令 |
| `APP_SECRET` | 首次部署生成 | Flask Session 签名密钥 |
| `APP_SESSION_HOURS` | `12` | 登录 Session 有效时间 |
| `COOKIE_SECURE` | `false` | 外层 HTTPS 时建议设置为 `true` |
| `PUBLIC_BASE_URL` | 空 | 二维码与公开资源基础 URL |
| `MAX_UPLOAD_GB` | `5` | 应用上传大小限制 |
| `CLIENT_MAX_BODY_SIZE` | `5g` | Docker Nginx 上传限制 |
| `KEEP_ORIGINAL` | `false` | 视频转码后是否保留原始视频 |
| `FFMPEG_THREADS` | `1` | FFmpeg 线程数 |
| `VIDEO_CRF` | `24` | H.264 编码质量参数 |
| `VIDEO_PRESET` | `veryfast` | H.264 编码速度参数 |
| `KEEP_DOCUMENT_ORIGINAL` | `true` | 是否保留文档原文件 |
| `DOCUMENT_RENDER_DPI` | `120` | 文档页面渲染分辨率 |
| `DOCUMENT_JPEG_QUALITY` | `82` | 文档页面 JPEG 质量 |

### APP_PASSWORD 与 APP_SECRET

`APP_PASSWORD` 是上传和管理页面的登录口令。

`APP_SECRET` 是 Flask 用于签名 Session Cookie 的内部密钥，不是登录密码，也不需要日常输入。修改 `APP_SECRET` 后，已有登录 Session 会失效，需要重新登录。

## 数据目录

所有持久化数据默认位于：

```text
data/
├── db/
│   └── video.db
├── uploads/
├── media/
│   └── <slug>/
└── logs/
    └── <slug>/
```

其中：

- `data/db/video.db`：SQLite 数据库
- `data/uploads/`：上传与待处理文件
- `data/media/`：视频、文档和页面转换结果
- `data/logs/`：处理日志

`.gitignore` 已排除 `.env`、数据库、上传文件、媒体文件和日志。

## 日志

查看应用日志：

```bash
docker compose logs -f app
```

查看视频 / 文档处理 Worker：

```bash
docker compose logs -f worker
```

查看 Nginx：

```bash
docker compose logs -f nginx
```

每个资源还会在：

```text
data/logs/<slug>/
```

保存自己的任务日志。

视频常见日志：

```text
events.log
ffmpeg.log
progress.log
poster.log
```

文档常见日志：

```text
events.log
convert.log
render.log
```

## 常用运维命令

查看状态：

```bash
docker compose ps
```

启动：

```bash
docker compose up -d
```

停止：

```bash
docker compose down
```

重启：

```bash
docker compose restart
```

更新代码：

```bash
git pull
```

如果只是 Web / Flask / 页面代码发生变化：

```bash
docker compose build app
docker compose up -d
```

如果 Worker、Dockerfile、FFmpeg、LibreOffice 或依赖发生变化：

```bash
docker compose build app worker
docker compose up -d
```

一般不需要使用 `--no-cache`。

## 备份与恢复

建议备份：

```text
.env
data/
```

完整备份示例：

```bash
docker compose down

tar czf video-box-backup-$(date +%Y%m%d-%H%M%S).tar.gz \
    .env data/

docker compose up -d
```

只备份数据库：

```bash
cp data/db/video.db \
   data/db/video.db.bak.$(date +%Y%m%d-%H%M%S)
```

恢复时应同时恢复 `.env` 和 `data/`，尤其是数据库与 `data/media/` 中的资源文件。

## 升级

更新之前建议先备份 `.env` 和 `data/`。

使用 Git 更新：

```bash
git status
git pull
```

如果新版本修改了镜像依赖或 Worker：

```bash
docker compose build app worker
docker compose up -d
```

否则通常可以：

```bash
docker compose build app
docker compose up -d
```

已有资源 ID 和公开地址应由版本升级保持兼容。升级后建议先检查一个已有视频和一个已有文档链接，再测试新功能。

## 安全建议

- 不要把 `.env` 提交到 Git
- 不要公开 `APP_SECRET`
- 使用强 `APP_PASSWORD`
- 公网部署建议使用 HTTPS
- HTTPS 环境建议设置 `COOKIE_SECURE=true`
- 推荐通过反向代理暴露服务，而不是直接开放 Docker 服务端口
- 定期备份 `.env` 和整个 `data/` 目录

更多安全说明见：

```text
SECURITY.md
```

## 版本记录

版本变化与升级内容请查看：

```text
CHANGELOG.md
```
