import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { parse, compileScript } from 'vue/compiler-sfc'
import ts from 'typescript'
import { tagConstants } from './annotation-test-helpers.mjs'

// Execute the real SFC setup code with API/UI boundaries replaced. This keeps
// these regressions offline without adding a browser or a test framework.
function setupComponent(path, mocks = {}, props = {}) {
  const filename = new URL(path, import.meta.url).pathname
  const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
  const script = compileScript(descriptor, { id: filename })
  const { outputText } = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const modules = {
    vue: { ...vue, onMounted: () => {}, onBeforeUnmount: () => {} },
    'ant-design-vue': { message: { warning() {}, error() {} } },
    '@ant-design/icons-vue': {},
    '@/api/tags': { getTagSystem: async () => ({ data: {} }) },
    '@/utils/media': { getMediaUrl: url => url },
    '@/constants/tags': tagConstants,
    ...mocks,
  }
  const exports = {}
  new Function('require', 'exports', outputText)(id => {
    if (id in modules) return modules[id]
    if (id.endsWith('.vue')) return {}
    throw new Error(`Unmocked module: ${id}`)
  }, exports)
  return exports.default.setup(props, { expose() {}, emit() {} })
}

const tag = { source: 'custom', category: 'road', name: 'highway' }
const rows = Array.from({ length: 28 }, (_, i) => ({
  media_id: `media-${i}`, file_type: 'image',
}))

function searchPage(searchByTags, exportRows = () => {}) {
  const state = setupComponent('../src/views/TagSearch.vue', {
    '@/api/search': { searchByTags },
    '@/utils/export': { exportSearchResultsToExcel: exportRows },
  })
  state.tagSystem.value = { default: [], custom: [tag], default_prompt: '' }
  state.selectedTagIds.value = [JSON.stringify([tag.source, tag.category, tag.name])]
  return state
}

test('all pages are fetched from the server; export contains the current page', async () => {
  const requests = []
  const exports = []
  const state = searchPage(async request => {
    requests.push(request)
    return { data: {
      results: rows.slice((request.page - 1) * request.size, request.page * request.size),
      total: rows.length, page: request.page,
    } }
  }, items => exports.push(items))
  await state.doSearch()
  assert.equal(state.total.value, 28)
  assert.equal(state.results.value.length, 12)
  // Editing controls does not change the submitted query during pagination.
  state.searchLogic.value = 'OR'
  state.selectedTagIds.value = []
  await state.fetchPage(2)
  assert.equal(state.results.value[0].media_id, 'media-12')
  await state.fetchPage(3)
  assert.equal(state.results.value.length, 4)
  assert.equal(state.currentPage.value, 3)
  assert.deepEqual(requests.map(r => [r.page, r.size, r.logic]), [
    [1, 12, 'AND'], [2, 12, 'AND'], [3, 12, 'AND'],
  ])
  assert.deepEqual(requests[2].tags, [tag])
  state.handleExport()
  assert.deepEqual(exports[0], rows.slice(24))
  state.selectedTagIds.value = [JSON.stringify([tag.source, tag.category, tag.name])]
  await state.doSearch()
  assert.equal(requests.at(-1).page, 1)
  assert.equal(requests.at(-1).logic, 'OR')
})

test('clear invalidates an in-flight response', async () => {
  let resolve
  const state = searchPage(() => new Promise(done => { resolve = done }))
  const pending = state.doSearch()
  state.clearTags()
  resolve({ data: { results: rows.slice(0, 12), total: 28, page: 1 } })
  await pending
  assert.deepEqual(state.results.value, [])
  assert.equal(state.total.value, 0)
  assert.equal(state.searching.value, false)
})

test('server pages are displayed whole while other galleries retain local pagination', async () => {
  const props = vue.reactive({ items: rows.slice(12, 24), total: 28, page: 2, pageSize: 12 })
  const state = setupComponent('../src/components/features/search/MediaGallery.vue', {}, props)
  assert.equal(state.currentPage.value, 2)
  assert.deepEqual(state.pagedItems.value, rows.slice(12, 24))
  props.items = rows.slice(24)
  props.page = 3
  await vue.nextTick()
  assert.equal(state.currentPage.value, 3)
  assert.equal(state.pagedItems.value.length, 4)
  const local = setupComponent('../src/components/features/search/MediaGallery.vue', {}, {
    items: rows, pageSize: 12,
  })
  local.currentPage.value = 2
  assert.deepEqual(local.pagedItems.value, rows.slice(12, 24))
})
