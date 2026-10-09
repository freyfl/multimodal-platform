"""
Pydantic Schema 定义 - API 请求和响应模型
"""
from datetime import datetime
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from enum import Enum
from app.vector_space import ARK_EMBEDDING_MODEL, ARK_TAG_MODEL, EMBEDDING_MODELS, TAG_MODELS
from app.models.annotation_schemas import AnnotationOptions, AnnotationStatus, AnnotationTaskProgress


TagSource = Literal["default", "custom"]
MAX_CUSTOM_TAG_PROMPT_LENGTH = 10_000


# ==================== 枚举定义 ====================

class FileType(str, Enum):
    """文件类型"""
    VIDEO = "video"
    IMAGE = "image"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VectorStatus(str, Enum):
    """向量化状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# ==================== 通用响应 ====================

class ApiResponse(BaseModel):
    """统一API响应格式"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    data: Optional[Any] = Field(default=None, description="数据")

    model_config = ConfigDict(
        json_schema_extra={"example": {"code": 200, "message": "success", "data": {}}}
    )


# ==================== 导入任务相关 ====================

class ImportStartRequest(AnnotationOptions):
    """启动导入请求"""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tos_directory: str = Field(..., description="TOS目录路径", min_length=1, max_length=2048)
    # 向量模型选择
    embedding_model: Literal["doubao-embedding-vision-251215"] = Field(default=ARK_EMBEDDING_MODEL, description="向量化模型")
    embedding_dimension: Literal[1024] = Field(default=1024, description="向量维度")
    # 标签模型选择
    tag_model: Literal["doubao-seed-2-1-lite-260915"] = Field(default=ARK_TAG_MODEL, description="标签生成模型")
    # 处理选项
    generate_vectors: bool = Field(default=True, description="是否生成向量")
    generate_tags: bool = Field(default=True, description="是否生成标签")
    tag_mode: TagSource = Field(default="default", description="标签生成模式")
    custom_tag_prompt: Optional[str] = Field(
        default=None, description="自定义标签 Prompt", repr=False,
    )

    @field_validator("tos_directory")
    @classmethod
    def validate_tos_directory(cls, v: str) -> str:
        # Query/fragment characters are literal object-key characters in TOS URIs.
        bucket = v[6:].split("/", 1)[0] if v.startswith("tos://") else ""
        if not bucket or any(char in bucket for char in "?#@: \t\r\n") or "/" not in v[6:]:
            raise ValueError("TOS目录路径必须为 tos://bucket/ 或 tos://bucket/prefix/")
        return v

    @model_validator(mode="after")
    def validate_tag_prompt(self):
        prompt = self.custom_tag_prompt.strip() if self.custom_tag_prompt is not None else ""
        if not self.generate_tags:
            self.custom_tag_prompt = None
            return self
        if self.tag_mode == "default":
            if prompt:
                raise ValueError("default 标签模式不接受 custom_tag_prompt")
            self.custom_tag_prompt = None
            return self
        if not prompt:
            raise ValueError("custom 标签模式要求非空 custom_tag_prompt")
        if len(prompt) > MAX_CUSTOM_TAG_PROMPT_LENGTH:
            raise ValueError(
                f"custom_tag_prompt 最多 {MAX_CUSTOM_TAG_PROMPT_LENGTH} 个字符"
            )
        self.custom_tag_prompt = prompt
        return self


class ImportTaskResponse(BaseModel):
    """导入任务响应"""
    task_id: str
    status: str
    tos_directory: str
    created_at: datetime


class ImportTaskDetail(BaseModel):
    """导入任务详情"""
    task_id: str
    tos_directory: str
    tag_mode: TagSource = "default"
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    generate_annotations: Optional[bool] = None
    annotation_mode: Optional[Literal["default", "custom"]] = None
    annotation_box_mode: Optional[Literal["2d", "2d+3d"]] = None
    annotation_sample_interval_seconds: Optional[int] = None
    annotation_max_frames: Optional[int] = None
    annotation_status: AnnotationStatus = "not_started"
    annotation_progress: AnnotationTaskProgress = Field(default_factory=AnnotationTaskProgress)
    annotation_retry_media_ids: List[str] = Field(default_factory=list)

    @property
    def progress(self) -> float:
        """计算进度百分比"""
        if self.total_files == 0:
            return 0.0
        return round(self.processed_files / self.total_files * 100, 2)


class ImportTaskListResponse(BaseModel):
    """导入任务列表响应"""
    tasks: List[ImportTaskDetail]
    total: int


# ==================== 搜索相关 ====================

class TagIdentity(BaseModel):
    """来源感知的标签身份。"""
    model_config = ConfigDict(extra="forbid")

    source: TagSource
    category: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("category", "name")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标签类别和名称不能为空")
        return value


class TagItem(BaseModel):
    """媒体及搜索结果中的标签项。"""
    model_config = ConfigDict(extra="forbid")

    source: TagSource = "default"
    category: str
    tag_name: str
    confidence: float
    is_manual: bool = False


class TagSearchRequest(BaseModel):
    """标签搜索请求"""
    model_config = ConfigDict(extra="forbid")

    tags: List[TagIdentity] = Field(..., description="标签列表", min_length=1)
    logic: Literal["AND", "OR"] = Field(default="AND", description="组合逻辑: AND/OR")
    page: int = Field(default=1, ge=1, description="页码")
    size: int = Field(default=20, ge=1, le=100, description="每页数量")


