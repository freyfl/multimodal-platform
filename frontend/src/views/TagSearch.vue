<template>
  <div class="tag-search-page">
    <PageHeader eyebrow="MULTIMODAL / TAG SEARCH" title="标签检索" subtitle="通过场景标签快速定位目标数据集" />
    <a-alert v-if="searchError" type="error" :message="searchError" show-icon />

    <!-- 标签选择卡片 -->
    <div class="search-card">
      <div class="search-card-header">
        <div class="card-title">
          <TagsOutlined class="card-title-icon" />
          <span>场景标签</span>
        </div>
        <div class="catalog-actions">
          <span class="selected-badge" v-if="selectedTags.length > 0">已选 {{ selectedTags.length }} 个</span>
          <a-button type="text" size="small" :loading="catalogLoading" @click="fetchTagSystem">
            <ReloadOutlined />
            刷新
          </a-button>
        </div>
      </div>
      <div class="search-card-body">
        <!-- 按来源、分类分组展示 -->
        <div class="source-groups">
          <section v-for="section in catalogSections" :key="section.source" class="source-group">
            <div class="source-header">
              <span class="source-badge" :class="`source-${section.source}`">{{ section.label }}</span>
              <span class="source-count">{{ section.tags.length }} 个标签</span>
            </div>
            <div v-if="section.categories.length > 0" class="tags-grouped">
              <div
                v-for="category in section.categories"
                :key="category.name"
                class="tag-category-group"
              >
                <div class="category-label">{{ category.name }}</div>
                <div class="category-tags">
                  <button
                    v-for="tag in category.tags"
                    :key="tag.id"
                    class="tag-chip"
                    :class="{ active: selectedTagIds.includes(tag.id) }"
                    :aria-pressed="selectedTagIds.includes(tag.id)"
                    @click="toggleTag(tag)"
                  >
                    {{ tag.name }}
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="tags-empty">
              {{ section.source === 'custom' ? '暂无自定义标签' : '暂无默认标签' }}
            </div>
          </section>
        </div>

        <!-- 已选标签区 -->
        <div class="selected-section" v-if="selectedTags.length > 0">
          <span class="selected-label">已选标签：</span>
          <button
            v-for="tag in selectedTags"
            :key="tag.id"
            class="tag-chip active"
            :aria-label="`移除标签 ${tag.name}`"
            @click="removeTag(tag)"
          >
            <span class="selected-source">{{ sourceLabels[tag.source] }}</span>
            {{ tag.name }}
            <CloseOutlined class="tag-remove" />
          </button>

          <!-- AND/OR 切换 -->
          <a-radio-group v-model:value="searchLogic" size="small" class="logic-toggle">
            <a-radio-button value="AND">AND</a-radio-button>
            <a-radio-button value="OR">OR</a-radio-button>
          </a-radio-group>

          <span class="selected-spacer"></span>

          <a-button size="small" type="text" class="clear-btn" @click="clearTags">清除全部</a-button>
        </div>

        <!-- 检索按钮 -->
        <div class="search-action" v-if="selectedTags.length > 0">
          <a-button type="primary" @click="doSearch" :loading="searching" class="search-btn">
            开始检索
          </a-button>
        </div>
      </div>
    </div>

    <!-- 检索结果卡片 -->
    <div class="search-card">
      <div class="search-card-header">
        <div class="card-title">
          <span>检索结果</span>
          <span class="results-count" v-if="total > 0 && !searching">({{ total }})</span>
        </div>
        <div class="results-actions">
          <a-button v-if="submittedQuery && total > 0" data-testid="tag-all-annotations" :loading="transferring"
            :disabled="searching" @click="viewAllAnnotations">
            查看标注（全部匹配结果）
          </a-button>
          <a-button
            v-if="results.length > 0 && !searching"
            type="text"
            size="small"
            class="export-btn"
            @click="handleExport"
          >
            <DownloadOutlined />
            导出当前页 Excel
          </a-button>
          <div class="view-toggle">
            <button
              class="view-icon"
              :class="{ active: viewMode === 'grid' }"
              aria-label="网格视图"
              :aria-pressed="viewMode === 'grid'"
              @click="viewMode = 'grid'"
            ><AppstoreOutlined /></button>
            <button
              class="view-icon"
              :class="{ active: viewMode === 'list' }"
              aria-label="列表视图"
              :aria-pressed="viewMode === 'list'"
              @click="viewMode = 'list'"
            ><UnorderedListOutlined /></button>
          </div>
        </div>
      </div>
      <div class="search-card-body">
        <!-- 搜索中：骨架屏 -->
        <SkeletonGrid v-if="searching" :columns="4" :count="8" />

        <!-- 有结果 -->
        <div v-else-if="results.length > 0" class="fade-in-up">
          <MediaGallery
            :items="results"
            :columns="4"
            :total="total"
            :page="currentPage"
            :page-size="pageSize"
            @page-change="fetchPage"
            @click="showDetail"
          />
        </div>

        <!-- 无结果 -->
        <EmptyState
          v-else
          title="暂无结果"
          description="请添加筛选条件后搜索"
          :icon="TagsOutlined"
        />
      </div>
    </div>

    <MediaDetailModal v-model:open="detailVisible" :item="selectedMedia" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { message } from 'ant-design-vue'
