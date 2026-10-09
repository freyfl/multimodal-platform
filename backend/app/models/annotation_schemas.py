"""Annotation wire contracts. No database, settings, credentials or network I/O.

JSON endpoints use the existing ApiResponse envelope; these are its data types.
Frame image is authenticated binary data, not an ApiResponse. Rule snapshots are
internal persistence types and MUST NOT be returned in list/detail responses.
"""

import math
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field,
    StrictBool, StrictInt, StrictStr, model_validator,
)


ANNOTATION_MODEL = "doubao-seed-2-1-lite-260915"
LEGACY_ANNOTATION_MODELS = ("doubao-seed-2-1-pro-260915",)
ANNOTATION_TEMPLATE_VERSION = "autonomous-driving-annotations-v1"
DEFAULT_ANNOTATION_CATEGORIES = (
    "vehicle", "person", "traffic_light", "traffic_sign",
    "road_facility", "obstacle", "unknown",
)
MAX_ANNOTATION_OBJECTS = 200
MAX_ANNOTATION_RESPONSE_BYTES = 1024 * 1024
MAX_CUSTOM_ANNOTATION_PROMPT_LENGTH = 8000
CUBOID_VERTEX_ORDER = (
    "F_TL", "F_TR", "F_BR", "F_BL", "B_TL", "B_TR", "B_BR", "B_BL",
)
CUBOID_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)
ANNOTATION_ENDPOINTS = {
    "config": ("GET", "/api/annotations/config"),
    "search": ("POST", "/api/annotations/search"),
    "media": ("GET", "/api/annotations/media/{media_id}"),
    "frames": ("GET", "/api/annotations/runs/{run_id}/frames"),
    "jobs": ("POST", "/api/annotations/jobs"),
    "result_sets": ("POST", "/api/annotations/result-sets"),
    "frame_image": ("GET", "/api/annotations/frames/{frame_id}/image"),
    "preview": ("GET", "/api/annotations/media/{media_id}/preview"),
}

AnnotationMode = Literal["default", "custom"]
AnnotationBoxMode = Literal["2d", "2d+3d"]
AnnotationStatus = Literal[
    "not_started", "pending", "running", "completed",
    "partial", "failed", "skipped", "cancelled",
]
AnnotationJobAction = Literal["generate", "retry", "regenerate"]
MediaType = Literal["image", "video"]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Text must not be blank")
    # Preserve exact model text: trimming must not merge distinct objects.
    return value


def _finite_number(value):
    if type(value) not in (int, float):
        raise ValueError("Expected a finite number, not a boolean or string")
    try:
        if not math.isfinite(value):
            raise ValueError("Expected a finite number")
    except OverflowError:
        raise ValueError("Expected a finite number") from None
    return value


