import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { setupComponent, settle, deferred, frame, installBrowserStubs } from './annotation-test-helpers.mjs'

const progress = { planned_frames: 120, completed_frames: 119, processed_frames: 120, failed_frames: 1 }
const media = { media_id: 'media', file_type: 'video', file_name: 'video.mp4' }
const latest = { id: 'latest', revision: 2, status: 'partial', progress }
const published = { id: 'published', revision: 1, status: 'completed', progress }
const details = { media, latest_run: latest, published_run: published }
const page = (results, number = 1, total = results.length) => ({ data: { results, page: number, size: 100, total } })

function detailSetup(api = {}, props = reactive({ open: false, mediaId: 'media' })) {
  return setupComponent('../src/components/AnnotationDetailModal.vue', {
    '@/api/annotations': {
      getAnnotationMedia: async () => ({ data: details }),
      getAnnotationPreview: async () => ({ data: { preview_url: '/private-preview.mp4' } }),
      getAnnotationFrames: async () => page([frame(0)]),
      getAnnotationFrameImage: async () => new Blob(['private-frame']),
      ...api,
    },
  }, props)
}

test('detail defaults to latest partial, loads 120 frames, and can select the older published run', async () => {
  const browser = installBrowserStubs()
  const requests = []
  const frames = Array.from({ length: 120 }, (_, i) => frame(i))
  const props = reactive({ open: true, mediaId: 'media' })
  const harness = detailSetup({
    getAnnotationFrames: async (id, number, size) => {
      requests.push([id, number, size])
      return id === 'latest' ? page(frames.slice((number - 1) * size, number * size), number, 120) : page([frame(0, { run_id: id })])
    },
  }, props)
  await settle()
  assert.equal(harness.state.runId.value, 'latest')
  assert.equal(harness.state.frames.value.length, 120)
  assert.deepEqual(requests.slice(0, 2), [['latest', 1, 100], ['latest', 2, 100]])
  assert.deepEqual(harness.state.runs.value.map(run => run.id), ['latest', 'published'])
  harness.state.runId.value = 'published'
  await harness.state.loadRun()
  assert.equal(harness.state.frames.value[0].run_id, 'published')
  assert.equal(harness.state.currentFrame.value.status, 'completed')
  assert.equal(harness.state.currentFrame.value.objects.length, 0)
  assert.equal(harness.state.filteredObjects.value.length, 0)
  harness.dispose()
  assert.equal(browser.listeners.size, 0)
})

test('late frame/version responses cannot replace a newly selected run', async () => {
  installBrowserStubs()
  const old = deferred()
  const harness = detailSetup({
    getAnnotationFrames: (id) => id === 'latest' ? old.promise : Promise.resolve(page([frame(0, { run_id: 'published' })])),
  })
  const state = harness.state
  state.detail.value = details
  state.runId.value = 'latest'
  const first = state.loadRun()
  state.runId.value = 'published'
  await state.loadRun()
  old.resolve(page([frame(1)]))
  await first
  assert.equal(state.frames.value[0].run_id, 'published')
  harness.dispose()
})

test('exact-frame switching discards late blobs, revokes previous URLs and aborts on close', async t => {
  installBrowserStubs()
  const requests = []
  const created = []
  const revoked = []
  t.mock.method(URL, 'createObjectURL', blob => { created.push(blob); return `blob:frame-${created.length}` })
  t.mock.method(URL, 'revokeObjectURL', url => revoked.push(url))
  const harness = detailSetup({
    getAnnotationFrameImage: (id, signal) => {
      const wait = deferred(); requests.push({ id, signal, ...wait }); return wait.promise
    },
  })
  const state = harness.state
  state.detail.value = details
  state.frames.value = [frame(0), frame(1)]
  state.viewMode.value = 'exact'
  const first = state.loadExactFrame()
  state.frameIndex.value = 1
  const second = state.loadExactFrame()
  assert.equal(requests[0].signal.aborted, true)
  requests[1].resolve(new Blob(['latest']))
  await second
  requests[0].resolve(new Blob(['obsolete']))
  await first
  assert.equal(created.length, 1)
  assert.equal(state.frameUrl.value, 'blob:frame-1')
  const third = state.loadExactFrame()
  assert.deepEqual(revoked, ['blob:frame-1'])
  state.close()
  assert.equal(requests[2].signal.aborted, true)
  requests[2].resolve(new Blob(['closed']))
  await third
  assert.equal(created.length, 1)
  assert.equal(state.frameUrl.value, '')
  assert.deepEqual(harness.emitted.at(-1), ['update:open', false])
  harness.dispose()
})

