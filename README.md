# Video Box 1.1.1

Video Box 是一个面向小型 Linux 服务器的轻量资源上传、处理、公开浏览、二维码分享与访问管理工具。

1.1.1 在保持 1.0/1.1.0 视频与文档功能、历史链接完全兼容的前提下，重点优化上传体验并增加资源彻底删除能力。默认仍按 **2 核 / 2 GB 内存** 的小型服务器设计：只有一个 Worker，视频转码和文档转换串行执行。

> **安全默认值**：默认只监听 `127.0.0.1:8080`，不会直接把 8080 暴露到公网。推荐通过 SSH 隧道，或宿主机 Nginx / Caddy 反向代理。

> **升级兼容重点**：1.0 已存在的视频 `slug`、SQLite `videos` 表、`/v/<slug>`、`/stream/<slug>`、`/qr/<slug>.svg` 全部保留。1.1.0 只新增 `documents` 表和 `/r/<slug>` 文档阅读入口，**已有视频二维码无需重新生成**。

## 1.1.1 更新

- 上传区域放大，支持点击选择或直接拖拽视频 / 文档到上传框。
- 管理中心和资源详情页增加“删除”操作。
- 删除前进行两次确认；确认后同步删除数据库记录、媒体 / 转换文件、上传临时文件和该资源日志。
- 正在上传或处理中资源禁止删除；排队中、已完成、失败资源可删除。
- 删除会让该资源已有二维码立即失效；如果只是临时不对外开放，请继续使用“暂停访问”。
- 既有 `/v/<slug>` 与 `/r/<slug>` 地址规则完全不变。

## 1.1.0 新增功能

- 上传 PDF、Word、PowerPoint、Excel / OpenDocument 文件。
- PDF 直接处理；Office 文档通过 LibreOffice Headless 转换为 PDF。
- PDF 再渲染为逐页 JPEG，手机端使用连续纵向页面阅读，不依赖客户端 Office，也不依赖外部 PDF.js CDN。
- 文档公开地址使用 `/r/<资源ID>`，扫码后手机直接阅读。
- 文档与视频共用统一管理中心、二维码、暂停 / 恢复、浏览次数与日志体系。
- 文档可以单独控制是否允许公开下载原文件；Office 文档允许下载时也可下载转换后的 PDF。
- 中文 / Unicode 原文件名完整保留用于后台显示与下载；实际磁盘文件仍使用随机资源 ID，避免特殊字符影响路径。
- 上传请求优先使用 `X-CSRF-Token` 校验，可在解析大文件前尽早发现过期登录会话。

## 支持格式

### 视频

`mp4`、`mov`、`m4v`、`avi`、`mkv`、`webm`、`mpeg`、`mpg`、`mts`、`m2ts`、`3gp`

视频统一转为：

- H.264 / libx264
- AAC
- MP4 + faststart
- 自动保持横屏 / 竖屏，或手动强制 16:9 / 9:16

### 文档

- PDF：`.pdf`
- Word：`.doc` `.docx` `.odt`
- PowerPoint：`.ppt` `.pptx` `.odp`
- Excel：`.xls` `.xlsx` `.ods`

处理链路：

```text
PDF
 └─→ PDF → 页面 JPEG → 手机连续阅读

Word / PowerPoint / Excel
 └─→ LibreOffice Headless → PDF → 页面 JPEG → 手机连续阅读
```

## 权限模型

| 路径 / 功能 | 是否需要登录 |
|---|---|
| `/` 上传资源 | 是 |
| `/upload` 上传动作 | 是 |
| `/admin` 管理中心 | 是 |
| `/manage/<slug>` 视频详情 / 日志 | 是 |
| `/manage/document/<slug>` 文档详情 / 日志 | 是 |
| 二维码、暂停 / 恢复、修改资源 | 是 |
| `/v/<slug>` 视频播放 | 否 |
| `/stream/<slug>` 视频流 | 否 |
| `/r/<slug>` 文档阅读 | 否 |
| `/document/<slug>/page/<n>` 文档页面 | 否 |
| 文档原文件 / PDF 下载 | 仅当管理员开启“允许下载” |

公开资源都受“暂停访问”控制。暂停后内容被阻止；恢复后原 URL 和原二维码继续有效。

## 与 1.0 的兼容关系

1.0 的视频 URL 保持不变：

```text
https://video.example.com/v/fsCFsRsNZ5Ss
```