UnitNumber = Annotated[
    float, BeforeValidator(_finite_number), Field(ge=0, le=1),
]
NonnegativeNumber = Annotated[
    float, BeforeValidator(_finite_number), Field(ge=0),
]
Identifier = Annotated[StrictStr, Field(min_length=1, max_length=128), AfterValidator(_nonblank)]
Category = Annotated[StrictStr, Field(min_length=1, max_length=50), AfterValidator(_nonblank)]
ObjectName = Annotated[StrictStr, Field(min_length=1, max_length=100), AfterValidator(_nonblank)]
UnavailableReason = Annotated[StrictStr, Field(min_length=1, max_length=200), AfterValidator(_nonblank)]
Count = Annotated[StrictInt, Field(ge=0)]
Page = Annotated[StrictInt, Field(ge=1)]
PageSize = Annotated[StrictInt, Field(ge=1, le=100)]
Point2D = Annotated[list[UnitNumber], Field(min_length=2, max_length=2)]
BBox2D = Annotated[list[UnitNumber], Field(min_length=4, max_length=4)]
Cuboid3D = Annotated[list[Point2D], Field(min_length=8, max_length=8)]


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p):
    return (
        _cross(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _segments_intersect(a, b, c, d):
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    return (
        ((ab_c > 0 > ab_d or ab_d > 0 > ab_c)
         and (cd_a > 0 > cd_b or cd_b > 0 > cd_a))
        or _on_segment(a, b, c) or _on_segment(a, b, d)
        or _on_segment(c, d, a) or _on_segment(c, d, b)
    )


def _validate_face(points):
    # Reject touching/overlapping non-adjacent edges as well as bow-ties.
    if len({tuple(point) for point in points}) != 4:
        raise ValueError("Cuboid face has repeated vertices")
    a, b, c, d = points
    area_twice = _cross(a, b, c) + _cross(a, c, d)
    if area_twice == 0:
        raise ValueError("Cuboid face has zero area")
    if _segments_intersect(a, b, c, d) or _segments_intersect(b, c, d, a):
        raise ValueError("Cuboid face intersects itself")


class AnnotationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, allow_inf_nan=False,
    )


class AnnotationModelObject(AnnotationSchema):
    category: Category
    name: ObjectName
    confidence: UnitNumber
    bbox_2d: BBox2D
    cuboid_3d: Optional[Cuboid3D]
    cuboid_unavailable_reason: Optional[UnavailableReason]
    occluded: StrictBool
    truncated: StrictBool

    @model_validator(mode="after")
    def validate_geometry(self):
        xmin, ymin, xmax, ymax = self.bbox_2d
        if xmin >= xmax or ymin >= ymax:
            raise ValueError("2D box must have positive width and height")
        if self.cuboid_3d is None:
            if self.cuboid_unavailable_reason is None:
                raise ValueError("Missing cuboid requires a reason")
        else:
            if self.cuboid_unavailable_reason is not None:
                raise ValueError("Available cuboid must have a null reason")
            _validate_face(self.cuboid_3d[:4])
            _validate_face(self.cuboid_3d[4:])
        return self


class AnnotationModelResponse(AnnotationSchema):
    objects: list[AnnotationModelObject] = Field(max_length=MAX_ANNOTATION_OBJECTS)


class AnnotationObject(AnnotationModelObject):
    """Only the server adds object_id after the whole frame has passed validation."""

    object_id: Identifier


class AnnotationOptions(AnnotationSchema):
    """Mixin contract for all import entry points; no additional model/key field."""

    generate_annotations: StrictBool = True
    annotation_mode: AnnotationMode = "default"
    custom_annotation_prompt: Optional[StrictStr] = Field(default=None, repr=False)
    annotation_box_mode: AnnotationBoxMode = "2d"
    annotation_sample_interval_seconds: Annotated[StrictInt, Field(ge=1, le=60)] = 1
    annotation_max_frames: Annotated[StrictInt, Field(ge=1, le=120)] = 60

    @model_validator(mode="before")
    @classmethod
    def ignore_disabled_prompt(cls, value):
        if isinstance(value, dict) and value.get("generate_annotations") is False:
            return {**value, "custom_annotation_prompt": None}
        return value

    @model_validator(mode="after")
    def validate_prompt(self):
        if not self.generate_annotations:
            self.custom_annotation_prompt = None
            return self
        prompt = (self.custom_annotation_prompt or "").strip()
        if self.annotation_mode == "default":
            if prompt:
                raise ValueError("Default annotation mode does not accept a custom prompt")
            self.custom_annotation_prompt = None
        elif not 1 <= len(prompt) <= MAX_CUSTOM_ANNOTATION_PROMPT_LENGTH:
            raise ValueError("Custom annotation prompt must contain 1-8000 characters")
        else:
            self.custom_annotation_prompt = prompt
        return self


class AnnotationRuleSnapshot(AnnotationSchema):
    model_config = ConfigDict(frozen=True)

    annotation_mode: AnnotationMode
    prompt: StrictStr = Field(min_length=1, repr=False)
    template_version: Literal["autonomous-driving-annotations-v1"]
    model: Literal[
        "doubao-seed-2-1-lite-260915",
        "doubao-seed-2-1-pro-260915",
    ]
    annotation_box_mode: AnnotationBoxMode
    annotation_sample_interval_seconds: Annotated[StrictInt, Field(ge=1, le=60)]
    annotation_max_frames: Annotated[StrictInt, Field(ge=1, le=120)]
    source_etag: Optional[StrictStr]
    source_version: Optional[StrictStr]
    rule_hash: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class AnnotationLimits(AnnotationSchema):
    max_objects: StrictInt = MAX_ANNOTATION_OBJECTS
    max_category_length: StrictInt = 50
    max_name_length: StrictInt = 100
    max_reason_length: StrictInt = 200
    max_prompt_length: StrictInt = MAX_CUSTOM_ANNOTATION_PROMPT_LENGTH
    max_response_bytes: StrictInt = MAX_ANNOTATION_RESPONSE_BYTES
    min_sample_interval_seconds: StrictInt = 1
    max_sample_interval_seconds: StrictInt = 60
    max_frames: StrictInt = 120
    max_video_bytes: StrictInt = 2 * 1024**3
    max_video_duration_ms: StrictInt = 30 * 60 * 1000
    max_frame_long_edge: StrictInt = 7680
    max_frame_short_edge: StrictInt = 4320
    decode_concurrency: StrictInt = 1
    max_filenames: StrictInt = 100
    max_filename_length: StrictInt = 255
    max_result_set_members: StrictInt = 10000
    result_set_ttl_seconds: StrictInt = 86400


class AnnotationConfigResponse(AnnotationSchema):
    default_prompt: StrictStr
    template_version: StrictStr = ANNOTATION_TEMPLATE_VERSION
    model: StrictStr = ANNOTATION_MODEL
    categories: list[StrictStr] = Field(default_factory=lambda: list(DEFAULT_ANNOTATION_CATEGORIES))
    box_modes: list[AnnotationBoxMode] = Field(default_factory=lambda: ["2d", "2d+3d"])
    defaults: AnnotationOptions = Field(default_factory=AnnotationOptions)
    limits: AnnotationLimits = Field(default_factory=AnnotationLimits)


class AnnotationSearchRequest(AnnotationSchema):
    # Raw CSV input; parse_filenames() implements exact basename matching tokens.
    filenames: StrictStr = Field(default="", max_length=60000)
    file_type: Optional[MediaType] = None
    status: Optional[AnnotationStatus] = None
    result_set_id: Optional[Identifier] = None
    page: Page = 1
    size: PageSize = 20


class AnnotationProgress(AnnotationSchema):
    planned_frames: Count = 0
    processed_frames: Count = 0
    completed_frames: Count = 0
    failed_frames: Count = 0


class AnnotationTaskProgress(AnnotationProgress):
    total_files: Count = 0
    processed_files: Count = 0
    completed_files: Count = 0
    failed_files: Count = 0
    current_media_id: Optional[Identifier] = None
    current_frame_index: Optional[Count] = None
    elapsed_ms: NonnegativeNumber = 0


class AnnotationMediaItem(AnnotationSchema):
    media_id: Identifier
    user_id: Optional[Identifier] = None
    file_name: StrictStr
    tos_url: StrictStr
    file_type: MediaType
    status: AnnotationStatus = "not_started"
    published_run_id: Optional[Identifier] = None
    latest_run_id: Optional[Identifier] = None
    object_count: Count = 0
    progress: AnnotationProgress = Field(default_factory=AnnotationProgress)
    annotation_mode: Optional[AnnotationMode] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class AnnotationSearchResponse(AnnotationSchema):
    results: list[AnnotationMediaItem]
    total: Count
    page: Page
    size: PageSize


class AnnotationRunSummary(AnnotationSchema):
    id: Identifier
    user_id: Identifier
    media_id: Identifier
    task_id: Optional[Identifier] = None
    revision: Page
    status: AnnotationStatus
    annotation_mode: AnnotationMode
    annotation_box_mode: AnnotationBoxMode
    template_version: StrictStr
    model: StrictStr
    annotation_sample_interval_seconds: Annotated[StrictInt, Field(ge=1, le=60)]
    annotation_max_frames: Annotated[StrictInt, Field(ge=1, le=120)]
    progress: AnnotationProgress
    model_elapsed_ms: NonnegativeNumber = 0
    error: Optional[UnavailableReason] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AnnotationMediaDetail(AnnotationSchema):
    media: AnnotationMediaItem
    published_run: Optional[AnnotationRunSummary] = None
    latest_run: Optional[AnnotationRunSummary] = None
    # Frame data comes only from paginated GET runs/{run_id}/frames.


class AnnotationFrame(AnnotationSchema):
    id: Identifier
    user_id: Identifier
    run_id: Identifier
    frame_index: Count
    # Actual presentation time since video start, not frame_index / FPS.
    timestamp_ms: Optional[NonnegativeNumber]
    width: Annotated[StrictInt, Field(ge=1)]
    height: Annotated[StrictInt, Field(ge=1)]
    status: AnnotationStatus
    objects: list[AnnotationObject] = Field(default_factory=list, max_length=200)
    error: Optional[UnavailableReason] = None


class AnnotationFramesResponse(AnnotationSchema):
    results: list[AnnotationFrame]
    total: Count
    page: Page
    size: PageSize


class AnnotationJobRequest(AnnotationSchema):
    media_ids: list[Identifier] = Field(min_length=1, max_length=100)
    action: AnnotationJobAction = "generate"
    options: Optional[AnnotationOptions] = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "retry" and self.options is not None:
            raise ValueError("Retry must reuse the stored snapshot without new options")
        if self.options is not None and not self.options.generate_annotations:
            raise ValueError("An annotation job cannot disable annotations")
        self.media_ids = list(dict.fromkeys(self.media_ids))
        return self


class AnnotationJobResponse(AnnotationSchema):
    task_id: Identifier
    status: AnnotationStatus
    media_ids: list[Identifier]
    run_ids: list[Identifier]


class AnnotationTagIdentity(AnnotationSchema):
    source: Literal["default", "custom"]
    category: Category
    name: ObjectName


class AnnotationResultSetRequest(AnnotationSchema):
    tags: list[AnnotationTagIdentity] = Field(min_length=1)
    logic: Literal["AND", "OR"] = "AND"


class AnnotationResultSetResponse(AnnotationSchema):
    result_set_id: Identifier
    total: Annotated[StrictInt, Field(ge=0, le=10000)]
    source: AnnotationResultSetRequest
    created_at: datetime
    expires_at: datetime


class AnnotationPreviewResponse(AnnotationSchema):
    media_id: Identifier
    preview_url: StrictStr = Field(repr=False)
    expires_at: datetime
