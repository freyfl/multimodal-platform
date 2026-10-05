<template>
  <div class="search-bar">
    <div class="search-input-wrapper">
      <SearchOutlined class="search-icon" />
      <a-input
        v-model:value="searchText"
        :placeholder="placeholder"
        aria-label="描述要检索的图片或视频"
        size="large"
        class="search-input"
        @pressEnter="handleSearch"
        @input="handleInput"
      />
      <a-button
        type="primary"
        size="large"
        :loading="loading"
        :disabled="disabled || !searchText.trim()"
        class="search-btn"
        @click="handleSearch"
      >
        搜索
      </a-button>
    </div>

    <div class="search-options" v-if="showOptions">
      <div class="option-group">
        <span class="option-label">搜索模式</span>
        <a-radio-group v-model:value="searchMode" button-style="solid" class="mode-radio">
          <a-radio-button value="semantic">语义搜索</a-radio-button>
        </a-radio-group>
      </div>

      <div class="option-group">
        <span class="option-label">返回数量</span>
        <a-select v-model:value="topK" class="topk-select">
          <a-select-option :value="10">10条</a-select-option>
          <a-select-option :value="20">20条</a-select-option>
          <a-select-option :value="50">50条</a-select-option>
          <a-select-option :value="100">100条</a-select-option>
        </a-select>
      </div>
    </div>

    <div class="search-history" v-if="showHistory && history.length > 0">
      <div class="history-header">
        <HistoryOutlined class="history-icon" />
        <span>搜索历史</span>
        <a-button type="link" size="small" @click="handleClearHistory" class="clear-btn">
          清空
        </a-button>
      </div>
      <div class="history-tags">
        <button
          v-for="(item, index) in history.slice(0, 10)"
          :key="index"
          class="history-tag stagger-item"
          :style="{ '--i': index }"
          @click="handleHistoryClick(item)"
        >
          {{ item }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { SearchOutlined, HistoryOutlined } from '@ant-design/icons-vue'

const props = withDefaults(defineProps<{
  placeholder?: string
  loading?: boolean
  disabled?: boolean
  showOptions?: boolean
  showHistory?: boolean
  history?: string[]
  modelValue?: string
}>(), {
  placeholder: '输入描述搜索相关图片或视频...',
  loading: false,
  disabled: false,
  showOptions: true,
  showHistory: true,
  history: () => [],
  modelValue: ''
})

const emit = defineEmits<{
  search: [text: string, mode: string, topK: number]
  input: [text: string]
  'update:modelValue': [value: string]
  clearHistory: []
}>()

const searchText = ref(props.modelValue)
const searchMode = ref<string>('semantic')
const topK = ref<number>(20)

watch(() => props.modelValue, (val) => {
  searchText.value = val
})

const handleInput = () => {
  emit('input', searchText.value)
  emit('update:modelValue', searchText.value)
}

const handleSearch = () => {
  if (props.disabled || props.loading || !searchText.value.trim()) return
  emit('search', searchText.value.trim(), searchMode.value, topK.value)
}

const handleHistoryClick = (text: string) => {
  searchText.value = text
  emit('update:modelValue', text)
  handleSearch()
}

const handleClearHistory = () => {
  emit('clearHistory')
}
</script>

<style scoped>
.search-bar {
  width: 100%;
}

.search-input-wrapper {
  display: flex;
  align-items: center;
  position: relative;
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-md);
  padding: 5px;
  transition: all 0.15s ease;
}

.search-input-wrapper:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(0, 100, 255, 0.08);
}

.search-icon {
  padding: 0 14px;
  color: var(--gray-400);
  font-size: 14px;
}

.search-input {
  flex: 1;
  min-width: 0;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

.search-input :deep(.ant-input) {
  background: transparent !important;
  color: var(--gray-800) !important;
  font-size: 13px;
}

.search-input :deep(.ant-input::placeholder) {
  color: var(--gray-400);
}

.search-btn {
  border-radius: var(--radius-sm) !important;
  height: 38px !important;
  padding: 0 20px !important;
  font-weight: 500;
  font-size: 13px;
  background: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
  box-shadow: 0 1px 3px rgba(0, 100, 255, 0.3);
}

.search-btn:hover {
  background: var(--color-primary-dark) !important;
  box-shadow: 0 2px 8px rgba(0, 100, 255, 0.4);
  transform: translateY(-1px);
}

.search-options {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  margin-top: 14px;
  padding: 12px 16px;
  background: var(--gray-50);
  border-radius: var(--radius);
  border: 1px solid var(--gray-100);
}

.option-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.option-label {
  color: var(--gray-500);
  font-size: 12px;
}

.mode-radio :deep(.ant-radio-button-wrapper) {
  background: var(--white) !important;
  border-color: var(--gray-200) !important;
  color: var(--gray-600) !important;
  font-size: 12px;
}

.mode-radio :deep(.ant-radio-button-wrapper:first-child) {
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}

.mode-radio :deep(.ant-radio-button-wrapper:last-child) {
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.mode-radio :deep(.ant-radio-button-wrapper-checked) {
  background: var(--color-primary-bg) !important;
  border-color: var(--color-primary) !important;
  color: var(--color-primary) !important;
}

.topk-select {
  width: 90px;
}

.topk-select :deep(.ant-select-selector) {
  background: var(--white) !important;
  border-color: var(--gray-200) !important;
  border-radius: var(--radius-sm) !important;
  font-size: 12px;
}

.topk-select :deep(.ant-select-selection-item) {
  color: var(--gray-700) !important;
}

.search-history {
  margin-top: 14px;
  padding: 14px 16px;
  background: var(--gray-50);
  border-radius: var(--radius);
  border: 1px solid var(--gray-100);
}

.history-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--gray-500);
  font-size: 12px;
}

.history-icon {
  color: var(--color-primary);
  font-size: 13px;
}

.clear-btn {
  margin-left: auto;
  color: var(--gray-500);
  padding: 0;
  height: auto;
  font-size: 11px;
}

.history-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.history-tag {
  background: var(--white) !important;
  border: 1px solid var(--gray-200) !important;
  color: var(--gray-600) !important;
  padding: 4px 10px;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 12px;
}

.history-tag:hover {
  border-color: var(--color-primary) !important;
  color: var(--color-primary) !important;
  background: var(--color-primary-bg) !important;
}
@media (max-width: 600px) {
  .search-icon { padding: 0 8px; }
  .search-options { gap: 12px; padding: 12px; }
  .search-btn { padding: 0 14px !important; flex-shrink: 0; }
}
</style>
