# Security Notes

Video Box 1.0 的默认部署目标是单机、小规模、自建视频服务。

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

## 登录与公开视频

`APP_PASSWORD` 保护：上传、管理中心、日志、二维码生成和资源控制。

以下播放路径故意不要求登录：

- `/v/<slug>`
- `/stream/<slug>`
- `/poster/<slug>`

这是产品设计的一部分：获得公开分享 URL 的观看者可以直接播放。管理员仍可暂停对应资源。

## APP_SECRET

`APP_SECRET` 用于 Flask Session 签名。它应当是随机值，不应提交到 Git，也不应与 `APP_PASSWORD` 相同。

`deploy.sh` 会在空值时自动生成随机密钥，并将 `.env` 权限尝试设为 `600`。

## HTTPS

通过 HTTPS 反向代理对外服务时建议：

```env
COOKIE_SECURE=true
PUBLIC_BASE_URL=https://video.example.com
```

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
- 定期备份 `.env` 与 `data/`；
- 操作系统和 Docker 安全更新。
