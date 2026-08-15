import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "/data/db/video.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    request_id TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL,
    input_path TEXT NOT NULL,
    output_path TEXT,
    poster_path TEXT,
    orientation TEXT NOT NULL DEFAULT 'auto',
    content_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    views INTEGER NOT NULL DEFAULT 0,
    access_enabled INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos(created_at);
"""


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(requeue_processing=False):
    with connect() as conn:
        conn.executescript(SCHEMA)

        # 向后兼容 v1/v2 数据库：只补字段，不删除任何旧数据。
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
        migrations = {
            "orientation": "ALTER TABLE videos ADD COLUMN orientation TEXT NOT NULL DEFAULT 'auto'",
            "request_id": "ALTER TABLE videos ADD COLUMN request_id TEXT",
            "description": "ALTER TABLE videos ADD COLUMN description TEXT NOT NULL DEFAULT ''",
            "content_sha256": "ALTER TABLE videos ADD COLUMN content_sha256 TEXT",
            "access_enabled": "ALTER TABLE videos ADD COLUMN access_enabled INTEGER NOT NULL DEFAULT 1",
        }
        for name, sql in migrations.items():
            if name not in columns:
                conn.execute(sql)

        # 旧数据库迁移后补索引。request_id 允许 NULL，旧行不会冲突。
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_request_id ON videos(request_id) WHERE request_id IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_content ON videos(content_sha256, orientation)")

        # 只有 worker 启动时才恢复中断任务，避免仅重启 Web 时把正在运行的任务重新排队。
        if requeue_processing:
            conn.execute(
                "UPDATE videos SET status='queued', updated_at=CURRENT_TIMESTAMP "
                "WHERE status='processing'"
            )
            # 上传过程中容器异常退出，无法确认文件是否完整，标记失败比盲目转码更安全。
            conn.execute(
                "UPDATE videos SET status='error', error='上传过程中服务被中断，请重新上传。', "
                "updated_at=CURRENT_TIMESTAMP WHERE status='uploading'"
            )
        conn.commit()
