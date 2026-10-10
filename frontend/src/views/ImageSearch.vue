<template>
  <div class="image-search-page">
    <PageHeader eyebrow="多模态工作台 / 图像检索" title="图像检索" subtitle="上传参考图像，检索视觉相似的数据场景" />
    <ModelCatalogStatus />
    <a-alert v-if="searchError" type="error" :message="searchError" show-icon />

    <a-row :gutter="20">
      <!-- 左侧: 上传区域 -->
      <a-col :span="8">
        <GlassCard class="upload-section">
          <template #header>
            <div class="section-title">
              <PictureOutlined class="title-icon" />
              <span>上传图片</span>
            </div>
          </template>

          <a-upload-dragger
            v-model:fileList="fileList"
            :multiple="false"
            :max-count="1"
            :before-upload="beforeUpload"
            accept="image/*"
            class="upload-dragger"
          >
            <div class="upload-content">
              <div class="upload-icon-wrap">
                <CloudUploadOutlined class="upload-icon" />
              </div>
              <p class="upload-text">点击或拖拽图片到此区域</p>
              <p class="upload-hint">支持 JPG, PNG, WEBP 格式</p>
            </div>
          </a-upload-dragger>

          <!-- 参数设置 -->
          <div class="params-section">
            <div class="param-item">
              <label>相似度阈值</label>
              <div class="param-control">
                <a-slider v-model:value="threshold" :min="0" :max="1" :step="0.05" />
                <span class="param-value">{{ (threshold * 100).toFixed(0) }}%</span>
              </div>
            </div>
            <div class="param-item">
              <label>返回数量</label>
              <a-input-number v-model:value="topK" :min="1" :max="100" style="width: 100%" />
            </div>
          </div>

          <a-button
            type="primary"
            size="large"
            block
            :loading="searching"
            :disabled="fileList.length === 0 || !system.catalogReady"
            @click="doSearch"
            class="search-btn"
          >
            <SearchOutlined />
            搜索相似内容
          </a-button>
        </GlassCard>
      </a-col>

      <!-- 右侧: 搜索结果 -->
      <a-col :span="16">
        <GlassCard class="results-section">
          <template #header>
            <div class="results-header">
              <div class="results-title-wrap">
                <span class="results-title">搜索结果</span>
                <span class="results-count" v-if="results.length && !searching">{{ results.length }}</span>
              </div>
              <div class="results-actions">
                <span class="search-time" v-if="searchTime > 0 && !searching">{{ searchTime }}ms</span>
                <a-button
                  v-if="results.length > 0 && !searching"
                  type="text"
                  size="small"
                  class="export-btn"
                  @click="handleExport"
                >
                  <DownloadOutlined />
                  导出Excel
                </a-button>
              </div>
            </div>
          </template>

          <!-- 搜索中：骨架屏 -->
          <SkeletonGrid v-if="searching" :columns="3" :count="6" />

          <!-- 有结果 -->
          <div v-else-if="results.length > 0" class="fade-in-up">
            <MediaGallery
              :items="results"
              :show-similarity="true"
              :columns="3"
              @click="showDetail"
            />
          </div>

          <!-- 无结果 -->
          <EmptyState
            v-else
            title="上传图片开始搜索"
            description="支持 JPG, PNG, WEBP 格式"
            :icon="PictureOutlined"
          />
        </GlassCard>
      </a-col>
    </a-row>

    <MediaDetailModal v-model:open="detailVisible" :item="selectedMedia" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message, Upload } from 'ant-design-vue'
