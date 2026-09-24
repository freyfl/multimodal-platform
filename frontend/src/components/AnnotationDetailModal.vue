<template>
  <a-modal :open="open" :title="detail?.media.file_name ?? '标注详情'" width="94vw" :footer="null"
    :destroy-on-close="true" @cancel="close">
    <div ref="container" class="annotation-detail" data-testid="annotation-detail">
      <header class="detail-toolbar">
        <label>结果版本
          <select v-model="runId" data-testid="annotation-version" :disabled="loading || !runs.length" @change="loadRun">
            <option v-for="run in runs" :key="run.id" :value="run.id">
              v{{ run.revision }} · {{ run.id === detail?.latest_run?.id ? '最新尝试' : '历史版本' }}
              {{ run.id === detail?.published_run?.id ? '（已发布）' : '（部分结果 / 未发布）' }} · {{ annotationStatusLabels[run.status] }}
            </option>
          </select>
        </label>
        <label>框类型
          <select v-model="boxMode" data-testid="annotation-box-mode"><option value="2d">2D</option><option value="3d">3D 投影</option><option value="both">2D + 3D</option></select>
        </label>
        <button data-testid="annotation-fullscreen" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '完整容器全屏' }}</button>
        <button data-testid="annotation-close" @click="close">关闭详情</button>
      </header>
      <p class="notice">3D 投影框（模型估计），不代表真实三维尺寸或训练真值。置信度为模型自评，非校准概率。</p>
      <p v-if="run" class="notice">
        {{ annotationStatusLabels[run.status] }} · 已标注 {{ run.progress.completed_frames }}/{{ run.progress.planned_frames }} 帧 ·
        已处理 {{ run.progress.processed_frames }} · 失败 {{ run.progress.failed_frames }}
        <template v-if="isVideo"> · 抽样标注，目标间隔 {{ run.annotation_sample_interval_seconds }} 秒，最多 {{ run.annotation_max_frames }} 帧，不提供连续追踪</template>
      </p>
      <a-alert v-if="detailError" type="error" :message="detailError" show-icon />
      <a-alert v-if="run?.error" type="warning" :message="run.error" show-icon />
      <div v-if="loading" class="loading">正在读取标注详情…</div>
      <div v-else class="detail-columns">
        <section class="media-column">
          <div v-if="isVideo" class="playback-toolbar">
            <label>查看模式
              <select :value="viewMode" data-testid="annotation-view-mode" @change="changeViewMode">
                <option value="original">原视频播放</option><option value="exact">精确抽样帧</option>
              </select>
            </label>
            <button data-testid="annotation-prev-frame" :disabled="navigationIndex <= 0 || framesLoading" @click="jumpFrame(navigationIndex - 1)">上一标注帧</button>
            <button data-testid="annotation-next-frame" :disabled="navigationIndex >= frames.length - 1 || !frames.length || framesLoading" @click="jumpFrame(navigationIndex + 1)">下一标注帧</button>
          </div>
          <div class="media-stage" data-testid="annotation-media-stage">
            <video v-if="isVideo && previewUrl" v-show="viewMode === 'original'" ref="video"
              data-testid="annotation-video" :src="previewUrl" controls controlslist="nofullscreen" disablepictureinpicture playsinline preload="metadata"
              @loadedmetadata="videoMetadata" @loadeddata="videoLoaded" @error="previewFailed"
              @play="startVideoClock" @pause="pauseVideoClock" @timeupdate="timeUpdate"
              @seeking="seeking = true" @seeked="videoSeeked" />
            <img v-if="!isVideo && previewUrl" :src="previewUrl" alt="待核对的标注图片"
              @load="imageLoaded" @error="previewFailed" />
            <img v-if="isVideo && viewMode === 'exact' && frameUrl" :src="frameUrl" data-testid="annotation-exact-frame"
              :alt="`精确抽样帧 ${formatTimestamp(selectedFrame?.timestamp_ms)}`"
              @load="imageLoaded" @error="frameDecodeFailed" />
            <AnnotationOverlay v-if="canDraw" :objects="visibleObjects" :width="displaySize.width"
              :height="displaySize.height" :mode="boxMode" :selected-id="selectedObjectId" @select="selectObject" />
            <span v-if="frameLoading || (isVideo && framesLoading)" class="stage-message">读取精确帧 / 帧列表中…</span>
            <span v-else-if="!previewUrl && (!isVideo || viewMode === 'original')" class="stage-message">预览尚未就绪或不可访问</span>
            <span v-else-if="isVideo && viewMode === 'exact' && !frameUrl" class="stage-message">当前帧图像不可用，请选择其他抽样帧</span>
          </div>
          <p v-if="isVideo && viewMode === 'original'" class="notice">
            播放时间 {{ formatTimestamp(playbackMs) }} ·
            {{ currentFrame ? `对应抽样帧 ${formatTimestamp(currentFrame.timestamp_ms)}` : '无对应标注帧，已隐藏框' }}
            （窗口 ≤ ±250ms，且 ≤ 相邻样本间隔的一半）
          </p>
          <p v-if="previewError" role="alert" class="error">{{ previewError }}</p>
          <p v-if="frameError" role="alert" class="error">{{ frameError }}</p>
          <p v-if="framesLoading">正在读取全部标注帧…</p>
          <div v-if="isVideo" class="timeline" aria-label="标注时间轴">
            <button v-for="(frame, index) in frames" :key="frame.id" :data-testid="`annotation-frame-${frame.frame_index}`"
              :class="{ active: frame.id === currentFrame?.id, failed: frame.status !== 'completed' }"
              :title="`帧 ${frame.frame_index + 1} · ${annotationStatusLabels[frame.status]}`"
              @click="jumpFrame(index)">
              {{ formatTimestamp(frame.timestamp_ms) }} · {{ annotationStatusLabels[frame.status] }}
            </button>
          </div>
          <p v-if="isVideo" class="notice">已加载 {{ frames.length }} 个帧记录。点击时间点暂停并跳转；精确抽样帧来自后端解码，不依赖浏览器视频编码支持。</p>
        </section>
        <aside ref="objectList" class="object-column">
          <h3 data-testid="annotation-object-count">当前帧目标 {{ currentFrame?.status === 'completed' ? currentFrame.objects.length : '—' }}</h3>
          <label>类别
            <select v-model="category" data-testid="annotation-category"><option value="">全部类别</option><option v-for="name in categories" :key="name" :value="name">{{ name }}</option></select>
          </label>
          <label>最低模型置信度 {{ Math.round(minConfidence * 100) }}%
            <input v-model.number="minConfidence" data-testid="annotation-confidence" aria-label="最低置信度" type="range" min="0" max="1" step="0.01" />
          </label>
          <p v-if="!run">尚无标注版本，可在查询页选择本人资源生成标注。</p>
          <p v-else-if="!framesLoading && !frames.length">当前版本暂无帧结果，请稍后重新打开详情。</p>
          <p v-else-if="!currentFrame">当前时间无对应标注帧。</p>
          <p v-else-if="currentFrame.status !== 'completed'" class="error">
            {{ annotationStatusLabels[currentFrame.status] }}：{{ currentFrame.error || '该帧尚无成功标注' }}
          </p>
          <p v-else-if="currentFrame.objects.length === 0" data-testid="annotation-empty-objects">未发现目标（标注成功）</p>
          <p v-else-if="!filteredObjects.length">没有满足类别 / 置信度条件的目标。</p>
          <article v-for="entry in filteredObjects" :key="entry.object.object_id" :data-object-id="entry.object.object_id"
            :data-testid="`annotation-object-${entry.number}`"
            class="object-card" :class="{ selected: selectedObjectId === entry.object.object_id, hidden: hiddenIds.has(entry.object.object_id) }"
            :style="{ borderLeftColor: annotationCategoryColor(entry.object.category) }">
            <button class="object-select" :aria-pressed="selectedObjectId === entry.object.object_id" @click="selectObject(entry.object.object_id)">
              <strong>#{{ entry.number }} {{ entry.object.name }}</strong>
              <span>{{ entry.object.category }} · {{ Math.round(entry.object.confidence * 100) }}%</span>
            </button>
            <p>遮挡：{{ entry.object.occluded ? '是' : '否' }} · 截断：{{ entry.object.truncated ? '是' : '否' }}</p>
            <p v-if="!entry.object.cuboid_3d">3D 不可用：{{ entry.object.cuboid_unavailable_reason || '未提供原因' }}</p>
            <button @click="toggleHidden(entry.object.object_id)">{{ hiddenIds.has(entry.object.object_id) ? '显示目标' : '隐藏目标' }}</button>
          </article>
        </aside>
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  getAnnotationMedia, getAnnotationFrames, getAnnotationFrameImage, getAnnotationPreview,
} from '@/api/annotations'
import type { AnnotationFrame, AnnotationMediaDetail } from '@/types/annotation'
import { annotationCategoryColor, annotationStatusLabels, collectAnnotationFrames, matchingAnnotationFrame } from '@/utils/annotations'
import AnnotationOverlay from './AnnotationOverlay.vue'

