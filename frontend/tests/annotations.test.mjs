import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, reactive } from 'vue'
import { loadModule, setupComponent, settle, deferred, frame, utils, contract, installBrowserStubs } from './annotation-test-helpers.mjs'

test('CSV accepts quoted commas, escaped quotes, Chinese delimiters and deduplicates exact names', () => {
  assert.deepEqual(utils.parseAnnotationFilenames(' road.jpg，"road,night.jpg"\n"a""b.png", road.jpg,, '),
    ['road.jpg', 'road,night.jpg', 'a"b.png'])
  assert.deepEqual(utils.parseAnnotationFilenames(utils.normalizeAnnotationFilenames('"中，文.jpg"\n"a""b.png"')),
    ['中，文.jpg', 'a"b.png'])
  assert.deepEqual(utils.parseAnnotationFilenames(' ,，\n'), [])
  for (const input of ['"unfinished', '"a.jpg"x', 'a"b.jpg', 'x'.repeat(256),
    Array.from({ length: 101 }, (_, i) => `${i}.jpg`).join(',')]) {
    assert.throws(() => utils.parseAnnotationFilenames(input))
  }
})

test('contain mapping aligns wide, portrait and resized media without counting letterboxing', () => {
  assert.deepEqual(utils.containedRect(1000, 1000, 1920, 1080), { left: 0, top: 218.75, width: 1000, height: 562.5 })
  assert.deepEqual(utils.containedRect(1000, 500, 1000, 2000), { left: 375, top: 0, width: 250, height: 500 })
  const resized = utils.containedRect(500, 500, 1920, 1080)
  assert.equal(resized.top, 109.375)
  for (const invalid of [0, -1, Infinity, NaN]) assert.equal(utils.containedRect(100, 100, invalid, 100).width, 0)
})

test('sample windows use actual presentation timestamps and the smaller adjacent interval', () => {
  const frames = [frame(0), frame(1, { timestamp_ms: 100 }), frame(2, { timestamp_ms: 1100 })]
  assert.equal(utils.annotationFrameWindowMs([0, 100, 1100], 1), 50)
  assert.equal(utils.annotationFrameWindowMs([0], 0), 250)
  assert.equal(utils.matchingAnnotationFrame(frames, 150)?.id, 'frame-1')
  assert.equal(utils.matchingAnnotationFrame(frames, 151), null)
  assert.equal(utils.matchingAnnotationFrame(frames, 849), null)
  assert.equal(utils.matchingAnnotationFrame(frames, 850)?.id, 'frame-2')
  assert.equal(utils.matchingAnnotationFrame([frame(0)], 250)?.id, 'frame-0')
  assert.equal(utils.matchingAnnotationFrame([frame(0)], 251), null)
  assert.equal(utils.matchingAnnotationFrame([frame(0, { timestamp_ms: null })], 0), null)
  assert.equal(utils.matchingAnnotationFrame(frames, NaN), null)
})

test('category colors are stable independent of order and cuboids have twelve fixed edges', () => {
  const categories = ['vehicle', 'person', '自定义类别']
  const first = categories.map(utils.annotationCategoryColor)
  assert.deepEqual(categories.toReversed().map(utils.annotationCategoryColor).toReversed(), first)
  assert.equal(new Set(first).size, 3)
  assert.equal(contract.CUBOID_EDGES.length, 12)
  assert.deepEqual(contract.CUBOID_EDGES.slice(-4), [[0, 4], [1, 5], [2, 6], [3, 7]])
})

test('frame collection follows pagination beyond 100 and fails instead of silently truncating', async () => {
  const frames = Array.from({ length: 120 }, (_, i) => frame(i))
  const requests = []
  const result = await utils.collectAnnotationFrames(async (page, size) => {
    requests.push([page, size])
    return { results: frames.slice((page - 1) * size, page * size), total: 120, page, size }
  })
  assert.deepEqual(requests, [[1, 100], [2, 100]])
  assert.equal(result.at(-1).frame_index, 119)
  await assert.rejects(utils.collectAnnotationFrames(async () => ({ results: [], total: 120 })), /分页不完整/)
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(utils.collectAnnotationFrames(async () => assert.fail('must not fetch'), controller.signal), /Aborted/)
})

