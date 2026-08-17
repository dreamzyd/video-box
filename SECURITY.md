# Security Notes

Video Box 1.1.0 的默认部署目标是单机、小规模、自建的视频与文档分享服务。

## 默认网络策略

Docker Nginx 默认：

```env
BIND_ADDRESS=127.0.0.1
VIDEO_PORT=8080
```

因此服务只监听宿主机回环地址。推荐使用：

- SSH 本地端口转发；或
- 宿主机 Nginx / Caddy 反向代理并提供 HTTPS。

只有明确需要直接暴露时才设置：

```env
BIND_ADDRESS=0.0.0.0
```

## 登录与公开资源

`APP_PASSWORD` 保护：上传、管理中心、日志、二维码生成、资源配置和暂停/恢复操作。

以下公开视频路径故意不要求登录：

- `/v/<slug>`
- `/stream/<slug>`
- `/poster/<slug>`

以下公开文档路径故意不要求登录：

- `/r/<slug>`
- `/document/<slug>/page/<n>`

这是产品设计的一部分：获得公开分享 URL 的访问者可以直接观看视频或阅读文档。管理员仍可暂停对应资源。

文档下载接口只有在该资源开启“允许下载”后才会返回文件。不要把“难猜的 slug”当成访问认证机制；需要私密资料时，应在外层增加真正的鉴权、VPN/IP 白名单或其他访问控制。

## 文档转换

Office 文档会交给容器内的 LibreOffice Headless 处理，PDF 会交给 Poppler 渲染页面。上传功能只接受白名单扩展名，但任何第三方解析器都可能存在安全缺陷，因此建议：

- 及时更新 Docker 基础镜像和系统软件包；
- 不以特权模式运行容器；
- 不把宿主机敏感目录挂载到 app/worker；
- 对不可信公网上传场景在外层增加额外限制；
- 对重要数据定期备份。

## APP_SECRET

`APP_SECRET` 用于 Flask Session 签名。它应当是随机值，不应提交到 Git，也不应与 `APP_PASSWORD` 相同。

`deploy.sh` 会在空值时自动生成随机密钥，并将 `.env` 权限尝试设为 `600`。

## HTTPS

通过 HTTPS 反向代理对外服务时建议：

```env
COOKIE_SECURE=true
PUBLIC_BASE_URL=https://video.example.com
```

`PUBLIC_BASE_URL` 会影响新生成二维码中的完整 URL，但不会改变已有视频或文档的 `slug`。

## Git

不要提交：

- `.env`
- `data/db/video.db`
- `data/uploads/`
- `data/media/`
- `data/logs/`

项目 `.gitignore` 已默认排除这些内容，但首次提交前仍建议运行 `git status` 检查。

## 公网部署建议

如果管理入口对公网可访问，建议在外层代理或防火墙增加：

- HTTPS；
- 登录入口限速 / 防暴力破解；
- IP 白名单或 VPN（如适用）；
- 上传大小和请求频率限制；
- 定期备份 `.env` 与 `data/`；
- 操作系统和 Docker 安全更新。