1.1.0 **不会**把它改成 `/r/`，也不会重新生成 `slug`。

新文档使用：

```text
https://video.example.com/r/AbCd12345678
```

数据库仍然使用原文件：

```text
data/db/video.db
```

但在同一个 SQLite 文件中新增：

```text
videos       # 原表，历史视频继续使用
documents    # 1.1.0 新表
```

## 架构

```text
浏览器 / 手机
      │
      ▼
宿主机 127.0.0.1:8080（默认）
      │
      ▼
Docker Nginx
      ├─ Web / 权限判断 ─────────► Flask / Gunicorn
      │                              ├─ 登录 / 上传 / 管理
      │                              ├─ SQLite
      │                              └─ 二维码
      │
      └─ X-Accel-Redirect ◄──────── 受保护媒体文件
                                     ▲
                                     │
                               单 Worker 串行处理
                             ┌───────┴─────────┐
                             │                 │
                          FFmpeg          LibreOffice
                           视频              Office
                             │                 │
                             └──────┬──────────┘
                                    ▼
                              PDF / pdftoppm
                                    ▼
                       data/uploads → data/media
```

## 快速部署

目标环境建议：Ubuntu 22.04 LTS + Docker Engine + Docker Compose plugin。

```bash
git clone https://github.com/dreamzyd/video-box.git
cd video-box
chmod +x deploy.sh
./deploy.sh
```

首次运行会：

1. 从 `.env.example` 创建 `.env`；
2. 自动生成 `APP_SECRET`；
3. 自动生成上传 / 管理登录口令 `APP_PASSWORD`；
4. 创建持久化目录；
5. 构建并启动 `app`、`worker`、`nginx`。

> 1.1.0 的 Docker 镜像新增 LibreOffice、Poppler 和 Noto CJK 字体，**第一次升级构建会比 1.0 明显更大、更慢**。后续代码升级通常可以复用 Docker 层缓存。

## 默认访问方式

默认 `.env`：

```env
BIND_ADDRESS=127.0.0.1
VIDEO_PORT=8080
```

公网不能直接访问 `IP:8080`。

SSH 隧道：

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

本机访问：

```text
http://127.0.0.1:8080/
http://127.0.0.1:8080/admin
```

明确需要直接开放端口时：

```env
BIND_ADDRESS=0.0.0.0
```

然后：

```bash
docker compose up -d
```

## 宿主机 Nginx 反向代理

推荐 Docker 仍然只监听 `127.0.0.1`：

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

项目里另有 `docs/nginx-reverse-proxy.conf.example`。

启用 HTTPS 后建议：

```env
PUBLIC_BASE_URL=https://video.example.com
COOKIE_SECURE=true
```

## 二维码规则

### 历史视频

仍然编码：

```text
https://video.example.com/v/<slug>
```

1.1.0 没有改变这个规则。

### 新文档

编码：

```text
https://video.example.com/r/<slug>
```

二维码按需生成，支持 SVG / PNG 和下方自定义备注。

如果 `PUBLIC_BASE_URL` 留空，则按生成二维码时管理页面当前访问的域名 / IP / 端口生成。通过 SSH 隧道管理时，建议设置一个手机真正能访问的 `PUBLIC_BASE_URL`，否则二维码可能写入 `127.0.0.1`。

## 文档手机阅读方式

Video Box 不要求手机安装 Word / PowerPoint / Excel，也不直接依赖手机浏览器原生 PDF 阅读器。

处理完成后：

```text
data/media/<slug>/
├── document.pdf
├── original.docx       # 默认保留，可按资源决定是否开放下载
└── pages/
    ├── page-1.jpg
    ├── page-2.jpg
    └── ...
```

公开 `/r/<slug>` 页面会纵向连续展示这些页面图片，并对后面的页面使用浏览器 lazy loading。手机可以直接上下滑动、双指缩放页面。

### 字体说明

Docker 安装 `fonts-noto-cjk` 作为中文字体兜底。普通 Word / PPT / Excel 文档通常可以获得较稳定的中文排版，但 LibreOffice 与 Microsoft Office 并非完全相同，特殊字体、宏、复杂文本框、嵌入对象或非常复杂的 Excel 打印区域仍可能出现排版差异。

## 文档参数

`.env`：

```env
KEEP_DOCUMENT_ORIGINAL=true
DOCUMENT_RENDER_DPI=120
DOCUMENT_JPEG_QUALITY=82
```

