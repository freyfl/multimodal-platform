// T1 wire contract. Existing import/task types are owned by T6.
// JSON responses use ApiResponse<T>; frame_image returns an authenticated Blob.
// Numeric geometry requires server validation; TS alone cannot ensure finiteness.
export type AnnotationMode = 'default' | 'custom'
export type AnnotationBoxMode = '2d' | '2d+3d'
export type AnnotationStatus =
  | 'not_started' | 'pending' | 'running' | 'completed'
  | 'partial' | 'failed' | 'skipped' | 'cancelled'
export type AnnotationJobAction = 'generate' | 'retry' | 'regenerate'
export type AnnotationMediaType = 'image' | 'video'
export type Point2D = [number, number]
export type BBox2D = [number, number, number, number]
export type Cuboid3D = [
  Point2D, Point2D, Point2D, Point2D, Point2D, Point2D, Point2D, Point2D,
]

export const CUBOID_VERTEX_ORDER = [
  'F_TL', 'F_TR', 'F_BR', 'F_BL', 'B_TL', 'B_TR', 'B_BR', 'B_BL',
] as const
export const CUBOID_EDGES = [
  [0, 1], [1, 2], [2, 3], [3, 0],
  [4, 5], [5, 6], [6, 7], [7, 4],
  [0, 4], [1, 5], [2, 6], [3, 7],
] as const
export const ANNOTATION_ENDPOINTS = {
  config: ['GET', '/api/annotations/config'],
  search: ['POST', '/api/annotations/search'],
  media: ['GET', '/api/annotations/media/{media_id}'],
  frames: ['GET', '/api/annotations/runs/{run_id}/frames'],
  jobs: ['POST', '/api/annotations/jobs'],
  result_sets: ['POST', '/api/annotations/result-sets'],
  frame_image: ['GET', '/api/annotations/frames/{frame_id}/image'],
  preview: ['GET', '/api/annotations/media/{media_id}/preview'],
} as const

export interface AnnotationModelObject {
  category: string
  name: string
  confidence: number
  bbox_2d: BBox2D
  cuboid_3d: Cuboid3D | null
  cuboid_unavailable_reason: string | null
  occluded: boolean
  truncated: boolean
}

export interface AnnotationModelResponse {
  objects: AnnotationModelObject[]
}

export interface AnnotationObject extends AnnotationModelObject {
  object_id: string
}

export interface AnnotationOptions {
  generate_annotations: boolean
  annotation_mode: AnnotationMode
  custom_annotation_prompt: string | null
  annotation_box_mode: AnnotationBoxMode
  annotation_sample_interval_seconds: number
  annotation_max_frames: number
}

// Requests may omit default-valued fields; config.defaults is fully populated.
export type AnnotationOptionsRequest = Partial<AnnotationOptions>

export interface AnnotationLimits {
  max_objects: number
  max_category_length: number
  max_name_length: number
  max_reason_length: number
  max_prompt_length: number
  max_response_bytes: number
  min_sample_interval_seconds: number
  max_sample_interval_seconds: number
  max_frames: number
  max_video_bytes: number
  max_video_duration_ms: number
  max_frame_long_edge: number
  max_frame_short_edge: number
  decode_concurrency: number
  max_filenames: number
  max_filename_length: number
  max_result_set_members: number
  result_set_ttl_seconds: number
}

export interface AnnotationConfigResponse {
  default_prompt: string
  template_version: string
  model: string
  categories: string[]
  box_modes: AnnotationBoxMode[]
  defaults: AnnotationOptions
  limits: AnnotationLimits
}

export interface AnnotationSearchRequest {
  filenames?: string
  file_type?: AnnotationMediaType | null
  status?: AnnotationStatus | null
  result_set_id?: string | null
  page?: number
  size?: number
}

export interface AnnotationProgress {
  planned_frames: number
  processed_frames: number
  completed_frames: number
  failed_frames: number
}

export interface AnnotationTaskProgress extends AnnotationProgress {
  total_files: number
  processed_files: number
  completed_files: number
  failed_files: number
  current_media_id: string | null
  current_frame_index: number | null
  elapsed_ms: number
}

// T6 can extend its existing ImportTask with these two fields.
export interface AnnotationTaskFields {
  annotation_status: AnnotationStatus
  annotation_progress: AnnotationTaskProgress
}

export interface AnnotationMediaItem {
  media_id: string
  user_id: string | null
  file_name: string
  tos_url: string
  file_type: AnnotationMediaType
  status: AnnotationStatus
  published_run_id: string | null
  latest_run_id: string | null
  // Video count is summed per frame, not unique tracked objects.
  object_count: number
  progress: AnnotationProgress
  annotation_mode: AnnotationMode | null
  created_at: string
  updated_at: string | null
}

export interface AnnotationSearchResponse {
  results: AnnotationMediaItem[]
  total: number
  page: number
  size: number
}

export interface AnnotationRunSummary {
  id: string
  user_id: string
  media_id: string
  task_id: string | null
  revision: number
  status: AnnotationStatus
  annotation_mode: AnnotationMode
  annotation_box_mode: AnnotationBoxMode
  template_version: string
  model: string
  annotation_sample_interval_seconds: number
  annotation_max_frames: number
  progress: AnnotationProgress
  model_elapsed_ms: number
  error: string | null
  created_at: string
  updated_at: string | null
  completed_at: string | null
}

export interface AnnotationMediaDetail {
  media: AnnotationMediaItem
  published_run: AnnotationRunSummary | null
  latest_run: AnnotationRunSummary | null
}

export interface AnnotationFrame {
  id: string
  user_id: string
  run_id: string
  frame_index: number
  // Actual presentation milliseconds since video start; null for an image.
  timestamp_ms: number | null
  width: number
  height: number
  status: AnnotationStatus
  objects: AnnotationObject[]
  error: string | null
}

export interface AnnotationFramesResponse {
  results: AnnotationFrame[]
  total: number
  page: number
  size: number
}

export type AnnotationJobRequest = {
  media_ids: string[]
} & (
  | { action: 'retry'; options?: null }
  | { action?: 'generate' | 'regenerate'; options?: AnnotationOptionsRequest | null }
)

export interface AnnotationJobResponse {
  task_id: string
  status: AnnotationStatus
  media_ids: string[]
  run_ids: string[]
}

export interface AnnotationTagIdentity {
  source: 'default' | 'custom'
  category: string
  name: string
}

export interface AnnotationResultSetRequest {
  tags: AnnotationTagIdentity[]
  logic?: 'AND' | 'OR'
}

export interface AnnotationResultSetResponse {
  result_set_id: string
  total: number
  source: AnnotationResultSetRequest
  created_at: string
  expires_at: string
}

export interface AnnotationPreviewResponse {
  media_id: string
  // Short-lived bearer credential: never log/store; at most one auto-renewal.
  preview_url: string
  expires_at: string
}

export interface AnnotationApiContract {
  getConfig(): Promise<AnnotationConfigResponse>
  search(request: AnnotationSearchRequest): Promise<AnnotationSearchResponse>
  getMedia(mediaId: string): Promise<AnnotationMediaDetail>
  getFrames(runId: string, page?: number, size?: number): Promise<AnnotationFramesResponse>
  createJob(request: AnnotationJobRequest): Promise<AnnotationJobResponse>
  createResultSet(request: AnnotationResultSetRequest): Promise<AnnotationResultSetResponse>
  getFrameImage(frameId: string): Promise<Blob>
  getPreview(mediaId: string): Promise<AnnotationPreviewResponse>
}
