import type {
  AnnotationFrame, AnnotationFramesResponse, AnnotationMediaItem,
  AnnotationResultSetResponse, AnnotationStatus,
} from '@/types/annotation'

export const annotationStatusLabels: Record<AnnotationStatus, string> = {
  not_started: '未标注', pending: '等待中', running: '标注中', completed: '已完成',
  partial: '部分失败', failed: '失败', skipped: '已跳过', cancelled: '已取消',
}

export function parseAnnotationFilenames(input: string): string[] {
  const names: string[] = []
  let value = ''
  let quoted = false
  let closed = false
  const flush = () => {
    const name = value.trim()
    if ([...name].length > 255) throw new Error('每个文件名最多 255 个字符')
    if (name && !names.includes(name)) names.push(name)
    value = ''
    closed = false
  }
  for (let i = 0; i < input.length; i++) {
    const char = input[i]
    if (quoted) {
      if (char === '"' && input[i + 1] === '"') { value += '"'; i++ }
      else if (char === '"') { quoted = false; closed = true }
      else value += char
    } else if (char === ',' || char === '，' || char === '\n' || char === '\r') {
      flush()
    } else if (char === '"' && !value.trim() && !closed) {
      value = ''
      quoted = true
    } else {
      if (char === '"' || (closed && char.trim())) throw new Error('CSV 引号格式错误，请用双引号包裹含逗号文件名')
      value += char
    }
  }
  if (quoted) throw new Error('文件名的 CSV 双引号未闭合')
  flush()
  if (names.length > 100) throw new Error('最多查询 100 个文件名')
  return names
}

export function normalizeAnnotationFilenames(input: string): string {
  return parseAnnotationFilenames(input).map(name => `"${name.replace(/"/g, '""')}"`).join(',')
}

export function containedRect(containerWidth: number, containerHeight: number, width: number, height: number) {
  if (![containerWidth, containerHeight, width, height].every(n => Number.isFinite(n) && n > 0)) {
    return { left: 0, top: 0, width: 0, height: 0 }
  }
  const scale = Math.min(containerWidth / width, containerHeight / height)
  const displayWidth = Math.min(containerWidth, width * scale)
  const displayHeight = Math.min(containerHeight, height * scale)
  return {
    left: (containerWidth - displayWidth) / 2,
    top: (containerHeight - displayHeight) / 2,
    width: displayWidth, height: displayHeight,
  }
}

export function annotationCategoryColor(category: string): string {
  let hash = 0
  for (const char of category) hash = (Math.imul(hash, 31) + char.codePointAt(0)!) | 0
  return `hsl(${(hash >>> 0) % 360}, 82%, 58%)`
}

// Timestamps are actual presentation times, never frame_index / FPS.
export function annotationFrameWindowMs(timestamps: number[], index: number): number {
  const timestamp = timestamps[index]
  if (!Number.isFinite(timestamp)) return 0
  const before = index > 0 ? timestamp - timestamps[index - 1] : Infinity
  const after = index + 1 < timestamps.length ? timestamps[index + 1] - timestamp : Infinity
  return Math.max(0, Math.min(250, before / 2, after / 2))
}

export function matchingAnnotationFrame(frames: AnnotationFrame[], timeMs: number): AnnotationFrame | null {
  const timed = frames.filter(f => f.timestamp_ms !== null).sort((a, b) => a.timestamp_ms! - b.timestamp_ms!)
  let nearest = -1
  for (let i = 0; i < timed.length; i++) {
    if (nearest < 0 || Math.abs(timed[i].timestamp_ms! - timeMs) < Math.abs(timed[nearest].timestamp_ms! - timeMs)) nearest = i
  }
  if (nearest < 0 || !Number.isFinite(timeMs)) return null
  const frame = timed[nearest]
  const window = annotationFrameWindowMs(timed.map(f => f.timestamp_ms!), nearest)
  return Math.abs(frame.timestamp_ms! - timeMs) <= window ? frame : null
}

export async function collectAnnotationFrames(
  fetchPage: (page: number, size: number) => Promise<AnnotationFramesResponse>,
  signal?: AbortSignal,
): Promise<AnnotationFrame[]> {
  const frames: AnnotationFrame[] = []
  for (let page = 1; ; page++) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const data = await fetchPage(page, 100)
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    frames.push(...data.results)
    if (frames.length >= data.total) return frames
    if (!data.results.length) throw new Error('帧分页不完整，请刷新重试')
  }
}

export function ownsAnnotationMedia(media: AnnotationMediaItem, userId?: string | null, ownerScoped = false): boolean {
  // Non-admin search responses omit user_id but are owner-scoped by the server.
  return !!userId && (media.user_id === userId || (ownerScoped && media.user_id === null))
}

function scopeKey(userId: string, id: string) {
  return `annotation-scope:${userId}:${id}`
}

export function saveAnnotationScope(userId: string, snapshot: AnnotationResultSetResponse) {
  try { sessionStorage.setItem(scopeKey(userId, snapshot.result_set_id), JSON.stringify(snapshot)) } catch { /* Storage may be disabled. The URL still preserves scope. */ }
}

export function readAnnotationScope(userId: string, id: string): AnnotationResultSetResponse | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(scopeKey(userId, id)) || 'null')
    if (value?.result_set_id !== id || !Array.isArray(value.source?.tags)
      || !value.source.tags.every((tag: Record<string, unknown>) =>
        ['default', 'custom'].includes(String(tag.source)) && typeof tag.category === 'string' && typeof tag.name === 'string')
      || !Number.isFinite(Date.parse(value.expires_at)) || typeof value.total !== 'number') return null
    return value
  } catch { return null }
}

export function isAnnotationScopeExpired(snapshot: AnnotationResultSetResponse | null, now = Date.now()): boolean {
  return !!snapshot && Date.parse(snapshot.expires_at) <= now
}

export function annotationHttpStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}
