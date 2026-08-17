# Changelog

## 1.1.0 - 2026-08-17

### Added

- PDF、Word、PowerPoint、Excel / OpenDocument 上传。
- LibreOffice Headless Office → PDF 转换。
- Poppler PDF → JPEG 页面渲染，提供手机连续阅读页 `/r/<slug>`。
- 独立 `documents` 数据表，不迁移或重建历史 `videos` 数据。
- 文档二维码、暂停 / 恢复、浏览次数、详情与转换日志。
- 文档原文件 / 转换 PDF 的可选公开下载控制。
- Noto CJK 中文字体兜底。
- `KEEP_DOCUMENT_ORIGINAL`、`DOCUMENT_RENDER_DPI`、`DOCUMENT_JPEG_QUALITY` 配置。

### Changed

- 上传页升级为“上传资源”，视频和文档共用入口。
- 管理中心统一展示视频与文档。
- Unicode 原文件名保留用于显示和下载，磁盘仍使用随机 slug 文件名。
- 大文件上传 CSRF 优先从 `X-CSRF-Token` Header 校验。
- Docker 镜像增加 LibreOffice、Poppler、Noto CJK 字体。

### Compatibility

- 保持 `videos` 表、视频 slug、`/v/<slug>`、`/stream/<slug>`、`/poster/<slug>` 和 `/qr/<slug>.svg` 语义不变。
- 1.0 已生成 / 已打印的视频二维码无需重新生成。

### Baseline

- Based on GitHub `main` commit `6089fe7` (`fix: preserve video extension for Chinese filenames`).

## 1.0 - 2026-08-15

- Initial public release.