const props = defineProps<{ open: boolean; mediaId: string | null }>()
const emit = defineEmits<{ 'update:open': [open: boolean] }>()
const container = ref<HTMLElement | null>(null)
const objectList = ref<HTMLElement | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const detail = ref<AnnotationMediaDetail | null>(null)
const loading = ref(false)
const detailError = ref('')
const previewError = ref('')
const frameError = ref('')
const runId = ref('')
const frames = ref<AnnotationFrame[]>([])
const framesLoading = ref(false)
const frameIndex = ref(0)
const frameLoading = ref(false)
const previewUrl = ref('')
const frameUrl = ref('')
const viewMode = ref<'original' | 'exact'>('original')
const boxMode = ref<'2d' | '3d' | 'both'>('both')
const category = ref('')
const minConfidence = ref(0)
const selectedObjectId = ref<string | null>(null)
const hiddenIds = ref(new Set<string>())
const playbackMs = ref(0)
const seeking = ref(false)
const videoReady = ref(false)
const imageReady = ref(false)
const videoSize = ref({ width: 0, height: 0 })
const imageSize = ref({ width: 0, height: 0 })
const fullscreen = ref(false)
let session = 0
let runVersion = 0
let frameVersion = 0
let controller: AbortController | null = null
let runController: AbortController | null = null
let frameController: AbortController | null = null
let renewed = false
let renewing = false
let restorePlayback: { time: number; paused: boolean } | null = null
let videoCallback: number | null = null

