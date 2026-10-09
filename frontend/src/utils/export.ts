import * as XLSX from 'xlsx'
import type { SearchResultItem, TagSource } from '../types'

const sourceLabels: Record<TagSource, string> = {
  default: '默认',
  custom: '自定义',
}

/** TOS keys contain literal %, # and ?; URL parsing would alter their meaning. */
export function parseTosUrl(tosUrl: string): { bucket: string; directory: string } {
  if (!tosUrl.startsWith('tos://')) return { bucket: '', directory: '' }
  const path = tosUrl.slice(6)
  const slash = path.indexOf('/')
  if (slash < 1) return { bucket: '', directory: '' }
  const key = path.slice(slash + 1)
  return { bucket: path.slice(0, slash), directory: key.slice(0, Math.max(0, key.lastIndexOf('/'))) }
}

export function buildExportRows(results: SearchResultItem[]) {
  return results.map(item => {
    const { bucket, directory } = parseTosUrl(item.tos_url)
    return {
      '文件名': item.file_name,
      tos_url: item.tos_url,
      '存储桶': bucket,
      '目录': directory,
      '标签': item.tags?.map(t => `[${sourceLabels[t.source]}]${t.category}:${t.tag_name}`).join(', ') ?? '',
      '文件类型': item.file_type,
      '相似度': item.similarity != null ? `${(item.similarity * 100).toFixed(1)}%` : '',
    }
  })
}
/**
 * 将搜索结果导出为 Excel 文件
 * searchType: 'image' | 'text' | 'tag'，用于文件名区分
 */
export function exportSearchResultsToExcel(results: SearchResultItem[], searchType: string): void {
  const data = buildExportRows(results)

  const wb = XLSX.utils.book_new()
  const ws = XLSX.utils.json_to_sheet(data)
  ws['!cols'] = [
    { wch: 60 },
    { wch: 30 },
    { wch: 20 },
    { wch: 30 },
    { wch: 40 },
    { wch: 12 },
    { wch: 10 },
  ]
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1')

  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  const filename = `检索结果_${searchType}_${timestamp}.xlsx`

  XLSX.writeFile(wb, filename)
}
