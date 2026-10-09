"""Immutable version 1 schema. Future model edits require a new migration."""

from sqlalchemy import BigInteger, Column, DateTime, Float, Index, Integer, MetaData, String, Table, Text
from sqlalchemy.dialects.mysql import VARCHAR


metadata = MetaData()


def _exact(length):
    return String(length).with_variant(VARCHAR(length, collation="utf8mb4_bin"), "mysql")


def _table(name, *columns):
    return Table(
        name, metadata, *columns,
        mysql_charset="utf8mb4", mysql_engine="InnoDB",
    )


_table(
    "media_files",
    Column("id", String(36), primary_key=True),
    Column("tos_url", _exact(500), nullable=False, unique=True, index=True),
    Column("file_type", String(20)),
    Column("file_name", String(255)),
    Column("file_size", BigInteger),
    Column("vector_status", String(20)),
    Column("tag_status", String(20)),
    Column("vector_id", String(100)),
    Column("vector_model", String(100)),
    Column("vector_dimension", Integer),
    Column("vector_instruction_version", String(100)),
    Column("vector_collection", String(255)),
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
    Index("ix_media_files_vector_status", "vector_status"),
)

_table(
    "media_tags",
    Column("id", String(36), primary_key=True),
    Column("media_id", String(36), nullable=False, index=True),
    Column("category", String(50)),
    Column("tag_name", String(100)),
    Column("confidence", Float),
    Column("is_manual", Integer),
    Column("created_at", DateTime),
    Index("ix_media_tags_category_tag", "category", "tag_name"),
)

_table(
    "import_tasks",
    Column("id", String(36), primary_key=True),
    Column("task_id", String(36), unique=True, index=True),
    Column("tos_directory", String(2048)),
    Column("status", String(20), index=True),
    Column("total_files", Integer),
    Column("processed_files", Integer),
    Column("failed_files", Integer),
    Column("error_message", Text),
    Column("created_at", DateTime),
    Column("completed_at", DateTime),
)

_table(
    "search_history",
    Column("id", String(36), primary_key=True),
    Column("search_type", String(20)),
    Column("query_content", Text),
    Column("result_count", Integer),
    Column("created_at", DateTime),
)

_table(
    "users",
    Column("id", String(36), primary_key=True),
    Column("username", String(50), nullable=False, unique=True, index=True),
    Column("email", String(100), unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(20)),
    Column("is_active", Integer),
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
)

_table(
    "login_logs",
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("ip_address", String(45)),
    Column("user_agent", String(500)),
    Column("status", String(20)),
    Column("created_at", DateTime),
    Index("ix_login_logs_user_created", "user_id", "created_at"),
)

_table(
    "user_sessions",
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("refresh_token", _exact(500), nullable=False, unique=True),
    Column("expires_at", DateTime, nullable=False),
    Column("is_revoked", Integer),
    Column("created_at", DateTime),
    Index("ix_user_sessions_active_expiry", "is_revoked", "expires_at"),
)

_table(
    "user_system_settings",
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, unique=True, index=True),
    Column("tos_access_key_id", String(255)),
    Column("tos_access_key_secret", String(255)),
    Column("tos_security_token", Text),
    Column("tos_bucket_name", String(255)),
    Column("tos_endpoint", String(255)),
    Column("tos_region", String(50)),
    Column("tos_custom_domain", String(255)),
    Column("ark_api_key", String(255)),
    Column("embedding_model", String(100)),
    Column("embedding_dimension", Integer),
    Column("tag_model", String(100)),
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
)