import { TagsOutlined, CloseOutlined, AppstoreOutlined, UnorderedListOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { getTagSystem } from '@/api/tags'
import { searchByTags } from '@/api/search'
import { exportSearchResultsToExcel } from '@/utils/export'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import SkeletonGrid from '@/components/common/SkeletonGrid/SkeletonGrid.vue'
import MediaGallery from '@/components/features/search/MediaGallery.vue'
import MediaDetailModal from '@/components/features/search/MediaDetailModal.vue'
import type { SearchResultItem, TagIdentity, TagSource, TagSystemResponse, TagSearchRequest } from '@/types'

interface CatalogTag extends TagIdentity {
  id: string
}

type SelectedTag = CatalogTag

const sourceLabels: Record<TagSource, string> = {
  default: '默认标签',
  custom: '自定义标签',
}
const sourceOrder: TagSource[] = ['default', 'custom']
const tagSystem = ref<TagSystemResponse>({ default: [], custom: [], default_prompt: '' })
const viewMode = ref<'grid' | 'list'>('grid')

const tagIdentity = (tag: TagIdentity): string =>
  JSON.stringify([tag.source, tag.category, tag.name])

const allTags = computed<CatalogTag[]>(() =>
  sourceOrder.flatMap(source =>
    (tagSystem.value[source] ?? []).map(tag => ({ ...tag, id: tagIdentity(tag) })),
  ),
)

const catalogSections = computed(() => sourceOrder.map(source => {
  const tags = allTags.value.filter(tag => tag.source === source)
  const categories = new Map<string, CatalogTag[]>()
  for (const tag of tags) {
    const categoryTags = categories.get(tag.category) ?? []
    categoryTags.push(tag)
    categories.set(tag.category, categoryTags)
  }
  return {
    source,
    label: sourceLabels[source],
    tags,
    categories: Array.from(categories, ([name, categoryTags]) => ({
      name,
      tags: categoryTags,
    })),
  }
}))

const selectedTagIds = ref<string[]>([])
const selectedTags = computed<SelectedTag[]>(() => {
  return allTags.value
    .filter(t => selectedTagIds.value.includes(t.id))
})
const searchLogic = ref<'AND' | 'OR'>('AND')

const catalogLoading = ref(false)
const searching = ref<boolean>(false)
const searchError = ref('')
const results = ref<SearchResultItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 12
const submittedQuery = ref<TagSearchRequest | null>(null)
let searchVersion = 0
const transferring = ref(false)
let transferController: AbortController | null = null

const detailVisible = ref<boolean>(false)
const selectedMedia = ref<SearchResultItem | null>(null)

const fetchTagSystem = async () => {
  catalogLoading.value = true
  try {
    const res = await getTagSystem()
    if (res?.data) {
      tagSystem.value = {
        default: res.data.default ?? [],
        custom: res.data.custom ?? [],
        default_prompt: res.data.default_prompt ?? '',
      }
      const validIds = new Set(allTags.value.map(tag => tag.id))
      selectedTagIds.value = selectedTagIds.value.filter(id => validIds.has(id))
    }
  } catch (e) {
    console.error('Failed to fetch tag system:', e)
    message.error('标签目录刷新失败')
  } finally {
    catalogLoading.value = false
  }
}

const toggleTag = (tag: CatalogTag) => {
  const index = selectedTagIds.value.indexOf(tag.id)
  if (index > -1) {
    selectedTagIds.value.splice(index, 1)
  } else {
    selectedTagIds.value.push(tag.id)
  }
}

const removeTag = (tag: SelectedTag) => {
  const index = selectedTagIds.value.indexOf(tag.id)
  if (index > -1) {
    selectedTagIds.value.splice(index, 1)
  }
}

const clearTags = () => {
  searchVersion++
  transferController?.abort()
  selectedTagIds.value = []
  results.value = []
  total.value = 0
  currentPage.value = 1
  submittedQuery.value = null
  searching.value = false
  searchError.value = ''
}

const fetchPage = async (page: number) => {
  if (!submittedQuery.value) return
  const version = ++searchVersion
  searching.value = true
  searchError.value = ''
  try {
    const res = await searchByTags({
      ...submittedQuery.value,
      page,
      size: pageSize,
    })
    if (version !== searchVersion) return
    results.value = res.data.results
    total.value = res.data.total
    currentPage.value = res.data.page ?? page
    // A deletion between pages can move the last result to the previous page.
    const lastPage = Math.max(1, Math.ceil(total.value / pageSize))
    if (page > lastPage) await fetchPage(lastPage)
  } catch {
    if (version !== searchVersion) return
    results.value = []
    total.value = 0
    currentPage.value = 1
    searchError.value = '标签检索失败，请检查服务状态后重试'
  } finally {
    if (version === searchVersion) searching.value = false
  }
}

const doSearch = async () => {
  if (selectedTags.value.length === 0) {
    message.warning('请至少选择一个标签')
    return
  }
  submittedQuery.value = {
    tags: selectedTags.value.map(({ source, category, name }) => ({ source, category, name })),
    logic: searchLogic.value,
  }
  await fetchPage(1)
}

const handleExport = () => {
  exportSearchResultsToExcel(results.value, 'tag')
}

const viewAllAnnotations = async () => {
  if (!submittedQuery.value || searching.value || transferring.value) return
  const version = searchVersion
  const query = {
    tags: submittedQuery.value.tags.map(({ source, category, name }) => ({ source, category, name })),
    logic: submittedQuery.value.logic,
  }
  transferring.value = true
  transferController = new AbortController()
  const signal = transferController.signal
  try {
    const [{ createAnnotationResultSet }, { saveAnnotationScope }, { useAuthStore }, { default: router }] = await Promise.all([
      import('@/api/annotations'), import('@/utils/annotations'), import('@/stores/auth'), import('@/router'),
    ])
    if (signal.aborted) return
    const response = await createAnnotationResultSet(query, signal)
    if (version !== searchVersion) return
    const userId = useAuthStore().user?.id
    if (userId) saveAnnotationScope(userId, response.data)
    await router.push({ path: '/search/annotations', query: { scope: response.data.result_set_id } })
  } catch {
    if (!signal.aborted) message.error('全部结果转入失败；结果集最多 10000 条，请检查权限或缩小查询范围后重试')
  } finally {
    transferring.value = false
  }
}

const showDetail = (item: SearchResultItem) => {
  selectedMedia.value = item
  detailVisible.value = true
}

onMounted(() => {
  fetchTagSystem()
})
onBeforeUnmount(() => {
  searchVersion++
  transferController?.abort()
})
</script>

<style scoped>
.tag-search-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 卡片通用 */
.search-card {
  background: #fff;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow);
}

.search-card-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--color-border-subtle);
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.search-card-body {
  padding: 24px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900, #1a1a2e);
}

