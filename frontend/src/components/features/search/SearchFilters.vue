<template>
  <div class="search-filters">
    <div class="filters-header">
      <FilterOutlined class="filter-icon" />
      <span>筛选条件</span>
      <a-button type="link" size="small" v-if="hasActiveFilters" @click="handleReset" class="reset-btn">
        重置
      </a-button>
    </div>

    <div class="filter-section">
      <div class="section-title">文件类型</div>
      <div class="filter-options">
        <div
          v-for="type in fileTypes"
          :key="type.value"
          class="filter-chip"
          :class="{ active: selectedTypes.includes(type.value) }"
          @click="toggleType(type.value)"
        >
          <component :is="type.icon" class="chip-icon" />
          <span>{{ type.label }}</span>
        </div>
      </div>
    </div>

    <div class="filter-section">
      <div class="section-title">相似度范围</div>
      <div class="similarity-slider">
        <a-slider
          v-model:value="similarityRange"
          range
          :min="0"
          :max="100"
          :tooltip-visible="true"
          :tip-formatter="(val: number) => `${val}%`"
        />
        <div class="range-labels">
          <span>{{ similarityRange[0] }}%</span>
          <span>{{ similarityRange[1] }}%</span>
        </div>
      </div>
    </div>

    <div class="filter-section">
      <div class="section-title">时间范围</div>
      <a-range-picker
        v-model:value="dateRange"
        :placeholder="['开始日期', '结束日期']"
        class="date-picker"
      />
    </div>

    <div class="filter-section" v-if="tags.length > 0">
      <div class="section-title">标签筛选</div>
      <div class="tags-grid">
        <a-tag
          v-for="tag in tags"
          :key="tag.id"
          :color="selectedTags.includes(tag.id) ? 'blue' : 'default'"
          class="tag-item"
          @click="toggleTag(tag.id)"
        >
          {{ tag.name }}
        </a-tag>
      </div>
    </div>

    <div class="filter-actions">
      <a-button block @click="handleApply" class="apply-btn">
        应用筛选
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { FilterOutlined, FileImageOutlined, VideoCameraOutlined, FileOutlined } from '@ant-design/icons-vue'
import type { Dayjs } from 'dayjs'

interface Tag {
  id: string
  name: string
  category?: string
}

interface FilterState {
  types: string[]
  similarityMin: number
  similarityMax: number
  dateStart?: string
  dateEnd?: string
  tags: string[]
}

withDefaults(defineProps<{
  tags?: Tag[]
}>(), {
  tags: () => []
})

const emit = defineEmits<{
  apply: [filters: FilterState]
  reset: []
}>()

const fileTypes = [
  { value: 'image', label: '图片', icon: FileImageOutlined },
  { value: 'video', label: '视频', icon: VideoCameraOutlined },
  { value: 'other', label: '其他', icon: FileOutlined }
]

const selectedTypes = ref<string[]>(['image', 'video'])
const similarityRange = ref<[number, number]>([50, 100])
const dateRange = ref<[Dayjs, Dayjs] | null>(null)
const selectedTags = ref<string[]>([])

const hasActiveFilters = computed(() => {
  return selectedTypes.value.length < 2 ||
    similarityRange.value[0] > 50 ||
    similarityRange.value[1] < 100 ||
    dateRange.value !== null ||
    selectedTags.value.length > 0
})

const toggleType = (type: string) => {
  const index = selectedTypes.value.indexOf(type)
  if (index > -1) {
    if (selectedTypes.value.length > 1) {
      selectedTypes.value.splice(index, 1)
    }
  } else {
    selectedTypes.value.push(type)
  }
}

const toggleTag = (tagId: string) => {
  const index = selectedTags.value.indexOf(tagId)
  if (index > -1) {
    selectedTags.value.splice(index, 1)
  } else {
    selectedTags.value.push(tagId)
  }
}

const handleApply = () => {
  const filters: FilterState = {
    types: [...selectedTypes.value],
    similarityMin: similarityRange.value[0] / 100,
    similarityMax: similarityRange.value[1] / 100,
    tags: [...selectedTags.value]
  }

  if (dateRange.value) {
    filters.dateStart = dateRange.value[0].format('YYYY-MM-DD')
    filters.dateEnd = dateRange.value[1].format('YYYY-MM-DD')
  }

  emit('apply', filters)
}

const handleReset = () => {
  selectedTypes.value = ['image', 'video']
  similarityRange.value = [50, 100]
  dateRange.value = null
  selectedTags.value = []
  emit('reset')
}
</script>

<style scoped>
.search-filters {
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.filters-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-900);
}

.filter-icon {
  color: var(--color-primary);
}

.reset-btn {
  margin-left: auto;
  color: var(--gray-500);
  padding: 0;
  height: auto;
}

.filter-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--gray-100);
}

.filter-section:last-of-type {
  border-bottom: none;
  margin-bottom: 0;
}

.section-title {
  color: var(--gray-500);
  font-size: 13px;
  margin-bottom: 12px;
  font-weight: 500;
}

.filter-options {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 20px;
  color: var(--gray-600);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.filter-chip.active {
  background: var(--color-primary-bg);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.chip-icon {
  font-size: 14px;
}

.similarity-slider {
  padding: 0 8px;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  color: var(--gray-500);
  font-size: 12px;
}

.date-picker {
  width: 100%;
}

.tags-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-item {
  background: var(--white);
  border: 1px solid var(--gray-200);
  color: var(--gray-600);
  padding: 4px 12px;
  border-radius: 16px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tag-item:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.filter-actions {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--gray-100);
}

.apply-btn {
  height: 42px;
  border-radius: var(--radius-sm);
  font-weight: 600;
  background: var(--color-primary);
  border-color: var(--color-primary);
}

.apply-btn:hover {
  background: var(--color-primary-dark);
}
</style>
