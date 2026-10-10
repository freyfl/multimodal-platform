<template>
  <a-modal
    :open="open"
    :title="null"
    width="720px"
    :footer="null"
    @update:open="$emit('update:open', $event)"
    class="detail-modal"
    :destroy-on-close="true"
  >
    <div v-if="item" class="detail-body scale-in">
      <div class="modal-title">
        <span class="title-text">{{ item.file_name || item.filename || '媒体详情' }}</span>
        <span class="type-badge">{{ item.file_type === 'video' ? 'VIDEO' : 'IMAGE' }}</span>
      </div>

      <!-- 媒体预览 -->
      <div class="preview-wrap">
        <a-alert v-if="!getMediaUrl(item.preview_url) || previewFailed" type="warning" message="预览不可用或链接已过期，请重新检索获取预览链接" />
        <div v-else-if="item.file_type === 'image' && !previewLoaded" class="preview-placeholder shimmer-bg"></div>
        <img
          v-if="item.file_type === 'image' && getMediaUrl(item.preview_url) && !previewFailed"
          :src="getMediaUrl(item.preview_url)"
          :alt="item.file_name"
          class="preview-media"
          :class="{ loaded: previewLoaded }"
          @load="previewLoaded = true"
          @error="previewFailed = true"
          @click="showFullscreen = true"
        />
        <video
          v-else-if="open && item.file_type === 'video' && getMediaUrl(item.preview_url) && !previewFailed"
          :src="getMediaUrl(item.preview_url)"
          @error="previewFailed = true"
          controls
          preload="metadata"
          class="preview-media loaded"
        />
      </div>
      <p class="media-source">TOS 来源：{{ item.tos_url }}</p>

      <!-- 相似度 -->
      <div v-if="item.similarity != null" class="sim-section">
        <span class="sim-label">相似度</span>
        <div class="sim-bar-wrap">
          <div class="sim-bar">
            <div class="sim-fill" :style="{ width: `${(item.similarity * 100).toFixed(0)}%` }" />
          </div>
          <span class="sim-value">{{ (item.similarity * 100).toFixed(1) }}%</span>
        </div>
      </div>

      <!-- 标签列表 -->
      <div v-if="groupedTags.length > 0" class="tags-section">
        <div class="tags-title">标签</div>
        <div v-for="group in groupedTags" :key="group.id" class="tag-group">
          <div class="tag-heading">
            <span class="tag-source" :class="`source-${group.source}`">{{ sourceLabels[group.source] }}</span>
            <span class="tag-category">{{ categoryNames[group.category] || group.category }}</span>
          </div>
          <div class="tag-list">
            <span v-for="tag in group.tags" :key="tagKey(tag)" class="tag-chip">
              {{ tag.tag_name || tag.name }}
              <span v-if="tag.confidence != null" class="tag-conf">{{ (tag.confidence * 100).toFixed(0) }}%</span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 全屏预览 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showFullscreen && item" class="fullscreen-overlay" @click="showFullscreen = false">
          <img :src="getMediaUrl(item.preview_url)" class="fullscreen-img" />
          <div class="fullscreen-hint">点击关闭</div>
        </div>
      </Transition>
    </Teleport>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getMediaUrl } from '@/utils/media'
import { categoryNames } from '@/constants/tags'
import type { TagSource } from '@/types'

interface TagItem {
  source: TagSource
  category?: string
  tag_name?: string
  name?: string
  confidence?: number
}

interface MediaItem {
  file_type: string
  file_name?: string
  filename?: string
  preview_url?: string | null
  tos_url?: string
  similarity?: number
  tags?: TagItem[] | null
}

const props = defineProps<{
  open: boolean
  item: MediaItem | null
}>()

defineEmits<{ 'update:open': [value: boolean] }>()

const previewLoaded = ref(false)
const previewFailed = ref(false)
const showFullscreen = ref(false)
const sourceLabels: Record<TagSource, string> = {
  default: '默认',
  custom: '自定义',
}

