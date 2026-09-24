// 全局类型定义
import type { AnnotationOptions, AnnotationTaskFields } from './annotation'

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

export interface ServiceErrorDetail {
  service: 'tos' | 'ark' | 'milvus' | 'mysql' | 'application'
  category: string
  message: string
  retryable: boolean
  request_id?: string | null
  missing_fields?: string[]
}

export interface MediaFile {
  id: string
  file_name: string
  tos_url: string
  preview_url?: string | null
  file_type: 'image' | 'video'
  file_size: number
  vector_status: 'pending' | 'processing' | 'done' | 'failed'
  tag_status: 'pending' | 'processing' | 'done' | 'failed'
  tags: MediaTag[]
  created_at: string
}

export interface MediaTag {
  id?: string
  source: TagSource
  tag_name: string
  category: string
  confidence: number
  is_manual?: boolean
}

export type TagSource = 'default' | 'custom'

export interface ImportTask extends Partial<AnnotationTaskFields> {
  task_id: string
  tos_directory: string
  tag_mode: TagSource
  status: 'pending' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'
  total_files: number
  processed_files: number
  failed_files: number
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  error_message?: string | null
  generate_vectors?: boolean
  generate_tags?: boolean
  generate_annotations?: boolean
  annotation_mode?: AnnotationOptions['annotation_mode']
  annotation_box_mode?: AnnotationOptions['annotation_box_mode']
  annotation_sample_interval_seconds?: number
  annotation_max_frames?: number
  annotation_retry_media_ids?: string[]
  current_stage?: string | null
  vector_status?: string
  tag_status?: string
}

export interface StartImportParams extends AnnotationOptions {
  tos_directory: string
  embedding_model: string
  embedding_dimension: number
  tag_model: string
  generate_vectors: boolean
  generate_tags: boolean
  tag_mode: TagSource
  custom_tag_prompt?: string | null
}

export interface SystemStats {
  media: {
    total: number
    images: number
    videos: number
    storage_used_gb: number
  }
  vectors: {
    total: number | null
    dimension: number
    status?: string
    error?: string | null
  }
  tasks: {
    running: number
    pending: number
    completed_today: number
  }
  performance: {
    total_searches: number
    tag_searches: number
    text_searches: number
    image_searches: number
  }
}

export interface TagCategory {
  name: string
  tags: { name: string; count: number }[]
}

export interface TagIdentity {
  source: TagSource
  category: string
  name: string
}

export interface TagSystemResponse {
  default: TagIdentity[]
  custom: TagIdentity[]
  default_prompt: string
}

export interface TagUpdateItem extends TagIdentity {
  confidence?: number
}

export interface TagSearchRequest {
  tags: TagIdentity[]
  logic: 'AND' | 'OR'
  page?: number
  size?: number
}

export interface TextSearchRequest {
  query: string
  top_k?: number
}

export interface ImageSearchRequest {
  image: File | Blob
  top_k?: number
  threshold?: number
}

export interface SearchResult {
  results: SearchResultItem[]
  total: number
  page?: number
  size?: number
}

export interface SearchResultItem {
  media_id: string
  tos_url: string
  preview_url?: string | null
  file_type: 'image' | 'video'
  file_name: string
  similarity: number
  tags?: MediaTag[] | null
}

export interface ModelCatalog {
  embedding_models: Record<string, { name: string; dimensions: number[]; default_dimension: number }>
  tag_models: Record<string, { name: string; description: string }>
  defaults: {
    embedding_model: string
    embedding_dimension: number
    tag_model: string
    text_search_min_score: number
  }
  vector_space: {
    model: string
    dimension: number
    corpus_instruction_version: string
    query_instruction_version: string
    collection: string
  }
}

export interface PublicSystemConfig {
  apiPrefix: string
  appName: string
  version: string
  model_catalog: ModelCatalog
}

export interface ReadinessStatus {
  status: 'ready' | 'unavailable'
  services: Record<'tos' | 'mysql' | 'milvus', {
    status: 'ready' | 'unavailable'
    error: ServiceErrorDetail | null
  }>
}

// ── Auth Types ──
export interface AuthUser {
  id: string
  username: string
  email: string | null
  role: string
  is_demo: number
  is_active: number
  created_at: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: AuthUser
}

export interface RefreshResponse {
  access_token: string
  token_type: string
}
