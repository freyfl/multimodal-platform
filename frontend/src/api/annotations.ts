import api from './index'
import type { ApiResponse } from '@/types'
import type {
  AnnotationConfigResponse, AnnotationSearchRequest, AnnotationSearchResponse,
  AnnotationMediaDetail, AnnotationFramesResponse, AnnotationJobRequest,
  AnnotationJobResponse, AnnotationResultSetRequest, AnnotationResultSetResponse,
  AnnotationPreviewResponse,
} from '@/types/annotation'

// The shared interceptor unwraps AxiosResponse, not the ApiResponse envelope.
export function getAnnotationConfig(signal?: AbortSignal): Promise<ApiResponse<AnnotationConfigResponse>> {
  return api.get('/annotations/config', { signal }) as unknown as Promise<ApiResponse<AnnotationConfigResponse>>
}

export function searchAnnotations(request: AnnotationSearchRequest, signal?: AbortSignal): Promise<ApiResponse<AnnotationSearchResponse>> {
  return api.post('/annotations/search', request, { signal }) as unknown as Promise<ApiResponse<AnnotationSearchResponse>>
}

export function getAnnotationMedia(mediaId: string, signal?: AbortSignal): Promise<ApiResponse<AnnotationMediaDetail>> {
  return api.get(`/annotations/media/${encodeURIComponent(mediaId)}`, { signal }) as unknown as Promise<ApiResponse<AnnotationMediaDetail>>
}

export function getAnnotationFrames(runId: string, page = 1, size = 100, signal?: AbortSignal): Promise<ApiResponse<AnnotationFramesResponse>> {
  return api.get(`/annotations/runs/${encodeURIComponent(runId)}/frames`, {
    params: { page, size }, signal,
  }) as unknown as Promise<ApiResponse<AnnotationFramesResponse>>
}

export function createAnnotationJob(request: AnnotationJobRequest, signal?: AbortSignal): Promise<ApiResponse<AnnotationJobResponse>> {
  return api.post('/annotations/jobs', request, { signal }) as unknown as Promise<ApiResponse<AnnotationJobResponse>>
}

export function createAnnotationResultSet(request: AnnotationResultSetRequest, signal?: AbortSignal): Promise<ApiResponse<AnnotationResultSetResponse>> {
  return api.post('/annotations/result-sets', request, { signal }) as unknown as Promise<ApiResponse<AnnotationResultSetResponse>>
}

export function getAnnotationResultSet(id: string, signal?: AbortSignal): Promise<ApiResponse<AnnotationResultSetResponse>> {
  return api.get(`/annotations/result-sets/${encodeURIComponent(id)}`, { signal }) as unknown as Promise<ApiResponse<AnnotationResultSetResponse>>
}

export function getAnnotationFrameImage(frameId: string, signal?: AbortSignal): Promise<Blob> {
  // Use the authenticated client (including token refresh), never a public img URL.
  return api.get(`/annotations/frames/${encodeURIComponent(frameId)}/image`, {
    responseType: 'blob', signal,
  }) as unknown as Promise<Blob>
}

export function getAnnotationPreview(mediaId: string, signal?: AbortSignal): Promise<ApiResponse<AnnotationPreviewResponse>> {
  return api.get(`/annotations/media/${encodeURIComponent(mediaId)}/preview`, { signal }) as unknown as Promise<ApiResponse<AnnotationPreviewResponse>>
}