const tagKey = (tag: TagItem) =>
  JSON.stringify([tag.source, tag.category ?? '', tag.tag_name ?? tag.name ?? ''])

// 当 item 变化时重置
watch([() => props.item, () => props.open], () => {
  previewLoaded.value = false
  previewFailed.value = false
  showFullscreen.value = false
})

const groupedTags = computed(() => {
  const groups = new Map<string, {
    id: string
    source: TagSource
    category: string
    tags: TagItem[]
  }>()
  for (const tag of props.item?.tags ?? []) {
    const category = tag.category || 'other'
    const id = JSON.stringify([tag.source, category])
    const group = groups.get(id) ?? { id, source: tag.source, category, tags: [] }
    group.tags.push(tag)
    groups.set(id, group)
  }
  return Array.from(groups.values())
})
</script>

<style scoped>
.media-source { overflow-wrap: anywhere; color: var(--gray-500); font-size: 12px; }
.detail-body {
  padding: 0 0 8px;
}

.modal-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.title-text {
  font-size: 16px;
  font-weight: 700;
  color: var(--gray-900);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 12px;
}

.type-badge {
  font-size: 10px;
  font-weight: 600;
  color: var(--gray-500);
  background: var(--gray-100);
  border: 1px solid var(--gray-200);
  padding: 2px 10px;
  border-radius: 6px;
  letter-spacing: 1px;
  flex-shrink: 0;
}

.preview-wrap {
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--gray-100);
  margin-bottom: 16px;
  border: 1px solid var(--gray-200);
}

.preview-placeholder {
  aspect-ratio: 16 / 10;
  border-radius: var(--radius-lg);
  margin-bottom: 16px;
  background: var(--gray-100);
}

.preview-media {
  width: 100%;
  max-height: 380px;
  object-fit: contain;
  display: block;
  opacity: 0;
  transition: opacity 0.4s ease;
  cursor: zoom-in;
}

.preview-media.loaded {
  opacity: 1;
}

video.preview-media {
  max-height: none;
  object-fit: initial;
  height: auto;
  cursor: default;
}

.sim-section {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-md);
  margin-bottom: 12px;
}

.sim-label {
  color: var(--gray-500);
  font-size: 12px;
  min-width: 48px;
}

.sim-bar-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.sim-bar {
  flex: 1;
  height: 4px;
  background: var(--gray-100);
  border-radius: 2px;
  overflow: hidden;
}

.sim-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-primary-light));
  border-radius: 2px;
  transition: width 0.4s ease;
}

.sim-value {
  font-family: var(--font-mono);
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 700;
  min-width: 50px;
  text-align: right;
}

.tags-section {
  padding: 14px 16px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-md);
}

.tags-title {
  color: var(--gray-500);
  font-size: 12px;
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.tag-group {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}

.tag-group:last-child {
  margin-bottom: 0;
}

.tag-heading {
  min-width: 56px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
}

.tag-category {
  color: var(--gray-500);
  font-size: 11px;
}

.tag-source {
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 600;
}

.source-default {
  color: #1d4ed8;
  background: #dbeafe;
}

.source-custom {
  color: #7e22ce;
  background: #f3e8ff;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  color: var(--gray-700);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tag-chip:hover {
  background: var(--mint-soft);
  border-color: var(--color-primary);
  transform: translateY(-1px);
}

.tag-conf {
  font-family: var(--font-mono);
  color: var(--color-primary);
  font-size: 10px;
  opacity: 0.7;
}

/* Fullscreen preview overlay */
.fullscreen-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(15, 23, 42, 0.9);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  cursor: zoom-out;
}

.fullscreen-img {
  max-width: 90vw;
  max-height: 85vh;
  object-fit: contain;
  border-radius: 8px;
}

.fullscreen-hint {
  margin-top: 16px;
  color: var(--gray-400);
  font-size: 13px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
