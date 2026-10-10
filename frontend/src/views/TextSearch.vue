<template>
  <div class="text-search-page">
    <PageHeader eyebrow="多模态工作台 / 文本检索" title="文本检索" subtitle="使用自然语言描述场景，语义匹配目标数据" />

    <!-- 搜索区域 -->
    <GlassCard class="search-section">
      <ModelCatalogStatus />
      <SearchBar
        v-model="searchQuery"
        :loading="searching"
        :disabled="!system.catalogReady"
        :show-history="true"
        :history="searchHistory"
        @search="doSearch"
        @clear-history="clearHistory"
      />
      <div v-if="!hasSearched" class="hot-searches">
        <span class="hot-label">快速示例：</span>
        <button
          v-for="(hot, index) in hotSearches"
          :key="hot"
          class="hot-tag stagger-item"
          :style="{ '--i': index }"
          @click="handleHotSearch(hot)"
        >{{ hot }}</button>
      </div>
    </GlassCard>

    <!-- 搜索结果 -->
    <GlassCard v-if="hasSearched" class="results-section">
      <a-alert v-if="searchError" type="error" :message="searchError" show-icon />
      <template #header>
        <div class="results-header">
          <div class="results-title-wrap">
            <span class="results-title">搜索结果</span>
            <span class="results-count" v-if="!searching">{{ results.length }}</span>
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
      <SkeletonGrid v-if="searching" :columns="4" :count="8" />

      <!-- 有结果 -->
      <div v-else-if="results.length > 0" class="fade-in-up">
        <MediaGallery
          :items="results"
          :show-similarity="true"
          :columns="4"
          @click="showDetail"
        />
      </div>

      <!-- 无结果 -->
      <EmptyState
        v-else
        title="没有找到相关内容"
        description="尝试使用不同的关键词或描述"
        :icon="SearchOutlined"
      />
    </GlassCard>

    <MediaDetailModal v-model:open="detailVisible" :item="selectedMedia" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { SearchOutlined, DownloadOutlined } from '@ant-design/icons-vue'
import GlassCard from '@/components/common/GlassCard/GlassCard.vue'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import { SearchBar, MediaGallery } from '@/components/features'
import SkeletonGrid from '@/components/common/SkeletonGrid/SkeletonGrid.vue'
import MediaDetailModal from '@/components/features/search/MediaDetailModal.vue'
import { searchByText } from '@/api/search'
import { exportSearchResultsToExcel } from '@/utils/export'
import { useSearchStore } from '@/stores/search'
import type { SearchResultItem } from '@/types'
import { useSystemStore } from '@/stores/system'
import ModelCatalogStatus from '@/components/common/ModelCatalogStatus.vue'
const system = useSystemStore()
const searchError = ref('')

const searchQuery = ref<string>('')
const searching = ref<boolean>(false)
const results = ref<SearchResultItem[]>([])
const searchTime = ref<number>(0)
const hasSearched = ref<boolean>(false)
const searchHistory = ref<string[]>([])
const searchStore = useSearchStore()
const detailVisible = ref<boolean>(false)
const selectedMedia = ref<SearchResultItem | null>(null)

const hotSearches = ref<string[]>([
  '夜间城区行人场景',
  '高速公路多车道变道',
  '雨天能见度低于50m',
  '交叉路口左转场景'
])

const doSearch = async (text: string, _mode?: string, topK?: number) => {
  if (!system.catalogReady || searching.value) return
  if (!text.trim()) {
    message.warning('请输入搜索内容')
    return
  }

  searching.value = true
  searchError.value = ''
  results.value = []
  hasSearched.value = true
  searchStore.setSearching(true)
  const start = Date.now()

  if (!searchHistory.value.includes(text)) {
    searchHistory.value.unshift(text)
    if (searchHistory.value.length > 10) {
      searchHistory.value.pop()
    }
  }

  try {
    const res = await searchByText({ query: text, top_k: topK || 20 })
    results.value = res.data.results
    searchTime.value = Date.now() - start
    searchStore.addToHistory({ type: 'text', query: text })
  } catch (e) {
    searchError.value = '文本检索失败，请检查服务状态后重试'
  } finally {
    searching.value = false
    searchStore.setSearching(false)
  }
}

const handleHotSearch = (text: string) => {
  searchQuery.value = text
  doSearch(text)
}

const clearHistory = () => {
  searchHistory.value = []
}

const handleExport = () => {
  exportSearchResultsToExcel(results.value, 'text')
}

const showDetail = (item: SearchResultItem) => {
  selectedMedia.value = item
  detailVisible.value = true
}
</script>

<style scoped>
.text-search-page {
  padding: 0;
}

.search-section {
  margin-bottom: 24px;
}

.results-section {
  min-height: 400px;
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
  font-weight: 500;
  line-height: 18px;
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

.hot-searches {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed var(--gray-200);
}

.hot-label {
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
  white-space: nowrap;
  margin-right: 6px;
}

.hot-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  color: var(--gray-700);
  padding: 5px 12px 5px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--transition-default), color var(--transition-default), transform var(--duration-normal) var(--ease-spring), box-shadow var(--duration-normal) var(--ease-default);
}
.hot-tag::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--gray-300);
  transition: background var(--transition-default), transform var(--duration-normal) var(--ease-spring);
}

.hot-tag:hover {
  border-color: var(--ink);
  color: var(--ink);
  transform: translateY(-1px);
  box-shadow: var(--shadow);
}
.hot-tag:hover::before { background: var(--mint-deep); transform: scale(1.4); }
.hot-tag:active { transform: translateY(0) scale(.97); }
</style>