test('annotation API retains wrappers, uses the authenticated client for Blob and passes cancellation', async () => {
  const calls = []
  const wrapped = { code: 200, message: 'ok', data: { task_id: 'task' } }
  const blob = new Blob(['frame'])
  const api = loadModule('../src/api/annotations.ts', { './index': { default: {
    get: async (...args) => { calls.push(args); return args[1]?.responseType === 'blob' ? blob : wrapped },
    post: async (...args) => { calls.push(args); return wrapped },
  } } })
  const signal = new AbortController().signal
  assert.equal(await api.getAnnotationConfig(signal), wrapped)
  assert.equal(await api.createAnnotationJob({ media_ids: ['m'], action: 'retry' }, signal), wrapped)
  assert.equal(await api.getAnnotationFrameImage('f/id', signal), blob)
  await api.getAnnotationFrames('run', 2, 100, signal)
  assert.deepEqual(calls[2], ['/annotations/frames/f%2Fid/image', { responseType: 'blob', signal }])
  assert.deepEqual(calls[3][1], { params: { page: 2, size: 100 }, signal })
})

function searchSetup(api, query = {}, extra = {}) {
  return setupComponent('../src/views/AnnotationSearch.vue', {
    'vue-router': { useRoute: () => reactive({ query }), useRouter: () => ({ replace() {} }) },
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 'owner' }, isAdmin: true }) },
    '@/api/annotations': api,
    ...extra,
  })
}

test('search ignores stale requests and submits type/status/CSV plus server paging', async () => {
  installBrowserStubs()
  const calls = []
  const pending = []
  const harness = searchSetup({ searchAnnotations: (request, signal) => {
    calls.push([request, signal]); const wait = deferred(); pending.push(wait); return wait.promise
  } })
  const state = harness.state
  state.filenames.value = '"a,b.jpg"，road.jpg'
  state.fileType.value = 'video'
  state.status.value = 'partial'
  const latest = state.submitSearch()
  assert.equal(calls[0][1].aborted, true)
  pending[1].resolve({ data: { results: [{ media_id: 'new' }], total: 25, page: 1, size: 20 } })
  await latest
  pending[0].resolve({ data: { results: [{ media_id: 'stale' }], total: 999, page: 1 } })
  await settle()
  assert.equal(state.results.value[0].media_id, 'new')
  assert.equal(calls[1][0].file_type, 'video')
  assert.equal(calls[1][0].status, 'partial')
  assert.equal(calls[1][0].filenames, '"a,b.jpg","road.jpg"')
  state.filenames.value = 'not-submitted.jpg'
  const paged = state.changePage(2, 20)
  assert.equal(calls[2][0].page, 2)
  assert.equal(calls[2][0].filenames, calls[1][0].filenames)
  pending[2].resolve({ data: { results: [], total: 25, page: 2 } })
  await paged
  harness.dispose()
})

test('snapshot refresh retains scope and expired/inaccessible scopes never fall back to all media', async () => {
  installBrowserStubs()
  const snapshot = {
    result_set_id: 'scope-1', total: 45, source: { tags: [{ source: 'custom', category: 'road', name: 'night' }], logic: 'OR' },
    created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60000).toISOString(),
  }
  utils.saveAnnotationScope('owner', snapshot)
  assert.equal(utils.readAnnotationScope('someone-else', 'scope-1'), null)
  const requests = []
  const harness = searchSetup({ getAnnotationResultSet: async () => ({ data: snapshot }), searchAnnotations: async request => {
    requests.push(request); throw { response: { status: 410 } }
  } }, { scope: 'scope-1' })
  await settle()
  assert.equal(harness.state.scope.value.total, 45)
  assert.equal(requests[0].result_set_id, 'scope-1')
  assert.match(harness.state.error.value, /不会自动查询全部/)
  assert.equal(requests.length, 1)
  harness.dispose()
  utils.saveAnnotationScope('owner', { ...snapshot, expires_at: new Date(0).toISOString() })
  const expired = searchSetup({ searchAnnotations: async () => assert.fail('expired scope must not query') }, { scope: 'scope-1' })
  await settle()
  assert.match(expired.state.error.value, /已过期/)
  expired.dispose()
})

