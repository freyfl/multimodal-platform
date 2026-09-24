/** Only use the backend's preview URL; never reconstruct a signed URL. */
export function getMediaUrl(previewUrl?: string | null): string {
  return previewUrl?.startsWith('https://') ? previewUrl : ''
}

/**
 * 格式化文件大小
 * @param bytes 字节数
 * @returns 格式化后的字符串
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'

  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${units[i]}`
}

/**
 * 格式化日期时间
 * @param dateStr 日期字符串
 * @returns 格式化后的本地时间字符串
 */
export function formatDateTime(dateStr: string): string {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

/**
 * 格式化相对时间
 * @param dateStr 日期字符串
 * @returns 相对时间描述
 */
export function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return ''

  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (days > 7) {
    return formatDateTime(dateStr)
  } else if (days > 0) {
    return `${days} 天前`
  } else if (hours > 0) {
    return `${hours} 小时前`
  } else if (minutes > 0) {
    return `${minutes} 分钟前`
  } else {
    return '刚刚'
  }
}

/**
 * 格式化相似度为百分比
 * @param similarity 相似度 (0-1)
 * @param decimals 小数位数
 * @returns 百分比字符串
 */
export function formatSimilarity(similarity: number, decimals: number = 1): string {
  return `${(similarity * 100).toFixed(decimals)}%`
}

/**
 * 获取文件扩展名
 * @param filename 文件名
 * @returns 扩展名（小写）
 */
export function getFileExtension(filename: string): string {
  if (!filename) return ''
  const lastDot = filename.lastIndexOf('.')
  return lastDot > 0 ? filename.slice(lastDot + 1).toLowerCase() : ''
}

/**
 * 判断是否为图片文件
 * @param filename 文件名或类型
 * @returns 是否为图片
 */
export function isImageFile(filename: string): boolean {
  const ext = getFileExtension(filename)
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']
  return imageExts.includes(ext)
}

/**
 * 判断是否为视频文件
 * @param filename 文件名或类型
 * @returns 是否为视频
 */
export function isVideoFile(filename: string): boolean {
  const ext = getFileExtension(filename)
  const videoExts = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm']
  return videoExts.includes(ext)
}
