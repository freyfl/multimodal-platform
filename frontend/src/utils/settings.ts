import type { UserSettingsUpdate } from '../api/settings'
import type { ServiceErrorDetail } from '../types'

const secretFields = ['tos_access_key_id', 'tos_access_key_secret', 'tos_security_token', 'ark_api_key'] as const
const textFields = ['tos_bucket_name', 'tos_endpoint', 'tos_region', 'tos_custom_domain', 'embedding_model', 'tag_model'] as const

export function settingsPayload(form: UserSettingsUpdate): UserSettingsUpdate {
  const payload: UserSettingsUpdate = {}
  for (const key of secretFields) {
    const value = form[key]?.trim()
    if (value && !value.includes('*')) payload[key] = value
  }
  for (const key of textFields) {
    if (form[key] !== undefined) payload[key] = form[key]?.trim()
  }
  if (form.embedding_dimension !== undefined) payload.embedding_dimension = form.embedding_dimension
  return payload
}

const serviceNames: Record<ServiceErrorDetail['service'], string> = {
  tos: 'TOS',
  ark: '方舟',
  milvus: 'Milvus',
  mysql: 'RDS MySQL',
  application: '应用',
}

const categoryMessages: Record<string, string> = {
  not_configured: '缺少必要配置',
  authentication: '身份认证失败',
  permission: '访问被拒绝',
  not_found: '资源不存在',
  invalid_request: '请求参数无效',
  timeout: '请求超时',
  rate_limit: '请求频率受限',
  unavailable: '服务不可用',
  invalid_response: '服务返回无效响应',
  incompatible_vector_space: '向量空间与当前集合不兼容',
}

export function formatServiceError(error?: ServiceErrorDetail | null): string {
  if (!error) return '未返回有效测试结果'
  const service = serviceNames[error.service] ?? error.service
  const category = categoryMessages[error.category] ?? '连接失败'
  const missing = error.missing_fields?.length ? `：${error.missing_fields.join('、')}` : ''
  const requestId = error.request_id ? `（请求 ID：${error.request_id}）` : ''
  return `${service} ${category}${missing}${requestId}`
}
