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
  padding: 6px 6px 6px 0;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--transition-default), box-shadow var(--duration-normal) var(--ease-default), transform var(--duration-normal) var(--ease-out);
}
.search-input-wrapper:hover { border-color: var(--gray-400); }

.search-input-wrapper:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px var(--color-primary-ring), var(--shadow-md);
}

.search-icon {
  padding: 0 16px 0 18px;
  color: var(--gray-400);
  font-size: 15px;
  transition: color var(--transition-default);
}
.search-input-wrapper:focus-within .search-icon { color: var(--color-primary); }

.search-input {
  flex: 1;
  min-width: 0;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding-left: 0 !important;
}

.search-input :deep(.ant-input),
.search-input.ant-input {
  background: transparent !important;
  color: var(--gray-900) !important;
  font-size: 15px !important;
  height: 44px;
}

.search-input :deep(.ant-input::placeholder) {
  color: var(--gray-400);
}

.search-btn {
  border-radius: var(--radius) !important;
  height: 42px !important;
  padding: 0 22px !important;
  font-weight: 500;
  font-size: 14px;
}

.search-options {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  margin-top: 14px;
  padding: 0 4px;
}

.option-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.option-label {
  color: var(--gray-500);
  font: 500 10px var(--font-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.mode-radio :deep(.ant-radio-button-wrapper) {
  font-size: 12px;
  height: 30px;
  line-height: 28px;
}

.mode-radio :deep(.ant-radio-button-wrapper:first-child) {
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}

.mode-radio :deep(.ant-radio-button-wrapper:last-child) {
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.topk-select {
  width: 92px;
}

.topk-select :deep(.ant-select-selector) {
  font-size: 12px;
  height: 30px !important;
  border-radius: var(--radius-sm) !important;
}
.topk-select :deep(.ant-select-selection-item) { line-height: 28px !important; color: var(--gray-700) !important; }

.search-history {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed var(--gray-200);
}

.history-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--gray-500);
  font: 500 10px var(--font-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.history-icon {
  color: var(--mint-deep);
  font-size: 12px;
}

.clear-btn {
  margin-left: auto;
  color: var(--gray-500) !important;
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
  background: var(--white);
  border: 1px solid var(--gray-200);
  color: var(--gray-600);
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  font-size: 12px;
  transition: border-color var(--transition-default), color var(--transition-default), background var(--transition-default), transform var(--duration-normal) var(--ease-spring);
}

.history-tag:hover {
  border-color: var(--ink);
  color: var(--ink);
  background: var(--white);
  transform: translateY(-1px);
}
.history-tag:active { transform: translateY(0) scale(.97); }
@media (max-width: 600px) {
  .search-icon { padding: 0 10px 0 12px; }
  .search-options { gap: 12px; }
  .search-btn { padding: 0 14px !important; flex-shrink: 0; }
  .search-input :deep(.ant-input) { font-size: 14px !important; }
}
</style>