test('clearing an empty invalid scope restarts an explicitly unscoped query', async () => {
  installBrowserStubs()
  const query = reactive({ scope: '' })
  const requests = []
  const harness = searchSetup({
    searchAnnotations: async request => {
      requests.push(request)
      return { data: { results: [], total: 0, page: 1, size: 20 } }
    },
  }, query, {
    'vue-router': {
      useRoute: () => reactive({ query }),
      useRouter: () => ({
        async replace({ query: next }) {
          for (const key of Object.keys(query)) delete query[key]
          Object.assign(query, next)
        },
      }),
    },
  })
  await settle()
  assert.match(harness.state.error.value, /范围参数无效/)
  assert.equal(requests.length, 0)
  await harness.state.clearScope()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].result_set_id, null)
  assert.equal(harness.state.error.value, '')
  harness.dispose()
})

test('scope URL alone restores source metadata from the server without session storage', async () => {
  installBrowserStubs()
  const requests = []
  const snapshot = {
    result_set_id: 'url-only', total: 45, source: { tags: [{ source: 'default', category: 'road', name: 'rain' }], logic: 'AND' },
    expires_at: new Date(Date.now() + 60000).toISOString(),
  }
  const harness = searchSetup({
    getAnnotationResultSet: async id => { assert.equal(id, 'url-only'); return { data: snapshot } },
    searchAnnotations: async request => { requests.push(request); return { data: { results: [], total: 0, page: 1 } } },
  }, { scope: 'url-only' })
  await settle()
  assert.equal(harness.state.scope.value.source.tags[0].name, 'rain')
  assert.equal(requests[0].result_set_id, 'url-only')
  harness.dispose()
})

test('normal owner-scoped responses may omit user_id but admin null ownership stays denied', () => {
  assert.equal(utils.ownsAnnotationMedia({ user_id: null }, 'owner', true), true)
  assert.equal(utils.ownsAnnotationMedia({ user_id: null }, 'admin', false), false)
  assert.equal(utils.ownsAnnotationMedia({ user_id: 'other' }, 'owner', true), false)
  assert.equal(utils.ownsAnnotationMedia({ user_id: null }, null, true), false)
})

test('admin viewing another owner cannot submit jobs; own retry preserves the original snapshot', async () => {
  installBrowserStubs()
  const jobs = []
  let confirm
  const harness = searchSetup({
    searchAnnotations: async () => ({ data: { results: [], total: 0, page: 1 } }),
    createAnnotationJob: async request => { jobs.push(request); return { data: { task_id: 'job' } } },
  }, {}, {
    'ant-design-vue': { message: { warning() {}, success() {}, error() {} }, Modal: { confirm: options => { confirm = options; return { destroy() {} } } } },
  })
  await settle()
  const state = harness.state
  state.results.value = [{ media_id: 'other', user_id: 'other-owner', status: 'failed' }]
  state.selected.value = ['other']
  state.submitJob('retry')
  assert.equal(confirm, undefined)
  state.results.value = [{ media_id: 'mine', user_id: 'owner', status: 'partial' }]
  state.selected.value = ['mine']
  state.submitJob('retry')
  await confirm.onOk()
  assert.deepEqual(jobs, [{ media_ids: ['mine'], action: 'retry' }])
  assert.equal(utils.ownsAnnotationMedia({ user_id: null }, 'owner'), false)
  harness.dispose()
})

test('tag transfer posts all submitted tag identities, never form edits or current-page IDs', async () => {
  installBrowserStubs()
  const tag = { source: 'custom', category: 'road', name: 'night' }
  const requests = []
  const navigation = []
  const harness = setupComponent('../src/views/TagSearch.vue', {
    '@ant-design/icons-vue': {},
    '@/api/tags': {},
    '@/api/search': { searchByTags: async () => ({ data: { results: [{ media_id: 'page-one' }], total: 45, page: 1 } }) },
    '@/utils/export': {},
    '@/api/annotations': { createAnnotationResultSet: async request => {
      requests.push(request)
      return { data: { result_set_id: 'all-45', total: 45, source: request } }
    } },
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 'owner' } }) },
    '@/router': { default: { push: value => navigation.push(value) } },
  })
  const state = harness.state
  state.tagSystem.value = { custom: [tag], default: [], default_prompt: '' }
  state.selectedTagIds.value = [JSON.stringify([tag.source, tag.category, tag.name])]
  await state.doSearch()
  state.searchLogic.value = 'OR'
  state.selectedTagIds.value = []
  await state.viewAllAnnotations()
  assert.deepEqual(requests, [{ tags: [tag], logic: 'AND' }])
  assert.deepEqual(navigation, [{ path: '/search/annotations', query: { scope: 'all-45' } }])
  harness.dispose()
})

