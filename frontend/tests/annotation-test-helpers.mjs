import { readFileSync } from 'node:fs'
import * as vue from 'vue'
import { parse, compileScript } from 'vue/compiler-sfc'
import ts from 'typescript'

export function loadModule(path, modules = {}) {
  const filename = new URL(path, import.meta.url).pathname
  let content = readFileSync(filename, 'utf8')
  if (filename.endsWith('.vue')) {
    const { descriptor } = parse(content, { filename })
    content = compileScript(descriptor, { id: filename }).content
  }
  const { outputText } = ts.transpileModule(content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const exports = {}
  new Function('require', 'exports', outputText)(id => {
    if (id in modules) return modules[id]
    if (id.endsWith('.vue')) return {}
    throw new Error(`Unmocked module: ${id}`)
  }, exports)
  return exports
}

export const utils = loadModule('../src/utils/annotations.ts')
export const contract = loadModule('../src/types/annotation.ts')

export function setupComponent(path, modules = {}, props = {}) {
  const cleanup = []
  const mounted = []
  const scope = vue.effectScope()
  const component = loadModule(path, {
    vue: { ...vue, onBeforeUnmount: fn => cleanup.push(fn), onMounted: fn => mounted.push(fn) },
    '@/utils/annotations': utils,
    '@/types/annotation': contract,
    'ant-design-vue': { message: { success() {}, error() {}, warning() {} }, Modal: { confirm() {} } },
    ...modules,
  })
  const emitted = []
  const state = scope.run(() => component.default.setup(props, { expose() {}, emit: (...args) => emitted.push(args) }))
  return {
    state, emitted, mount: () => mounted.forEach(fn => fn()),
    dispose: () => { cleanup.forEach(fn => fn()); scope.stop() },
  }
}

export async function settle() {
  for (let i = 0; i < 16; i++) await Promise.resolve()
  await vue.nextTick()
}

export function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

export function frame(index, overrides = {}) {
  return {
    id: `frame-${index}`, user_id: 'owner', run_id: 'latest', frame_index: index,
    timestamp_ms: index * 1000, width: 1920, height: 1080, status: 'completed', objects: [], error: null,
    ...overrides,
  }
}

export function installBrowserStubs() {
  const data = new Map()
  globalThis.sessionStorage = {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
  }
  const listeners = new Map()
  globalThis.document = {
    fullscreenElement: null,
    addEventListener: (event, fn) => listeners.set(event, fn),
    removeEventListener: (event, fn) => { if (listeners.get(event) === fn) listeners.delete(event) },
    exitFullscreen: async () => { document.fullscreenElement = null },
  }
  return { data, listeners }
}