const isVideo = computed(() => detail.value?.media.file_type === 'video')
const runs = computed(() => {
  const values = [detail.value?.latest_run, detail.value?.published_run].filter(r => !!r)
  return values.filter((r, i) => values.findIndex(other => other!.id === r!.id) === i).map(r => r!)
})
const run = computed(() => runs.value.find(r => r.id === runId.value))
const selectedFrame = computed(() => frames.value[frameIndex.value] ?? null)
const currentFrame = computed(() => {
  if (!isVideo.value || viewMode.value === 'exact') return selectedFrame.value
  return seeking.value ? null : matchingAnnotationFrame(frames.value, playbackMs.value)
})
const navigationIndex = computed(() => {
  if (viewMode.value === 'exact') return frameIndex.value
  const index = frames.value.findIndex(f => f.id === currentFrame.value?.id)
  if (index >= 0) return index
  return frames.value.reduce((last, f, i) => (f.timestamp_ms ?? 0) <= playbackMs.value ? i : last, -1)
})
const categories = computed(() => [...new Set((currentFrame.value?.objects ?? []).map(o => o.category))])
const filteredObjects = computed(() => currentFrame.value?.status !== 'completed' ? [] : currentFrame.value.objects
  .map((object, index) => ({ object, number: index + 1 }))
  .filter(({ object }) => (!category.value || object.category === category.value) && object.confidence >= minConfidence.value))
