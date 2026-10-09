"""MySQL 8 models; UUIDs and historical integer flags stay portable."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, String, Integer, Float, DateTime,
    Text, Index, UniqueConstraint, JSON, ForeignKey, ForeignKeyConstraint,
)
from sqlalchemy.dialects.mysql import VARCHAR
from app.models.database import Base


def _exact_string(length):
    # Object keys and JWTs are case sensitive, unlike MySQL's default collation.
    return String(length).with_variant(VARCHAR(length, collation="utf8mb4_bin"), "mysql")


def generate_uuid():
    return str(uuid.uuid4())


def _utcnow():
    # MySQL DATETIME stores UTC without a timezone or server-session conversion.
    return datetime.now(timezone.utc).replace(tzinfo=None)


_ANNOTATION_STATUSES = (
    "'not_started', 'pending', 'running', 'completed', "
    "'partial', 'failed', 'skipped', 'cancelled'"
)


class MediaFile(Base):
    """媒体文件表"""
    __tablename__ = "media_files"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=True, index=True)
    tos_url = Column(_exact_string(500), nullable=False, index=True)
    file_type = Column(String(20))  # "image" | "video"
    file_name = Column(String(255))
    file_size = Column(BigInteger)
    vector_status = Column(String(20), default="pending")  # pending/processing/done/failed/skipped
    tag_status = Column(String(20), default="pending")
    published_annotation_run_id = Column(
        String(36), ForeignKey(
            "annotation_runs.id", name="fk_media_published_annotation_run",
            ondelete="SET NULL", use_alter=True,
        ), nullable=True,
    )
    annotation_status = Column(
        String(20), nullable=False, default="not_started", server_default="not_started",
    )
    vector_id = Column(String(100))
    vector_model = Column(String(100))
    vector_dimension = Column(Integer)
    vector_instruction_version = Column(String(100))
    vector_collection = Column(String(255))
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "tos_url", name="uq_media_files_user_tos_url"),
        Index("uq_media_files_id_user", "id", "user_id", unique=True),
        Index("ix_media_files_user_annotation_status", "user_id", "annotation_status"),
        Index("ix_media_files_vector_status", "vector_status"),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )

    def __repr__(self):
        return f"<MediaFile(id={self.id}, name={self.file_name}, type={self.file_type})>"


class MediaTag(Base):
    """媒体标签表"""
    __tablename__ = "media_tags"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=True, index=True)
    media_id = Column(String(36), nullable=False, index=True)
    source = Column(String(20), nullable=False, default="default", server_default="default")
    category = Column(String(50))
    tag_name = Column(String(100))
    confidence = Column(Float, default=1.0)
    is_manual = Column(Integer, default=0)  # 0=自动, 1=手动
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_media_tags_category_tag", "category", "tag_name"),
        Index(
            "ix_media_tags_user_source_category_tag",
            "user_id", "source", "category", "tag_name",
        ),
        CheckConstraint(
            "source IN ('default', 'custom')",
            name="ck_media_tags_source",
        ),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )

    def __repr__(self):
        return f"<MediaTag(media_id={self.media_id}, category={self.category}, tag={self.tag_name})>"


class ImportTask(Base):
    """导入任务表"""
    __tablename__ = "import_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=True, index=True)
    task_id = Column(String(36), unique=True, index=True)
    tos_directory = Column(String(2048))
    tag_mode = Column(String(20), nullable=False, default="default", server_default="default")
    custom_tag_prompt = Column(Text, nullable=True)
    annotation_config = Column(JSON, nullable=True)
    annotation_status = Column(
        String(20), nullable=False, default="not_started", server_default="not_started",
    )
    annotation_total_files = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_processed_files = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_completed_files = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_failed_files = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_planned_frames = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_processed_frames = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_completed_frames = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_failed_frames = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_current_media_id = Column(String(36), nullable=True)
    annotation_current_frame_index = Column(Integer, nullable=True)
    annotation_started_at = Column(DateTime, nullable=True)
    annotation_completed_at = Column(DateTime, nullable=True)
    annotation_elapsed_ms = Column(BigInteger, nullable=False, default=0, server_default="0")
    status = Column(String(20), default="pending", index=True)
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    failed_files = Column(Integer, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime)
    __table_args__ = (
        CheckConstraint(
            "tag_mode IN ('default', 'custom')",
            name="ck_import_tasks_tag_mode",
        ),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )

    def __repr__(self):
        return f"<ImportTask(id={self.task_id}, status={self.status})>"


class AnnotationRun(Base):
    """Immutable rule/source snapshot; terminal runs release active_key."""
    __tablename__ = "annotation_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    media_id = Column(String(36), nullable=False, index=True)
    task_id = Column(
        String(36), ForeignKey("import_tasks.task_id", ondelete="SET NULL"), index=True,
    )
    revision = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    snapshot = Column(JSON, nullable=False)
    source_etag = Column(_exact_string(255), nullable=True)
    source_version = Column(_exact_string(255), nullable=True)
    idempotency_hash = Column(_exact_string(64), nullable=False)
    active_key = Column(_exact_string(64), nullable=True)
    planned_frames = Column(Integer, nullable=False, default=0, server_default="0")
    processed_frames = Column(Integer, nullable=False, default=0, server_default="0")
    completed_frames = Column(Integer, nullable=False, default=0, server_default="0")
    failed_frames = Column(Integer, nullable=False, default=0, server_default="0")
    model_elapsed_ms = Column(BigInteger, nullable=False, default=0, server_default="0")
    error = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["media_id", "user_id"], ["media_files.id", "media_files.user_id"],
            name="fk_annotation_runs_media_owner", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "user_id", name="uq_annotation_runs_id_user"),
        UniqueConstraint("user_id", "media_id", "revision", name="uq_annotation_runs_revision"),
        UniqueConstraint("user_id", "media_id", "active_key", name="uq_annotation_runs_active"),
        Index("ix_annotation_runs_identity", "user_id", "media_id", "idempotency_hash"),
        Index("ix_annotation_runs_user_status", "user_id", "status"),
        CheckConstraint("revision > 0", name="ck_annotation_runs_revision"),
        CheckConstraint(f"status IN ({_ANNOTATION_STATUSES})", name="ck_annotation_runs_status"),
        CheckConstraint(
            "planned_frames >= 0 AND processed_frames >= 0 AND completed_frames >= 0 "
            "AND failed_frames >= 0 AND model_elapsed_ms >= 0",
            name="ck_annotation_runs_progress",
        ),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class AnnotationFrame(Base):
    """One display-oriented image and validated objects, never a public URL."""
    __tablename__ = "annotation_frames"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    run_id = Column(String(36), nullable=False, index=True)
    frame_index = Column(Integer, nullable=False)
    timestamp_ms = Column(Float, nullable=True)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    objects = Column(JSON, nullable=False, default=list)
    error = Column(String(200), nullable=True)
    storage_key = Column(_exact_string(500), nullable=True, index=True)
    model_elapsed_ms = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "user_id"], ["annotation_runs.id", "annotation_runs.user_id"],
            name="fk_annotation_frames_run_owner", ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "frame_index", name="uq_annotation_frames_run_index"),
        CheckConstraint(
            "frame_index >= 0 AND width > 0 AND height > 0 AND model_elapsed_ms >= 0 "
            "AND (timestamp_ms IS NULL OR timestamp_ms >= 0)",
            name="ck_annotation_frames_geometry",
        ),
        CheckConstraint(f"status IN ({_ANNOTATION_STATUSES})", name="ck_annotation_frames_status"),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class AnnotationResultSet(Base):
    """Immutable membership with an explicit expiry, scoped to its creator."""
    __tablename__ = "annotation_result_sets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    source = Column(JSON, nullable=False)
    total = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_annotation_result_sets_id_user"),
        CheckConstraint("total >= 0 AND total <= 10000", name="ck_annotation_result_sets_total"),
        CheckConstraint("expires_at > created_at", name="ck_annotation_result_sets_expiry"),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class AnnotationResultSetMember(Base):
    __tablename__ = "annotation_result_set_members"

    snapshot_id = Column(String(36), primary_key=True)
    media_id = Column(
        String(36), ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True, index=True,
    )
    user_id = Column(String(36), nullable=False, index=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "user_id"],
            ["annotation_result_sets.id", "annotation_result_sets.user_id"],
            name="fk_annotation_members_snapshot_owner", ondelete="CASCADE",
        ),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )


class SearchHistory(Base):
    """搜索历史表"""
    __tablename__ = "search_history"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=True, index=True)
    search_type = Column(String(20))
    query_content = Column(Text)
    result_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    def __repr__(self):
        return f"<SearchHistory(type={self.search_type}, results={self.result_count})>"


# ==================== 用户相关模型 ====================

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(100), unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")  # "admin" | "user"
    is_demo = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class LoginLog(Base):
    """登录日志表"""
    __tablename__ = "login_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    status = Column(String(20))  # "success" | "failed"
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_login_logs_user_created", "user_id", "created_at"),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )

    def __repr__(self):
        return f"<LoginLog(user_id={self.user_id}, status={self.status})>"


class UserSession(Base):
    """用户会话表"""
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    refresh_token = Column(_exact_string(500), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        Index("ix_user_sessions_active_expiry", "is_revoked", "expires_at"),
        {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"},
    )

    def __repr__(self):
        return f"<UserSession(user_id={self.user_id})>"


class UserSystemSettings(Base):
    """用户系统设置表"""
    __tablename__ = "user_system_settings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, unique=True, index=True)

    # TOS 对象存储配置
    tos_access_key_id = Column(String(255))
    tos_access_key_secret = Column(String(255))
    tos_security_token = Column(Text)
    tos_bucket_name = Column(String(255))
    tos_endpoint = Column(String(255))
    tos_region = Column(String(50))
    tos_custom_domain = Column(String(255))

    # 方舟 API 配置
    ark_api_key = Column(String(255))

    # 模型配置
    embedding_model = Column(String(100))
    embedding_dimension = Column(Integer)
    tag_model = Column(String(100))

    # 时间戳
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<UserSystemSettings(user_id={self.user_id})>"
