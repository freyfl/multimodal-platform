import api from './index'
import type { ApiResponse, SearchResult, SearchResultItem, TagSearchRequest, TextSearchRequest } from './types'

interface SearchApiData {
  items: SearchResultItem[]
  total: number
  page?: number
  size?: number
}

function normalizeSearchResponse(response: ApiResponse<SearchApiData>): ApiResponse<SearchResult> {
  return {
    ...response,
    data: {
      results: response.data.items,
      total: response.data.total,
      page: response.data.page,
      size: response.data.size,
    },
  }
}

export async function searchByTags(params: TagSearchRequest): Promise<ApiResponse<SearchResult>> {
  const response = await api.post('/search/tags', params) as unknown as ApiResponse<SearchApiData>
  return normalizeSearchResponse(response)
}

export async function searchByText(params: TextSearchRequest): Promise<ApiResponse<SearchResult>> {
  const response = await api.post('/search/text', params) as unknown as ApiResponse<SearchApiData>
  return normalizeSearchResponse(response)
}

export async function searchByImage(formData: FormData): Promise<ApiResponse<SearchResult>> {
  const response = await api.post('/search/image', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  }) as unknown as ApiResponse<SearchApiData>
  return normalizeSearchResponse(response)
}