import type { UploadProps } from 'ant-design-vue'
import { PictureOutlined, CloudUploadOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons-vue'
import { searchByImage } from '@/api/search'
import { exportSearchResultsToExcel } from '@/utils/export'
import { useSearchStore } from '@/stores/search'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import GlassCard from '@/components/common/GlassCard/GlassCard.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import SkeletonGrid from '@/components/common/SkeletonGrid/SkeletonGrid.vue'
import MediaGallery from '@/components/features/search/MediaGallery.vue'
import MediaDetailModal from '@/components/features/search/MediaDetailModal.vue'
import type { SearchResultItem } from '@/types'
import { useSystemStore } from '@/stores/system'
import ModelCatalogStatus from '@/components/common/ModelCatalogStatus.vue'
const system = useSystemStore()
const searchError = ref('')

interface FileItem {
  uid: string
  name: string
  status?: string
  response?: any
  url?: string
  type?: string
  originFileObj?: File
}

const searchStore = useSearchStore()

const fileList = ref<FileItem[]>([])
const threshold = ref<number>(0.7)
const topK = ref<number>(20)
const searching = ref<boolean>(false)
const results = ref<SearchResultItem[]>([])
const searchTime = ref<number>(0)

const detailVisible = ref<boolean>(false)
const selectedMedia = ref<SearchResultItem | null>(null)

const beforeUpload: UploadProps['beforeUpload'] = (file) => {
  const isImage = file.type.startsWith('image/')
  if (!isImage) {
    message.error('只能上传图片文件!')
    return Upload.LIST_IGNORE
  }
  return false
}

const doSearch = async () => {
  if (!system.catalogReady || searching.value) return
  if (fileList.value.length === 0) {
    message.warning('请先上传图片')
    return
  }
  searching.value = true
  searchError.value = ''
  results.value = []
  searchStore.setSearching(true)
  const startTime = Date.now()
  try {
    const formData = new FormData()
    const file = fileList.value[0]
    formData.append('image', file.originFileObj || file as unknown as File)
    formData.append('threshold', String(threshold.value))
    formData.append('top_k', String(topK.value))
    const res = await searchByImage(formData)
    results.value = res.data.results
    searchTime.value = Date.now() - startTime

    searchStore.addToHistory({
      type: 'image',
      query: file.name
    })

    message.success(`搜索完成，找到 ${results.value.length} 个结果`)
  } catch (e) {
    searchError.value = '图片检索失败，请检查服务状态后重试'
  } finally {
    searching.value = false
    searchStore.setSearching(false)
  }
}

const handleExport = () => {
  exportSearchResultsToExcel(results.value, 'image')
}

const showDetail = (item: SearchResultItem) => {
  selectedMedia.value = item
  detailVisible.value = true
}
</script>

<style scoped>
.image-search-page {
  padding: 0;
}

.upload-section {
  min-height: calc(100vh - 180px);
}

.results-section {
  min-height: calc(100vh - 180px);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
}

.title-icon {
  color: var(--mint-deep);
}

.upload-dragger {
  position: relative;
  border-radius: var(--radius-lg) !important;
  border: none !important;
  background: transparent !important;
  transition: all 0.2s ease !important;
  overflow: hidden;
}

.upload-dragger :deep(.ant-upload-drag) {
  border: 1px dashed var(--gray-300) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--gray-50) !important;
  transition: border-color var(--transition-default), background var(--duration-normal) var(--ease-default) !important;
}

.upload-dragger :deep(.ant-upload-drag:hover) {
  border-color: var(--ink) !important;
  background: var(--white) !important;
}

.upload-dragger :deep(.ant-upload-drag.ant-upload-drag-hover) {
  border-color: var(--color-primary) !important;
  border-style: solid !important;
  background: var(--color-primary-bg) !important;
}

.upload-dragger :deep(.ant-upload),
.upload-dragger :deep(.ant-upload-btn) {
  border: none !important;
  outline: none !important;
  background: transparent !important;
}

.upload-dragger :deep(.ant-upload-drag-container) {
  outline: none !important;
}

.upload-content {
  padding: 32px 20px;
  text-align: center;
}

.upload-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  background: var(--white);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-mark-lg);
  margin-bottom: 14px;
  box-shadow: var(--shadow);
  transition: background var(--transition-default), transform var(--duration-slow) var(--ease-spring), border-color var(--transition-default);
}

.upload-dragger:hover .upload-icon-wrap {
  background: var(--mint-soft);
  border-color: transparent;
  transform: translateY(-3px) rotate(-4deg);
}

.upload-icon {
  font-size: 22px;
  color: var(--mint-deep);
}

.upload-text {
  color: var(--gray-700);
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
}

.upload-hint {
  color: var(--gray-400);
  font-size: 11px;
}

.upload-dragger :deep(.ant-upload-list) {
  margin-top: 12px;
}

.upload-dragger :deep(.ant-upload-list-item) {
  background: var(--gray-50) !important;
  border: 1px solid var(--gray-200) !important;
  border-radius: var(--radius) !important;
}

.params-section {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--gray-100);
}

.param-item {
  margin-bottom: 16px;
}

.param-item label {
  display: block;
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
  margin-bottom: 10px;
}

.param-control {
  display: flex;
  align-items: center;
  gap: 12px;
}

.param-control .ant-slider {
  flex: 1;
}

.param-value {
  font-family: var(--font-mono);
  color: var(--gray-900);
  font-weight: 500;
  font-size: 13px;
  min-width: 40px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.search-btn {
  margin-top: 8px;
  height: 44px;
  font-weight: 600;
  border-radius: var(--radius-sm);
}

.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.results-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.results-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
}

.results-count {
  background: var(--ink);
  color: var(--mint);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}

.search-time {
  font-family: var(--font-mono);
  color: var(--gray-400);
  font-size: 12px;
  font-weight: 500;
}

.results-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.export-btn {
  font-size: 12px;
  color: var(--gray-500);
}

.export-btn:hover {
  color: var(--color-accent);
}
</style>
