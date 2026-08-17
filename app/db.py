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

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    request_id TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    original_name TEXT NOT NULL,
    input_path TEXT NOT NULL,
    original_ext TEXT NOT NULL,
    document_type TEXT NOT NULL,
    output_path TEXT,
    original_path TEXT,
    page_count INTEGER NOT NULL DEFAULT 0,
    content_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    views INTEGER NOT NULL DEFAULT 0,
    access_enabled INTEGER NOT NULL DEFAULT 1,
    allow_download INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_request_id ON documents(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_content ON documents(content_sha256, document_type);
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

        # 向后兼容所有 1.0 及更早数据库：videos 只补字段，不重建、不删除、不改 slug。
        video_columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()}
        video_migrations = {
            "orientation": "ALTER TABLE videos ADD COLUMN orientation TEXT NOT NULL DEFAULT 'auto'",
            "request_id": "ALTER TABLE videos ADD COLUMN request_id TEXT",
            "description": "ALTER TABLE videos ADD COLUMN description TEXT NOT NULL DEFAULT ''",
            "content_sha256": "ALTER TABLE videos ADD COLUMN content_sha256 TEXT",
            "access_enabled": "ALTER TABLE videos ADD COLUMN access_enabled INTEGER NOT NULL DEFAULT 1",
        }
        for name, sql in video_migrations.items():
            if name not in video_columns:
                conn.execute(sql)

        # 旧数据库迁移后补索引。request_id 允许 NULL，旧行不会冲突。
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_request_id "
            "ON videos(request_id) WHERE request_id IS NOT NULL"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_content ON videos(content_sha256, orientation)")

        # documents 是 1.1.0 新表；以下迁移用于后续开发版本平滑升级。
        doc_columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
        doc_migrations = {
            "description": "ALTER TABLE documents ADD COLUMN description TEXT NOT NULL DEFAULT ''",
            "original_path": "ALTER TABLE documents ADD COLUMN original_path TEXT",
            "page_count": "ALTER TABLE documents ADD COLUMN page_count INTEGER NOT NULL DEFAULT 0",
            "content_sha256": "ALTER TABLE documents ADD COLUMN content_sha256 TEXT",
            "access_enabled": "ALTER TABLE documents ADD COLUMN access_enabled INTEGER NOT NULL DEFAULT 1",
            "allow_download": "ALTER TABLE documents ADD COLUMN allow_download INTEGER NOT NULL DEFAULT 0",
        }
        for name, sql in doc_migrations.items():
            if name not in doc_columns:
                conn.execute(sql)

        # 只有 worker 启动时才恢复中断任务，避免仅重启 Web 时把正在运行的任务重新排队。
        if requeue_processing:
            conn.execute(
                "UPDATE videos SET status='queued', updated_at=CURRENT_TIMESTAMP "
                "WHERE status='processing'"
            )
            conn.execute(
                "UPDATE videos SET status='error', error='上传过程中服务被中断，请重新上传。', "
                "updated_at=CURRENT_TIMESTAMP WHERE status='uploading'"
            )
            conn.execute(
                "UPDATE documents SET status='queued', updated_at=CURRENT_TIMESTAMP "
                "WHERE status='processing'"
            )
            conn.execute(
                "UPDATE documents SET status='error', error='上传过程中服务被中断，请重新上传。', "
                "updated_at=CURRENT_TIMESTAMP WHERE status='uploading'"
            )
        conn.commit()