const visibleObjects = computed(() => filteredObjects.value.filter(({ object }) => !hiddenIds.value.has(object.object_id)))
const displaySize = computed(() => isVideo.value && viewMode.value === 'original' ? videoSize.value : imageSize.value)
const canDraw = computed(() => !framesLoading.value && currentFrame.value?.status === 'completed'
  && (isVideo.value && viewMode.value === 'original' ? videoReady.value && !seeking.value : imageReady.value && !frameLoading.value))

function formatTimestamp(ms: number | null | undefined) { return ms == null ? '图片' : `${(ms / 1000).toFixed(3)}s` }
function releaseFrame() {
  if (frameUrl.value) URL.revokeObjectURL(frameUrl.value)
  frameUrl.value = ''
  imageReady.value = false
}
function stopVideoClock() {
  if (videoCallback !== null) video.value?.cancelVideoFrameCallback?.(videoCallback)
  videoCallback = null
}
function fullscreenChanged() { fullscreen.value = document.fullscreenElement === container.value }
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement === container.value) await document.exitFullscreen()
    else await container.value?.requestFullscreen()
  } catch { previewError.value = '当前浏览器不支持完整容器全屏' }
}
function cleanup() {
  session++
  runVersion++
  frameVersion++
  controller?.abort()
  runController?.abort()
  frameController?.abort()
  stopVideoClock()
  video.value?.pause()
  if (video.value) {
    video.value.removeAttribute('src')
    video.value.load()
  }
  releaseFrame()
  previewUrl.value = ''
  if (container.value && document.fullscreenElement === container.value) void document.exitFullscreen().catch(() => {})
  document.removeEventListener('fullscreenchange', fullscreenChanged)
}
function close() { cleanup(); emit('update:open', false) }

async function loadMedia() {
  cleanup()
  detail.value = null
  frames.value = []
  runId.value = ''
  detailError.value = ''
  previewError.value = ''
  frameError.value = ''
  viewMode.value = 'original'
  playbackMs.value = 0
  videoReady.value = false
  seeking.value = false
  imageReady.value = false
  framesLoading.value = false
  frameLoading.value = false
  renewed = false
  renewing = false
  restorePlayback = null
  category.value = ''
  minConfidence.value = 0
  fullscreen.value = false
  if (!props.open || !props.mediaId) return
  document.addEventListener('fullscreenchange', fullscreenChanged)
  controller = new AbortController()
  const token = session
  loading.value = true
  try {
    const response = await getAnnotationMedia(props.mediaId, controller.signal)
    if (token !== session) return
    detail.value = response.data
    runId.value = detail.value.latest_run?.id ?? detail.value.published_run?.id ?? ''
    void loadPreview(token)
    await loadRun()
  } catch {
    if (token === session) detailError.value = '媒体详情不可访问或已删除，请检查权限后重试'
  } finally { if (token === session) loading.value = false }
}

async function loadRun() {
  const version = ++runVersion
  runController?.abort()
  frameVersion++
  frameController?.abort()
  releaseFrame()
  frameLoading.value = false
  frames.value = []
  frameIndex.value = 0
  frameError.value = ''
  detailError.value = ''
  video.value?.pause()
  if (!runId.value) { framesLoading.value = false; return }
  runController = new AbortController()
  const signal = runController.signal
  const id = runId.value
  framesLoading.value = true
  try {
    const data = await collectAnnotationFrames(async (page, size) =>
      (await getAnnotationFrames(id, page, size, signal)).data, signal)
    if (version !== runVersion) return
    frames.value = data.sort((a, b) => (a.timestamp_ms ?? a.frame_index) - (b.timestamp_ms ?? b.frame_index))
    if (viewMode.value === 'exact') await loadExactFrame()
  } catch {
    if (version === runVersion) detailError.value = '标注帧读取失败，请切换版本或重新打开详情'
  } finally { if (version === runVersion) framesLoading.value = false }
}