test('playback outside a sample hides objects; filters keep stable object numbering and selection', async () => {
  installBrowserStubs()
  const harness = detailSetup()
  const state = harness.state
  const object = { name: 'same-name', category: 'vehicle', confidence: .9, bbox_2d: [.1, .1, .5, .5] }
  state.detail.value = details
  state.frames.value = [frame(0, { objects: [
    { ...object, object_id: 'a', confidence: .3 },
    { ...object, object_id: 'b' },
  ] }), frame(1)]
  state.playbackMs.value = 300
  assert.equal(state.currentFrame.value, null)
  assert.equal(state.visibleObjects.value.length, 0)
  state.playbackMs.value = 0
  state.minConfidence.value = .5
  assert.equal(state.filteredObjects.value[0].number, 2)
  state.toggleHidden('b')
  assert.equal(state.visibleObjects.value.length, 0)
  await state.selectObject('b')
  assert.equal(state.visibleObjects.value.length, 1)
  assert.equal(state.selectedObjectId.value, 'b')
  state.seeking.value = true
  assert.equal(state.currentFrame.value, null)
  harness.dispose()
})

test('preview renews once, restores time and playing state, and cleans callbacks/fullscreen', async () => {
  const browser = installBrowserStubs()
  let previews = 0
  const props = reactive({ open: true, mediaId: 'media' })
  const harness = detailSetup({
    getAnnotationPreview: async () => ({ data: { preview_url: `/private-preview-${++previews}.mp4` } }),
  }, props)
  await settle()
  const state = harness.state
  let plays = 0
  let pauses = 0
  let cancelled = 0
  const element = {
    currentTime: 12.345, paused: false, videoWidth: 1920, videoHeight: 1080,
    pause() { pauses++; this.paused = true },
    async play() { plays++; this.paused = false },
    load() {}, removeAttribute() {},
    requestVideoFrameCallback() { return 77 },
    cancelVideoFrameCallback(id) { assert.equal(id, 77); cancelled++ },
  }
  state.video.value = element
  state.startVideoClock()
  state.previewFailed()
  await settle()
  assert.equal(previews, 2)
  element.currentTime = 0
  element.paused = true
  state.videoMetadata()
  assert.equal(element.currentTime, 12.345)
  assert.equal(plays, 1)
  state.previewFailed()
  await settle()
  assert.equal(previews, 2)
  assert.match(state.previewError.value, /不会继续自动续签/)
  const fullContainer = { async requestFullscreen() { document.fullscreenElement = this } }
  state.container.value = fullContainer
  await state.toggleFullscreen()
  assert.equal(document.fullscreenElement, state.container.value)
  state.close()
  assert.ok(pauses > 0)
  assert.equal(cancelled, 1)
  assert.equal(document.fullscreenElement, null)
  assert.equal(browser.listeners.size, 0)
  harness.dispose()
})

test('paused preview renewal does not auto-play', async () => {
  installBrowserStubs()
  const harness = detailSetup({}, reactive({ open: true, mediaId: 'media' }))
  await settle()
  const state = harness.state
  let plays = 0
  const element = {
    currentTime: 3.5, paused: true, videoWidth: 100, videoHeight: 100,
    load() {}, removeAttribute() {}, pause() {}, play() { plays++; return Promise.resolve() },
  }
  state.video.value = element
  state.previewFailed()
  await settle()
  element.currentTime = 0
  state.videoMetadata()
  assert.equal(element.currentTime, 3.5)
  assert.equal(plays, 0)
  harness.dispose()
})

test('overlay resizes content rect and disconnects its ResizeObserver', () => {
  let observe, disconnected = false
  globalThis.ResizeObserver = class {
    constructor(callback) { observe = callback }
    observe() {}
    disconnect() { disconnected = true }
  }
  const harness = setupComponent('../src/components/AnnotationOverlay.vue', {}, {
    objects: [], width: 1920, height: 1080, mode: 'both', selectedId: null,
  })
  harness.state.host.value = { clientWidth: 1000, clientHeight: 1000 }
  harness.mount()
  assert.equal(harness.state.rect.value.top, 218.75)
  observe([{ contentRect: { width: 500, height: 500 } }])
  assert.equal(harness.state.rect.value.top, 109.375)
  harness.dispose()
  assert.equal(disconnected, true)
})
