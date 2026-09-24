import type { TagSource } from '@/types'

export const categoryNames: Record<string, string> = {
  vehicle: '车辆',
  pedestrian: '行人',
  sign: '标志',
  road: '道路',
  weather: '天气',
  traffic: '交通状态',
  interaction: '交互行为',
}

export const tagModeLabels: Record<TagSource, string> = {
  default: '默认标签',
  custom: '自定义标签',
}

export function getTagModeLabel(mode: unknown): string {
  return mode === 'custom' ? tagModeLabels.custom : tagModeLabels.default
}