async function loadPreview(token: number) {
  if (!props.mediaId) return
  try {
    const response = await getAnnotationPreview(props.mediaId, controller?.signal)
    if (token !== session) return
    videoReady.value = false
    if (!isVideo.value) imageReady.value = false
    previewUrl.value = response.data.preview_url
    await nextTick()
    if (token === session) video.value?.load()
  } catch {
    if (token === session) previewError.value = '预览授权失败或资源不可访问。视频仍可尝试精确抽样帧模式。'
  } finally {
    if (token === session) renewing = false
  }
}

function previewFailed() {
  if (!props.open || !previewUrl.value || renewing) return
  videoReady.value = false
  if (!isVideo.value) imageReady.value = false
  if (renewed) {
    previewError.value = '预览续签后仍不可播放，可能是编码不受支持或源文件不可访问。请选择精确抽样帧；不会继续自动续签。'
    return
  }
  renewed = true
  renewing = true
  stopVideoClock()
  const element = video.value
  restorePlayback = element ? { time: element.currentTime || playbackMs.value / 1000, paused: element.paused } : null
  previewError.value = '正在重新鉴权并续签预览（最多一次）…'
  void loadPreview(session)
}

function videoMetadata() {
  const element = video.value
  if (!element) return
  videoSize.value = { width: element.videoWidth, height: element.videoHeight }
  if (restorePlayback) {
    const restore = restorePlayback
    restorePlayback = null
    element.currentTime = restore.time
    if (!restore.paused && viewMode.value === 'original') {
      void element.play().catch(() => { previewError.value = '播放时间已恢复，请手动继续播放' })
    }
  }
}
function videoLoaded() { videoReady.value = true; previewError.value = '' }
function imageLoaded(event: Event) {
  const image = event.target as HTMLImageElement
  imageSize.value = { width: image.naturalWidth, height: image.naturalHeight }
  imageReady.value = true
  if (!isVideo.value) previewError.value = ''
}
function frameDecodeFailed() { imageReady.value = false; frameError.value = '抽样帧图像无法解码，请选择其他帧' }
function videoSeeked() {
  seeking.value = false
  playbackMs.value = (video.value?.currentTime ?? 0) * 1000
}
function timeUpdate() {
  const element = video.value
  if (element && (!element.requestVideoFrameCallback || element.paused)) playbackMs.value = element.currentTime * 1000
}
function startVideoClock() {
  stopVideoClock()
  const element = video.value
  const token = session
  if (!element?.requestVideoFrameCallback || element.paused || viewMode.value !== 'original') return
  videoCallback = element.requestVideoFrameCallback((_now, metadata) => {
    videoCallback = null
    if (token !== session) return
    playbackMs.value = metadata.mediaTime * 1000
    startVideoClock()
  })
}
function pauseVideoClock() { stopVideoClock(); timeUpdate() }

async function loadExactFrame() {
  const version = ++frameVersion
  frameController?.abort()
  releaseFrame()
  frameError.value = ''
  frameLoading.value = false
  const frame = selectedFrame.value
  if (!frame || viewMode.value !== 'exact') return
  frameController = new AbortController()
  frameLoading.value = true
  try {
    const blob = await getAnnotationFrameImage(frame.id, frameController.signal)
    if (version !== frameVersion) return
    frameUrl.value = URL.createObjectURL(blob)
  } catch {
    if (version === frameVersion) frameError.value = '精确抽样帧不可访问或尚未保存，请选择其他帧'
  } finally { if (version === frameVersion) frameLoading.value = false }
}

