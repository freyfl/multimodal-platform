<template>
  <div class="tag-selector">
    <div class="selector-header">
      <TagsOutlined class="header-icon" />
      <span>{{ title }}</span>
      <span class="selected-count" v-if="selectedTags.length > 0">
        {{ selectedTags.length }}
      </span>
    </div>

    <div class="search-input-wrapper" v-if="searchable">
      <a-input
        v-model:value="searchText"
        placeholder="搜索标签..."
        class="tag-search"
        allow-clear
      >
        <template #prefix>
          <SearchOutlined class="search-icon" />
        </template>
      </a-input>
    </div>

    <div class="tags-container">
      <div
        v-for="category in filteredCategories"
        :key="category.name"
        class="tag-category"
      >
        <div class="category-header" @click="toggleCategory(category.name)">
          <span class="category-name">{{ category.label }}</span>
          <span class="category-count">{{ category.tags.length }}</span>
          <DownOutlined
            class="expand-icon"
            :class="{ expanded: expandedCategories.includes(category.name) }"
          />
        </div>
        <Transition name="expand">
          <div
            v-show="expandedCategories.includes(category.name)"
            class="category-tags"
          >
            <div
              v-for="tag in category.tags"
              :key="tag.id"
              class="tag-item"
              :class="{ selected: selectedTags.includes(tag.id) }"
              @click="toggleTag(tag)"
            >
              <CheckOutlined v-if="selectedTags.includes(tag.id)" class="check-icon" />
              <span>{{ tag.name }}</span>
              <span class="tag-count" v-if="tag.count">{{ tag.count }}</span>
            </div>
          </div>
        </Transition>
      </div>
    </div>

    <div class="selector-footer" v-if="showActions">
      <a-button @click="handleClear" :disabled="selectedTags.length === 0">
        清空选择
      </a-button>
      <a-button type="primary" @click="handleConfirm" :disabled="selectedTags.length === 0">
        确认选择
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { TagsOutlined, SearchOutlined, CheckOutlined, DownOutlined } from '@ant-design/icons-vue'

interface Tag {
  id: string
  name: string
  category?: string
  count?: number
}

interface TagCategory {
  name: string
  label: string
  tags: Tag[]
}

const props = withDefaults(defineProps<{
  title?: string
  categories: TagCategory[]
  modelValue?: string[]
  searchable?: boolean
  showActions?: boolean
  multiple?: boolean
}>(), {
  title: '选择标签',
  modelValue: () => [],
  searchable: true,
  showActions: true,
  multiple: true
})

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  change: [tags: Tag[]]
  confirm: [tags: Tag[]]
  clear: []
}>()

const searchText = ref('')
const selectedTags = ref<string[]>([...props.modelValue])
const expandedCategories = ref<string[]>(props.categories.map(c => c.name))

watch(() => props.modelValue, (val) => {
  selectedTags.value = [...val]
})

const filteredCategories = computed(() => {
  if (!searchText.value) return props.categories

  return props.categories
    .map(category => ({
      ...category,
      tags: category.tags.filter(tag =>
        tag.name.toLowerCase().includes(searchText.value.toLowerCase())
      )
    }))
    .filter(category => category.tags.length > 0)
})

const toggleCategory = (name: string) => {
  const index = expandedCategories.value.indexOf(name)
  if (index > -1) {
    expandedCategories.value.splice(index, 1)
  } else {
    expandedCategories.value.push(name)
  }
}

const toggleTag = (tag: Tag) => {
  if (props.multiple) {
    const index = selectedTags.value.indexOf(tag.id)
    if (index > -1) {
      selectedTags.value.splice(index, 1)
    } else {
      selectedTags.value.push(tag.id)
    }
  } else {
    selectedTags.value = [tag.id]
  }

  emit('update:modelValue', [...selectedTags.value])

  const selectedTagObjects = props.categories
    .flatMap(c => c.tags)
    .filter(t => selectedTags.value.includes(t.id))
  emit('change', selectedTagObjects)
}

const handleClear = () => {
  selectedTags.value = []
  emit('update:modelValue', [])
  emit('change', [])
  emit('clear')
}

const handleConfirm = () => {
  const selectedTagObjects = props.categories
    .flatMap(c => c.tags)
    .filter(t => selectedTags.value.includes(t.id))
  emit('confirm', selectedTagObjects)
}
</script>

<style scoped>
.tag-selector {
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-lg);
  padding: 18px;
}

.selector-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
}

.header-icon {
  color: var(--color-primary);
  font-size: 15px;
}

.selected-count {
  margin-left: auto;
  background: var(--color-primary-bg);
  color: var(--color-primary);
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}

.search-input-wrapper {
  margin-bottom: 14px;
}

.tag-search :deep(.ant-input) {
  background: var(--gray-50) !important;
  border-color: var(--gray-200) !important;
  border-radius: var(--radius-md) !important;
  color: var(--gray-800) !important;
  font-size: 13px;
}

.tag-search :deep(.ant-input::placeholder) {
  color: var(--gray-400) !important;
}

.search-icon {
  color: var(--gray-400);
  font-size: 13px;
}

.tags-container {
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}

.tags-container::-webkit-scrollbar {
  width: 4px;
}

.tags-container::-webkit-scrollbar-track {
  background: transparent;
}

.tags-container::-webkit-scrollbar-thumb {
  background: var(--gray-300);
  border-radius: 2px;
}

.tag-category {
  margin-bottom: 8px;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--gray-50);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.15s ease;
}

.category-header:hover {
  background: var(--gray-100);
}

.category-name {
  color: var(--gray-700);
  font-size: 13px;
  font-weight: 500;
}

.category-count {
  background: var(--color-primary-bg);
  color: var(--color-primary);
  padding: 0 7px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 18px;
}

.expand-icon {
  margin-left: auto;
  color: var(--gray-400);
  font-size: 10px;
  transition: transform 0.2s ease;
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.category-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 8px;
}

.tag-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 20px;
  color: var(--gray-600);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tag-item:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-bg);
}

.tag-item.selected {
  background: var(--color-primary-bg);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.check-icon {
  font-size: 10px;
  color: var(--color-primary);
}

.tag-count {
  background: var(--color-primary-bg);
  color: var(--color-primary);
  padding: 0 5px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 16px;
}

.selector-footer {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--gray-100);
}

.selector-footer .ant-btn {
  flex: 1;
  height: 36px;
  border-radius: var(--radius-sm);
  font-size: 13px;
}

.selector-footer .ant-btn-primary {
  border-radius: var(--radius);
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: 500px;
}
</style>