test('import form defaults and reset preserve the annotation request contract', async () => {
  const system = reactive({
    catalogReady: true,
    configError: '',
    catalog: {
      embedding_models: { embedding: { dimensions: [1024], default_dimension: 1024 } },
      tag_models: { seed: { name: 'Seed 2.1' } },
      defaults: { embedding_model: 'embedding', embedding_dimension: 1024, tag_model: 'seed' },
    },
  })
  const module = loadModule('../src/composables/useImportForm.ts', {
    vue: await import('vue'),
    '@/api/annotations': {
      getAnnotationConfig: async () => ({ data: {
        default_prompt: 'default annotation prompt',
        model: 'seed',
      } }),
    },
    '@/api/tags': { getTagSystem: async () => ({ data: { default_prompt: 'default tag prompt' } }) },
    '@/stores/system': { useSystemStore: () => system },
    '@/utils/modelCatalog': {
      validModelSelection: () => true,
      validTosDirectory: value => value === 'tos://bucket/',
    },
  })
  const scope = effectScope()
  const state = scope.run(() => module.useImportForm())
  await settle()
  state.formState.tosDirectory = 'tos://bucket/'
  assert.equal(state.formState.generateAnnotations, true)
  assert.equal(state.formState.annotationMode, 'default')
  assert.equal(state.formState.annotationBoxMode, '2d')
  assert.equal(state.formError.value, '')
  assert.deepEqual(state.toRequest(), {
    tos_directory: 'tos://bucket/',
    embedding_model: 'embedding',
    embedding_dimension: 1024,
    tag_model: 'seed',
    generate_vectors: true,
    generate_tags: true,
    tag_mode: 'default',
    custom_tag_prompt: null,
    generate_annotations: true,
    annotation_mode: 'default',
    custom_annotation_prompt: null,
    annotation_box_mode: '2d',
    annotation_sample_interval_seconds: 1,
    annotation_max_frames: 60,
  })
  state.formState.annotationMode = 'custom'
  state.formState.customAnnotationPrompt = '  detect cones  '
  assert.equal(state.toRequest().custom_annotation_prompt, 'detect cones')
  state.formState.generateAnnotations = false
  assert.equal(state.formState.customAnnotationPrompt, '')
  assert.equal(state.toRequest().custom_annotation_prompt, null)
  state.resetForm()
  assert.equal(state.formState.generateAnnotations, true)
  assert.equal(state.formState.annotationMode, 'default')
  scope.stop()
})

test('import form enforces custom annotation prompt character limits only while enabled', async () => {
  const system = reactive({
    catalogReady: true,
    configError: '',
    catalog: {
      embedding_models: { embedding: { dimensions: [1024], default_dimension: 1024 } },
      tag_models: { seed: { name: 'Seed 2.1' } },
      defaults: { embedding_model: 'embedding', embedding_dimension: 1024, tag_model: 'seed' },
    },
  })
  const module = loadModule('../src/composables/useImportForm.ts', {
    vue: await import('vue'),
    '@/api/annotations': {
      getAnnotationConfig: async () => ({ data: { default_prompt: 'prompt', model: 'seed' } }),
    },
    '@/api/tags': { getTagSystem: async () => ({ data: { default_prompt: '' } }) },
    '@/stores/system': { useSystemStore: () => system },
    '@/utils/modelCatalog': { validModelSelection: () => true, validTosDirectory: () => true },
  })
  const scope = effectScope()
  const state = scope.run(() => module.useImportForm())
  await settle()
  state.formState.annotationMode = 'custom'
  state.formState.customAnnotationPrompt = '路'.repeat(8000)
  assert.equal(state.formError.value, '')
  state.formState.customAnnotationPrompt += '标'
  assert.match(state.formError.value, /最多 8000/)
  state.formState.generateAnnotations = false
  assert.equal(state.formError.value, '')
  scope.stop()
})

test('shared status badge distinguishes partial, skipped and not-started', () => {
  for (const [status, expected] of [['partial', '部分失败'], ['skipped', '已跳过'], ['not_started', '未开始']]) {
    const harness = setupComponent('../src/components/common/StatusBadge/StatusBadge.vue', {}, { status })
    assert.equal(harness.state.displayText.value, expected)
    assert.equal(harness.state.statusClass.value, `status-${status}`)
    harness.dispose()
  }
})