function jumpFrame(index: number) {
  const frame = frames.value[index]
  if (!frame) return
  frameIndex.value = index
  video.value?.pause()
  if (video.value && video.value.readyState >= 1 && frame.timestamp_ms !== null) {
    video.value.currentTime = frame.timestamp_ms / 1000
  }
  if (viewMode.value === 'exact') void loadExactFrame()
}
function changeViewMode(event: Event) {
  const mode = (event.target as HTMLSelectElement).value as 'original' | 'exact'
  if (mode === 'exact') {
    const index = frames.value.findIndex(frame => frame.id === currentFrame.value?.id)
    if (index >= 0) frameIndex.value = index
    video.value?.pause()
    viewMode.value = mode
    void loadExactFrame()
  } else {
    viewMode.value = mode
    frameVersion++
    frameController?.abort()
    releaseFrame()
    frameLoading.value = false
    frameError.value = ''
    jumpFrame(frameIndex.value)
  }
}
function toggleHidden(id: string) {
  const ids = new Set(hiddenIds.value)
  if (ids.has(id)) ids.delete(id)
  else ids.add(id)
  hiddenIds.value = ids
  if (ids.has(id) && selectedObjectId.value === id) selectedObjectId.value = null
}
async function selectObject(id: string) {
  selectedObjectId.value = id
  hiddenIds.value.delete(id)
  await nextTick()
  const cards = objectList.value?.querySelectorAll<HTMLElement>('[data-object-id]')
  cards?.forEach(card => { if (card.dataset.objectId === id) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) })
}
watch(() => currentFrame.value?.id, () => {
  selectedObjectId.value = null
  hiddenIds.value = new Set()
}, { flush: 'sync' })
watch([() => props.open, () => props.mediaId], () => { void loadMedia() }, { immediate: true })
onBeforeUnmount(cleanup)
</script>

<style scoped>
.annotation-detail { background: white; color: #0f172a; padding: 8px; }
.annotation-detail:fullscreen { width: 100vw; height: 100vh; overflow: auto; padding: 20px; }
.detail-toolbar, .playback-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
button, select { border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; padding: 6px 10px; color: #0f172a; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .45; }
select { max-width: 100%; }
.detail-columns { display: grid; grid-template-columns: minmax(0, 7fr) minmax(240px, 3fr); gap: 18px; margin-top: 14px; }
.media-column { min-width: 0; }
.media-stage { position: relative; height: min(58vh, 700px); min-height: 280px; background: #0b1220; border-radius: 8px; overflow: hidden; }
.media-stage video, .media-stage img { display: block; width: 100%; height: 100%; object-fit: contain; object-position: center; }
.media-stage video::-webkit-media-controls-fullscreen-button { display: none; }
.stage-message { position: absolute; left: 12px; top: 12px; color: #fff; background: #0f172abf; padding: 6px; pointer-events: none; }
.object-column { max-height: 70vh; overflow-y: auto; padding: 0 6px 12px; }
.object-column label { display: block; margin-bottom: 10px; }
.object-column select, .object-column input { width: 100%; }
.object-card { border: 1px solid #e2e8f0; border-left: 5px solid; border-radius: 8px; margin: 12px 0; padding: 10px; overflow-wrap: anywhere; font-size: 12px; }
.object-card.selected { background: #eff6ff; outline: 2px solid #2563eb; }
.object-card.hidden { opacity: .55; }
.object-select { display: block; text-align: left; border: 0; width: 100%; background: transparent; padding: 0; }
.object-select strong, .object-select span { display: block; margin-bottom: 5px; }
.notice { color: #64748b; font-size: 12px; margin: 8px 0; }
.error { color: #b91c1c; font-size: 13px; }
.timeline { display: flex; gap: 6px; overflow-x: auto; padding: 8px 0; }
.timeline button { white-space: nowrap; font-size: 12px; }
.timeline .active { background: #dbeafe; border-color: #2563eb; }
.timeline .failed { border-style: dashed; }
.loading { padding: 48px; text-align: center; }
@media (max-width: 800px) {
  .detail-columns { grid-template-columns: minmax(0, 1fr); }
  .object-column { max-height: 45vh; }
  .media-stage { height: 42vh; min-height: 220px; }
}
</style>