.card-title-icon {
  color: var(--mint-deep);
  font-size: 15px;
}

.selected-badge {
  font: 500 11px var(--font-mono);
  color: var(--mint);
  background: var(--ink);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  line-height: 18px;
}

.catalog-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.results-count {
  font-weight: 400;
  color: var(--gray-500, #64748b);
  margin-left: 4px;
}

/* 来源与分类分组 */
.source-groups {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.source-group + .source-group {
  padding-top: 18px;
  border-top: 1px dashed var(--gray-200);
}

.source-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.source-badge,
.selected-source {
  border-radius: var(--radius-xs);
  padding: 2px 7px;
  font: 500 10px var(--font-mono);
  letter-spacing: 0.08em;
}

.source-default {
  color: var(--mint-ink);
  background: var(--mint-soft);
}

.source-custom {
  color: var(--color-purple);
  background: var(--color-purple-light);
}

.source-count {
  color: var(--gray-400, #94a3b8);
  font-size: 11px;
}

.tags-grouped {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tag-category-group {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 10px;
}

.category-label {
  font: 500 10px var(--font-mono);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--gray-400);
  min-width: 88px;
  padding-top: 8px;
  flex-shrink: 0;
}

.category-tags {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 6px;
}

.tags-empty {
  color: var(--gray-400, #94a3b8);
  font-size: 13px;
  padding: 4px 0;
}

/* 标签 chip */
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 11px;
  max-width: 100%;
  overflow-wrap: anywhere;
  text-align: left;
  border-radius: var(--radius-pill);
  font-size: 12px;
  border: 1px solid var(--gray-200);
  background: #fff;
  color: var(--gray-600);
  cursor: pointer;
  transition:
    border-color var(--transition-default),
    background-color var(--transition-default),
    color var(--transition-default),
    transform var(--duration-normal) var(--ease-spring),
    box-shadow var(--duration-normal) var(--ease-default);
  user-select: none;
}

.tag-chip:hover {
  border-color: var(--ink);
  color: var(--ink);
  transform: translateY(-1px);
  box-shadow: var(--shadow);
}
.tag-chip:active { transform: translateY(0) scale(.96); }

.tag-chip.active {
  border-color: var(--ink);
  background: var(--ink);
  color: var(--mint);
}

.selected-source {
  color: currentColor;
  background: rgba(196, 236, 207, 0.16);
}

.tag-remove {
  font-size: 10px;
  margin-left: 2px;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.15s;
}

.tag-remove:hover {
  opacity: 1;
}

/* 已选区 */
.selected-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.selected-label {
  font-size: 12px;
  color: var(--gray-500, #64748b);
  font-weight: 500;
  white-space: nowrap;
}

.selected-spacer {
  flex: 1;
}

.logic-toggle {
  margin-left: 4px;
}

.logic-toggle :deep(.ant-radio-button-wrapper) {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  height: 26px;
  line-height: 24px;
  padding: 0 8px;
}

.clear-btn {
  font-size: 12px;
  color: var(--gray-500, #64748b);
}

.clear-btn:hover {
  color: #ef4444;
}

/* 检索按钮 */
.search-action {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.search-btn {
  height: 36px;
  border-radius: 8px;
  padding: 0 28px;
  font-size: 13px;
  font-weight: 500;
}

/* 视图切换 */
.results-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.export-btn {
  font-size: 12px;
  color: var(--gray-500);
}

.export-btn:hover {
  color: var(--color-primary);
}

.view-toggle {
  display: flex;
  gap: 4px;
}

.view-icon {
  font-size: 16px;
  color: var(--gray-400, #94a3b8);
  cursor: pointer;
  padding: 8px;
  border-radius: 4px;
  transition: all 0.15s;
}

.view-icon:hover {
  color: var(--gray-600, #475569);
}

.view-icon.active {
  color: var(--color-primary, #0064ff);
  background: var(--color-primary-bg, #e8f0ff);
}

/* 结果网格覆盖为 4 列 */
.search-card-body :deep(.gallery-grid) {
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

/* 结果卡片圆角 */
.search-card-body :deep(.media-card) {
  border-radius: 10px;
}

@media (max-width: 1024px) {
  .search-card-body :deep(.gallery-grid) {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .search-card-body :deep(.gallery-grid) {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
