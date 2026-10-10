<template>
  <div class="media-gallery">
    <div class="gallery-grid">
      <div
        v-for="(item, index) in pagedItems"
        :key="`${animKey}-${item.media_id || item.id || index}`"
        class="media-card stagger-item"
        :style="{ '--i': index }"
        @click="handleClick(item)"
      >
        <div class="media-preview">
          <div v-if="!getMediaUrl(item.preview_url) || failedImages.has(item.media_id || item.id || index)">预览不可用，请重新检索获取链接</div>
          <div v-else-if="item.file_type === 'image' && !loadedImages.has(item.media_id || item.id || index)" class="img-placeholder shimmer-bg"></div>
          <img
            v-if="item.file_type === 'image' && getMediaUrl(item.preview_url)"
            :src="getMediaUrl(item.preview_url)"
            :alt="item.file_name"
            loading="lazy"
            :class="{ 'img-loaded': loadedImages.has(item.media_id || item.id || index) }"
            @load="onImageLoad(item.media_id || item.id || index)"
            @error="failedImages.add(item.media_id || item.id || index)"
          />
          <video v-else-if="item.file_type === 'video' && getMediaUrl(item.preview_url)" :src="getMediaUrl(item.preview_url)" preload="metadata" class="img-loaded"
            @error="failedImages.add(item.media_id || item.id || index)" />
          <div class="media-type">{{ item.file_type === 'video' ? 'VIDEO' : 'IMAGE' }}</div>
          <div class="media-overlay">
            <EyeOutlined class="overlay-icon" />
          </div>
        </div>
        <div class="media-info">
          <div class="file-name">{{ item.file_name || item.filename }}</div>
          <div class="tags-row" v-if="item.tags?.length">
            <span v-for="tag in item.tags.slice(0, 2)" :key="tagKey(tag)" class="mini-tag">
              <span class="mini-tag-source" :class="`source-${tag.source}`">{{ sourceLabels[tag.source] }}</span>
              {{ tag.tag_name || tag.name }}
            </span>
            <span v-if="item.tags.length > 2" class="more-tags">+{{ item.tags.length - 2 }}</span>
          </div>
          <div class="similarity" v-if="showSimilarity && item.similarity != null">
            <div class="sim-bar">
              <div class="sim-fill" :style="{ width: `${(item.similarity || 0) * 100}%` }"></div>
            </div>
            <span class="sim-text">{{ ((item.similarity || 0) * 100).toFixed(1) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <div class="gallery-pagination" v-if="total > pageSize">
      <a-pagination
        v-model:current="currentPage"
        :total="total"
        :page-size="pageSize"
        simple
        @change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { EyeOutlined } from '@ant-design/icons-vue'
import { getMediaUrl } from '@/utils/media'
import type { MediaTag, TagSource } from '@/types'

type GalleryTag = MediaTag & { name?: string }

interface GalleryItem {
  id?: string | number
  media_id?: string
  preview_url?: string | null
  tos_url?: string
  filename?: string
  file_name?: string
  file_type: string
  file_size?: number
  vector_status?: string
  tag_status?: string
  created_at?: string
  similarity?: number
  tags?: GalleryTag[] | null
}

const props = withDefaults(defineProps<{
  items: GalleryItem[]
  showSimilarity?: boolean
  pageSize?: number
  columns?: number
  total?: number
  page?: number
}>(), {
  showSimilarity: false,
  pageSize: 12,
  columns: 4
})

const emit = defineEmits<{
  click: [item: any]
  pageChange: [page: number]
}>()

const localPage = ref(1)
const serverPagination = computed(() => props.total !== undefined)
const currentPage = computed({
  get: () => serverPagination.value ? (props.page ?? 1) : localPage.value,
  set: (page: number) => { if (!serverPagination.value) localPage.value = page },
})
const total = computed(() => props.total ?? props.items.length)
const pagedItems = computed(() => serverPagination.value
  ? props.items
  : props.items.slice((localPage.value - 1) * props.pageSize, localPage.value * props.pageSize))
const loadedImages = ref<Set<string | number>>(new Set())
const failedImages = ref<Set<string | number>>(new Set())
const animKey = ref(0)
const sourceLabels: Record<TagSource, string> = {
  default: '默认',
  custom: '自定义',
}

const tagKey = (tag: GalleryTag) =>
  tag.id ?? JSON.stringify([tag.source, tag.category, tag.tag_name])

const onImageLoad = (id: string | number) => {
  loadedImages.value.add(id)
}

watch(() => props.items, () => {
  localPage.value = 1
  loadedImages.value = new Set()
  failedImages.value = new Set()
  animKey.value++
})

const handleClick = (item: GalleryItem) => {
  emit('click', item)
}

const handlePageChange = (page: number) => {
  emit('pageChange', page)
}
</script>

<style scoped>
.media-gallery {
  height: 100%;
}

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.media-card {
  position: relative;
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
}

.media-card:hover {
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 0 0 3px var(--color-primary-ring), var(--shadow-md);
}

.media-card:hover .media-overlay {
  opacity: 1;
}

.media-preview {
  position: relative;
  aspect-ratio: 16/9;
  background: var(--gray-100);
  overflow: hidden;
}

.img-placeholder {
  position: absolute;
  inset: 0;
  z-index: 0;
  background: var(--gray-100);
}

.media-preview img,
.media-preview video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease, opacity 0.3s ease;
  opacity: 0;
  position: relative;
  z-index: 1;
}

.media-preview img.img-loaded,
.media-preview video.img-loaded {
  opacity: 1;
}

.media-card:hover .media-preview img,
.media-card:hover .media-preview video {
  transform: scale(1.03);
}

.media-type {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 1px;
  z-index: 2;
}

.media-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 2;
}

.overlay-icon {
  color: #fff;
  font-size: 22px;
  filter: drop-shadow(0 0 8px rgba(255, 255, 255, 0.3));
}

.media-info {
  padding: 10px 12px;
}

.file-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--gray-800);
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tags-row {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
}

.mini-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: var(--color-primary-bg);
  color: var(--color-primary);
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
}

.mini-tag-source {
  padding: 0 3px;
  border-radius: 3px;
  font-size: 8px;
}

.source-default {
  color: #1d4ed8;
  background: #dbeafe;
}

.source-custom {
  color: #7e22ce;
  background: #f3e8ff;
}

.more-tags {
  color: var(--gray-400);
  font-size: 10px;
}

.similarity {
  display: flex;
  align-items: center;
  gap: 8px;
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

.sim-text {
  font-family: var(--font-mono);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 700;
  min-width: 38px;
  text-align: right;
  background: var(--color-primary-bg);
  padding: 2px 6px;
  border-radius: 4px;
}

.media-card:active {
  transform: translateY(-1px) scale(0.98);
  transition-duration: 0.1s;
}

.gallery-pagination {
  margin-top: 20px;
  text-align: center;
}
</style>