class TextSearchRequest(BaseModel):
    """文本搜索请求"""
    query: str = Field(..., description="搜索文本", min_length=1, max_length=500)
    top_k: int = Field(default=20, ge=1, le=100, description="返回数量")


class ImageSearchRequest(BaseModel):
    """图片搜索请求 (用于表单数据)"""
    threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="相似度阈值")
    top_k: int = Field(default=20, ge=1, le=100, description="返回数量")


class SearchResultItem(BaseModel):
    """搜索结果项"""
    media_id: str
    tos_url: str
    preview_url: Optional[str] = None
    file_type: str
    file_name: str
    similarity: float = Field(ge=0, le=1, description="相似度分数")
    tags: Optional[List[TagItem]] = Field(default=None, description="标签列表")


class SearchResponse(BaseModel):
    """搜索响应"""
    results: List[SearchResultItem]
    total: int
    page: Optional[int] = None
    size: Optional[int] = None


# ==================== 标签相关 ====================

class TagSystemResponse(BaseModel):
    """标签体系响应"""
    model_config = ConfigDict(extra="forbid")

    default: List[TagIdentity] = Field(default_factory=list)
    custom: List[TagIdentity] = Field(default_factory=list)
    default_prompt: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_group_sources(self):
        if any(item.source != "default" for item in self.default):
            raise ValueError("default 分组只能包含 default 标签")
        if any(item.source != "custom" for item in self.custom):
            raise ValueError("custom 分组只能包含 custom 标签")
        return self


class TagUpdateRequest(BaseModel):
    """标签更新请求"""
    tags: List[dict] = Field(..., description="标签列表")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tags": [
                    {"category": "vehicle", "name": "轿车", "confidence": 0.95, "is_manual": True}
                ]
            }
        }
    )


# ==================== 系统状态相关 ====================

class SystemStats(BaseModel):
    """系统统计"""
    media: dict
    vectors: dict
    tasks: dict
    performance: dict


class HealthCheck(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str
    timestamp: datetime = Field(default_factory=datetime.now)


# ==================== 用户相关 ====================

class UserCreate(BaseModel):
    """用户注册 / 管理员创建用户请求"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    email: Optional[str] = Field(default=None, max_length=100)
    role: str = Field(default="user", pattern="^(admin|user)$")
    is_demo: int = Field(default=0, ge=0, le=1)


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str
    password: str


class UserResponse(BaseModel):
    """用户信息响应"""
    id: str
    username: str
    email: Optional[str] = None
    role: str
    is_demo: int = 0
    is_active: int = 1
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    """Token 响应（登录/注册返回）"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    """刷新 Token 请求"""
    refresh_token: str


class PasswordChange(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    """管理员更新用户请求"""
    email: Optional[str] = None
    role: Optional[str] = None
    is_demo: Optional[int] = None
    is_active: Optional[int] = None


class PaginatedUsers(BaseModel):
    """分页用户列表"""
    items: List[UserResponse]
    total: int
    page: int
    page_size: int


# ==================== 用户系统设置相关 ====================

class UserSettingsUpdate(BaseModel):
    """用户系统设置创建/更新"""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tos_access_key_id: Optional[str] = Field(default=None, repr=False)
    tos_access_key_secret: Optional[str] = Field(default=None, repr=False)
    tos_security_token: Optional[str] = Field(default=None, repr=False)
    tos_bucket_name: Optional[str] = None
    tos_endpoint: Optional[str] = None
    tos_region: Optional[str] = None
    tos_custom_domain: Optional[str] = None
    ark_api_key: Optional[str] = Field(default=None, repr=False)
    embedding_model: Optional[Literal["doubao-embedding-vision-251215"]] = None
    embedding_dimension: Optional[Literal[1024]] = None
    tag_model: Optional[Literal["doubao-seed-2-1-lite-260915"]] = None

    @field_validator("tos_access_key_id", "tos_access_key_secret", "tos_security_token", "ark_api_key")
    @classmethod
    def preserve_blank_secret(cls, value: Optional[str]) -> Optional[str]:
        """空白不覆盖已有密钥；更新 SQL 必须排除 None。"""
        return None if value is not None and not value.strip() else value

    def updates(self) -> dict:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class UserSettingsResponse(BaseModel):
    """用户系统设置响应（敏感字段脱敏）"""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str
    user_id: str
    tos_access_key_id_masked: Optional[str] = None
    tos_access_key_secret_masked: Optional[str] = None
    tos_security_token_masked: Optional[str] = None
    tos_bucket_name: Optional[str] = None
    tos_endpoint: Optional[str] = None
    tos_region: Optional[str] = None
    tos_custom_domain: Optional[str] = None
    ark_api_key_masked: Optional[str] = None
    embedding_model: Optional[Literal["doubao-embedding-vision-251215"]] = None
    embedding_dimension: Optional[Literal[1024]] = None
    tag_model: Optional[Literal["doubao-seed-2-1-lite-260915"]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("tos_access_key_id_masked", "tos_access_key_secret_masked", "tos_security_token_masked", "ark_api_key_masked")
    @classmethod
    def mask_secret(cls, value: Optional[str]) -> Optional[str]:
        return "****" if value else None


class ModelCatalog(BaseModel):
    embedding_models: dict
    tag_models: dict
    defaults: dict
    vector_space: dict


class PublicSystemConfig(BaseModel):
    """GET /system/config 的 data，沿用现有基础字段命名。"""
    apiPrefix: str = "/api"
    appName: str
    version: str
    model_catalog: ModelCatalog