- `KEEP_DOCUMENT_ORIGINAL=true`：转换完成后在 `data/media/<slug>/` 保留原文件。推荐保持开启。
- `DOCUMENT_RENDER_DPI=120`：页面图片渲染清晰度。越大越清晰，也越占磁盘和处理时间。
- `DOCUMENT_JPEG_QUALITY=82`：页面 JPEG 质量。

## 视频参数

```env
KEEP_ORIGINAL=false
FFMPEG_THREADS=1
VIDEO_CRF=24
VIDEO_PRESET=veryfast
```

2 核 / 2G 建议继续保持单 Worker 和 `FFMPEG_THREADS=1`。

## 数据目录

```text
data/
├── db/
│   └── video.db
├── uploads/
├── media/
│   ├── <video-slug>/
│   │   ├── video.mp4
│   │   └── poster.jpg
│   └── <document-slug>/
│       ├── document.pdf
│       ├── original.<ext>
│       └── pages/
│           ├── page-1.jpg
│           └── ...
└── logs/
    └── <slug>/
        ├── events.log
        ├── ffmpeg.log      # 视频
        ├── progress.log    # 视频
        ├── convert.log     # Office 文档
        └── render.log      # PDF 页面渲染
```

`.gitignore` 排除 `.env`、数据库、上传文件、转换结果与日志。

## 从 1.0 升级到 1.1.0

这是最重要的部署流程。**不要删除 `.env`，不要删除 `data/`。**

### 1. 先确认当前代码和备份

```bash
cd /path/to/video-box
git status
git rev-parse --short HEAD
```

建议停服后完整备份：

```bash
docker compose down
tar czf ../video-box-backup-$(date +%Y%m%d-%H%M%S).tar.gz .env data/
```

最低限度也应备份数据库：

```bash
cp data/db/video.db data/db/video.db.bak.$(date +%Y%m%d-%H%M%S)
```

### 2. 更新代码

如果代码已经提交 Git：

```bash
git pull
```

### 3. 构建并启动

由于 1.1.0 新增 LibreOffice / Poppler，需要重建 app/worker 镜像：

```bash
docker compose build app worker
docker compose up -d
docker compose ps
```

通常不要加 `--no-cache`。

### 4. 验证旧二维码

先取一个正在使用的历史地址，例如：

```text
https://video.example.com/v/fsCFsRsNZ5Ss
```

升级前后都应继续直接播放。

再登录 `/admin`，确认历史视频标题、观看次数、暂停状态仍存在。

### 5. 验证新文档

依次测试：

- PDF
- 中文文件名 `.docx`
- PPTX
- XLSX

处理完成后打开 `/r/<slug>` 检查手机排版。

## 升级为什么不会破坏旧二维码

核心原因：

1. 不重建 `videos` 表；
2. 不修改旧 `slug`；
3. 不修改 `/v/<slug>` 路由；
4. 不修改 `/stream/<slug>` 路由；
5. 原 `/qr/<slug>.svg` 仍然只生成视频 `/v/<slug>` 地址；
6. 文档使用独立 `documents` 表和 `/r/<slug>`。

所以已有二维码只要原域名仍然可访问，就与 1.0 一样继续有效。

## 常用运维命令

```bash
# 查看容器
docker compose ps

# Web 日志
docker compose logs -f app

# 视频 / 文档 Worker
docker compose logs -f worker

# Nginx
docker compose logs -f nginx

# 重启
docker compose restart

# 停止
docker compose down
```

如果只改 Web 模板 / Flask：

```bash
docker compose build app
docker compose up -d
```

如果改了 Worker、Dockerfile、FFmpeg、LibreOffice 或文档转换：

```bash
docker compose build app worker
docker compose up -d
```

## 备份与恢复

至少备份：

```text
.env
data/
```

完整备份：

```bash
docker compose down
tar czf video-box-backup-$(date +%Y%m%d-%H%M%S).tar.gz .env data/
docker compose up -d
```

恢复时应恢复 `.env` 和整个 `data/`，尤其是 `data/db/video.db` 与 `data/media/`。

## 版本基线

1.1.0 的开发基线为仓库 `dreamzyd/video-box` 当时的 `main`：

```text
6089fe7  fix: preserve video extension for Chinese filenames
```

该提交相对初始 1.0 只修改了 `app/app.py` 的中文文件名扩展名处理；1.1.0 在这个基线上继续扩展。
