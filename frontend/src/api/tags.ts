import api from './index'
import type { ApiResponse, TagSystemResponse, TagUpdateItem } from './types'

export async function getTagSystem(): Promise<ApiResponse<TagSystemResponse>> {
  return api.get('/tags')
}

export async function updateMediaTags(mediaId: string, tags: TagUpdateItem[]): Promise<ApiResponse> {
  return api.put(`/tags/media/${mediaId}`, { tags })
}

export async function removeMediaTag(mediaId: string, tagId: string): Promise<ApiResponse> {
  return api.delete(`/tags/media/${mediaId}/tags/${tagId}`)
}
