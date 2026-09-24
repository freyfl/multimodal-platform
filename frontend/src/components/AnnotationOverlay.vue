<template>
  <div ref="host" class="annotation-overlay">
    <svg v-if="rect.width && rect.height" class="annotation-svg" data-testid="annotation-overlay"
      :style="{ left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px` }"
      :viewBox="`0 0 ${rect.width} ${rect.height}`" aria-label="标注叠加层">
      <g v-for="entry in objects" :key="entry.object.object_id" :data-testid="`annotation-box-${entry.number}`"
        :class="{ selected: entry.object.object_id === selectedId }"
        :stroke="annotationCategoryColor(entry.object.category)"
        :stroke-width="entry.object.object_id === selectedId ? 3.5 : 2"
        tabindex="0" role="button" :aria-label="`目标 ${entry.number} ${entry.object.name}`"
        :aria-pressed="entry.object.object_id === selectedId"
        @click.stop="emit('select', entry.object.object_id)"
        @keydown.enter.prevent="emit('select', entry.object.object_id)"
        @keydown.space.prevent="emit('select', entry.object.object_id)">
        <rect v-if="mode !== '3d'"
          :x="entry.object.bbox_2d[0] * rect.width" :y="entry.object.bbox_2d[1] * rect.height"
          :width="(entry.object.bbox_2d[2] - entry.object.bbox_2d[0]) * rect.width"
          :height="(entry.object.bbox_2d[3] - entry.object.bbox_2d[1]) * rect.height"
          :fill="entry.object.object_id === selectedId ? annotationCategoryColor(entry.object.category) : 'transparent'"
          :fill-opacity="entry.object.object_id === selectedId ? 0.14 : 0" />
        <template v-if="mode !== '2d' && entry.object.cuboid_3d">
          <line v-for="([a, b], index) in CUBOID_EDGES" :key="index"
            :x1="entry.object.cuboid_3d[a][0] * rect.width" :y1="entry.object.cuboid_3d[a][1] * rect.height"
            :x2="entry.object.cuboid_3d[b][0] * rect.width" :y2="entry.object.cuboid_3d[b][1] * rect.height" />
        </template>
        <text v-if="mode !== '3d' || entry.object.cuboid_3d"
          :x="Math.min(entry.object.bbox_2d[0] * rect.width + 3, Math.max(0, rect.width - 40))"
          :y="Math.max(16, entry.object.bbox_2d[1] * rect.height + 16)"
          :fill="annotationCategoryColor(entry.object.category)" stroke="#0f172a" stroke-width="3" paint-order="stroke">
          #{{ entry.number }}
        </text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CUBOID_EDGES, type AnnotationObject } from '@/types/annotation'
import { annotationCategoryColor, containedRect } from '@/utils/annotations'

const props = defineProps<{
  objects: { object: AnnotationObject; number: number }[]
  width: number
  height: number
  mode: '2d' | '3d' | 'both'
  selectedId: string | null
}>()
const emit = defineEmits<{ select: [id: string] }>()
const host = ref<HTMLElement | null>(null)
const size = ref({ width: 0, height: 0 })
const rect = computed(() => containedRect(size.value.width, size.value.height, props.width, props.height))
let observer: ResizeObserver | null = null
onMounted(() => {
  observer = new ResizeObserver(entries => {
    const bounds = entries[0]?.contentRect
    if (bounds) size.value = { width: bounds.width, height: bounds.height }
  })
  if (host.value) {
    size.value = { width: host.value.clientWidth, height: host.value.clientHeight }
    observer.observe(host.value)
  }
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.annotation-overlay { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.annotation-svg { position: absolute; overflow: visible; }
g { cursor: pointer; pointer-events: none; outline: none; }
rect { pointer-events: all; }
line { pointer-events: stroke; }
text { pointer-events: auto; font: 700 13px sans-serif; }
g:focus rect, g.selected rect { stroke-dasharray: 6 3; }
g:focus line, g.selected line { stroke-width: 3.5; }
</style>
