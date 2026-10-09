<template>
  <div class="tag-cloud">
    <div class="cloud-header" v-if="title">
      <TagsOutlined class="header-icon" />
      <span>{{ title }}</span>
    </div>

    <div class="cloud-container">
      <div
        v-for="(tag, index) in tags"
        :key="tag.id"
        class="cloud-tag"
        :class="{ selected: selectedTags.includes(tag.id) }"
        :style="getTagStyle(tag, index)"
        @click="handleTagClick(tag)"
      >
        {{ tag.name }}
        <span class="tag-weight" v-if="showWeight && tag.weight">
          {{ formatWeight(tag.weight) }}
        </span>
      </div>
    </div>

    <div class="cloud-footer" v-if="showActions && selectedTags.length > 0">
      <span class="selection-info">已选择 {{ selectedTags.length }} 个标签</span>
      <a-button type="link" size="small" @click="handleClear">清空</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { TagsOutlined } from '@ant-design/icons-vue'

interface Tag {
  id: string
  name: string
  weight?: number
  category?: string
  color?: string
}

const props = withDefaults(defineProps<{
  tags: Tag[]
  title?: string
  modelValue?: string[]
  showWeight?: boolean
  showActions?: boolean
  interactive?: boolean
  colorScale?: boolean
}>(), {
  title: '',
  modelValue: () => [],
  showWeight: false,
  showActions: true,
  interactive: true,
  colorScale: true
})

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  select: [tag: Tag]
  deselect: [tag: Tag]
  clear: []
}>()

const selectedTags = ref<string[]>([...props.modelValue])

watch(() => props.modelValue, (val) => {
  selectedTags.value = [...val]
})

const getTagStyle = (tag: Tag, index: number) => {
  const styles: Record<string, string> = {}

  if (props.colorScale && tag.weight) {
    const hue = 210 + (index % 5) * 15
    const saturation = 70 + tag.weight * 30
    const lightness = 50 + tag.weight * 10
    styles['--tag-color'] = `hsl(${hue}, ${saturation}%, ${lightness}%)`
  }

  if (tag.weight) {
    const fontSize = 12 + tag.weight * 6
    styles.fontSize = `${fontSize}px`
  }

  return styles
}

const formatWeight = (weight: number): string => {
  if (weight >= 1000) {
    return `${(weight / 1000).toFixed(1)}k`
  }
  return String(Math.round(weight))
}

const handleTagClick = (tag: Tag) => {
  if (!props.interactive) return

  const index = selectedTags.value.indexOf(tag.id)
  if (index > -1) {
    selectedTags.value.splice(index, 1)
    emit('deselect', tag)
  } else {
    selectedTags.value.push(tag.id)
    emit('select', tag)
  }

  emit('update:modelValue', [...selectedTags.value])
}

const handleClear = () => {
  selectedTags.value = []
  emit('update:modelValue', [])
  emit('clear')
}
</script>

<style scoped>
.tag-cloud {
  padding: 16px;
}

.cloud-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
}

.header-icon {
  color: var(--color-primary);
}

.cloud-container {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px;
  background: var(--gray-50);
  border-radius: var(--radius-lg);
}

.cloud-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 20px;
  color: var(--tag-color, var(--gray-600));
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.cloud-tag:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
  color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.cloud-tag.selected {
  background: var(--color-primary-bg);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.tag-weight {
  background: var(--color-primary-bg);
  color: var(--color-primary);
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
}

.cloud-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-100);
}

.selection-info {
  color: var(--gray-500);
  font-size: 13px;
}

.cloud-footer .ant-btn {
  color: var(--gray-500);
  padding: 0;
  height: auto;
}
</style>
