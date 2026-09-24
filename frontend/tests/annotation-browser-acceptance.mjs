import assert from 'node:assert/strict'

const debuggerUrl = process.env.CHROME_DEBUG_URL || 'http://127.0.0.1:9222'
const origin = process.env.FRONTEND_URL || 'http://127.0.0.1:3000'

const targets = await (await fetch(`${debuggerUrl}/json`)).json()
const target = targets.find(item => item.type === 'page')
assert.ok(target, 'Chrome page target is required')

const socket = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})

let sequence = 0
const pending = new Map()
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data)
  if (!message.id) return
  const request = pending.get(message.id)
  if (!request) return
  pending.delete(message.id)
  if (message.error) request.reject(new Error(message.error.message))
  else request.resolve(message.result)
})

function command(method, params = {}) {
  const id = ++sequence
  socket.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

async function evaluate(expression) {
  const result = await command('Runtime.evaluate', {
    expression, awaitPromise: true, returnByValue: true,
  })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
  return result.result.value
}

async function waitFor(expression, description, timeout = 8000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error(`Timed out waiting for ${description}`)
}

async function navigate(path) {
  await command('Page.navigate', { url: `${origin}${path}` })
  await waitFor(`document.readyState === 'complete'`, `navigation ${path}`)
}

async function rect(expression) {
  const value = await evaluate(`(() => {
    const element = ${expression}
    if (!element) return null
    const box = element.getBoundingClientRect()
    return { x: box.x, y: box.y, width: box.width, height: box.height }
  })()`)
  assert.ok(value?.width && value?.height, `click target missing: ${expression}`)
  return value
}

async function click(expression) {
  await evaluate(`(${expression})?.scrollIntoView({ block: 'center', inline: 'center' })`)
  const box = await rect(expression)
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await command('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
  await command('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
}

async function press(key) {
  await command('Input.dispatchKeyEvent', { type: 'keyDown', key })
  await command('Input.dispatchKeyEvent', { type: 'keyUp', key })
}

async function fill(selector, value) {
  await click(`document.querySelector(${JSON.stringify(selector)})`)
  await command('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', code: 'KeyA', modifiers: 2 })
  await command('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA', modifiers: 2 })
  await command('Input.insertText', { text: value })
}

async function select(selector, value) {
  await evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)})
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set
    setter.call(element, ${JSON.stringify(value)})
    element.dispatchEvent(new Event('change', { bubbles: true }))
  })()`)
}

await command('Page.enable')
await command('Runtime.enable')
await command('Network.enable')
await command('Emulation.setDeviceMetricsOverride', {
  width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false,
})

await navigate('/login')
await evaluate(`localStorage.setItem('accessToken', 'fixture-access'); localStorage.setItem('refreshToken', 'fixture-refresh')`)

const evidence = {}

await navigate('/import')
await waitFor(`document.body.innerText.includes('生成标注') && document.querySelector('textarea[readonly]')?.value === 'FIXTURE 默认自动驾驶标注 Prompt'`, 'import annotation config')
evidence.importDefaults = await evaluate(`(() => {
  const annotationButton = [...document.querySelectorAll('button')].find(el => el.textContent.includes('生成标注'))
  const readonly = document.querySelector('textarea[readonly]')
  return {
    enabled: annotationButton?.getAttribute('aria-pressed'),
    readonly: readonly?.readOnly,
    prompt: readonly?.value,
    sampling: document.body.innerText.includes('目标采样间隔（秒）') && document.body.innerText.includes('均匀采样覆盖全片'),
  }
})()`)
assert.deepEqual(evidence.importDefaults, {
  enabled: 'true', readonly: true, prompt: 'FIXTURE 默认自动驾驶标注 Prompt', sampling: true,
})
await click(`[...document.querySelectorAll('button')].find(el => el.textContent.includes('生成标注'))`)
assert.equal(await evaluate(`![...document.querySelectorAll('label')].some(el => el.textContent.includes('标注生成规则'))`), true)
await click(`document.querySelector('.reset-btn')`)
await waitFor(`[...document.querySelectorAll('button')].some(el => el.textContent.includes('生成标注') && el.getAttribute('aria-pressed') === 'true')`, 'annotation reset')

await navigate('/search/tags')
await waitFor(`document.body.innerText.includes('fixture-road')`, 'tag catalog')
await click(`[...document.querySelectorAll('.tag-chip')].find(el => el.textContent.includes('fixture-road'))`)
await click(`[...document.querySelectorAll('button')].find(el => el.textContent.includes('开始检索'))`)
await waitFor(`document.body.innerText.includes('检索结果') && document.body.innerText.includes('(45)')`, '45 tag results')
evidence.tagPage = await evaluate(`({
  total: [...document.querySelectorAll('.results-count')].map(el => el.textContent.trim())[0],
  visibleCards: document.querySelectorAll('.media-card').length || document.querySelectorAll('[class*="gallery"] [class*="item"]').length,
})`)
await click(`document.querySelector('[data-testid="tag-all-annotations"]')`)
await waitFor(`location.pathname === '/search/annotations' && location.search.includes('scope=scope-45') && document.body.innerText.includes('检索结果 45 条')`, 'scope transfer')
evidence.scopeTransfer = await evaluate(`({
  url: location.pathname + location.search,
  banner: document.querySelector('[data-testid="annotation-scope"]')?.innerText,
  rows: document.querySelectorAll('tbody tr[data-testid]').length,
})`)
assert.equal(evidence.scopeTransfer.rows, 20)
assert.match(evidence.scopeTransfer.banner, /45 条/)
assert.match(evidence.scopeTransfer.banner, /AND/)

await click(`document.querySelector('li[title="3"] button, li[title="3"]')`)
await waitFor(`!!document.querySelector('[data-testid="annotation-media-media-041"]')`, 'third server page')
evidence.thirdPage = await evaluate(`({
  rows: document.querySelectorAll('tbody tr[data-testid]').length,
  first: document.querySelector('tbody tr[data-testid]')?.getAttribute('data-testid'),
})`)
assert.deepEqual(evidence.thirdPage, { rows: 5, first: 'annotation-media-media-041' })

await navigate('/search/annotations?scope=scope-45')
await waitFor(`document.body.innerText.includes('标签结果集范围：45 条')`, 'scope restored from URL')
await click(`document.querySelector('[data-testid="annotation-clear-scope"]')`)
await waitFor(`!location.search.includes('scope=') && document.body.innerText.includes('检索结果 45 条')`, 'scope cleared to explicit unscoped query')
evidence.scopeClear = await evaluate(`({ url: location.pathname + location.search, scopeBanner: !!document.querySelector('[data-testid="annotation-scope"]') })`)
assert.deepEqual(evidence.scopeClear, { url: '/search/annotations', scopeBanner: false })

await fill('[data-testid="annotation-filenames"]', 'fixture-wide.jpg，"fixture-video.mp4"\nfixture-wide.jpg,,')
await click(`document.querySelector('[data-testid="annotation-search"]')`)
await waitFor(`document.body.innerText.includes('检索结果 2 条') && !!document.querySelector('[data-testid="annotation-media-media-002"]')`, 'CSV filename query')
evidence.filenameQuery = await evaluate(`({
  rows: document.querySelectorAll('tbody tr[data-testid]').length,
  names: [...document.querySelectorAll('tbody .detail-link')].map(el => el.textContent.trim()),
})`)
assert.deepEqual(evidence.filenameQuery, { rows: 2, names: ['fixture-wide.jpg', 'fixture-video.mp4'] })
await click(`document.querySelector('[data-testid="annotation-reset"]')`)
await waitFor(`document.body.innerText.includes('检索结果 45 条')`, 'filename reset')

await click(`document.querySelector('[data-testid="annotation-media-media-001"] .detail-link')`)
await waitFor(`!!document.querySelector('[data-testid="annotation-overlay"]') && document.body.innerText.includes('当前帧目标 2')`, 'image detail overlay')
evidence.imageDetail = await evaluate(`(() => {
  const columns = document.querySelector('.detail-columns')
  const left = document.querySelector('.media-column').getBoundingClientRect()
  const right = document.querySelector('.object-column').getBoundingClientRect()
  const stage = document.querySelector('[data-testid="annotation-media-stage"]').getBoundingClientRect()
  const svg = document.querySelector('[data-testid="annotation-overlay"]').getBoundingClientRect()
  const box = document.querySelector('[data-testid="annotation-box-1"] rect')
  const expected = { left: stage.left, top: stage.top + (stage.height - stage.width * 9 / 16) / 2, width: stage.width, height: stage.width * 9 / 16 }
  const errors = {
    left: Math.abs(svg.left - expected.left), top: Math.abs(svg.top - expected.top),
    width: Math.abs(svg.width - expected.width), height: Math.abs(svg.height - expected.height),
  }
  return {
    columns: getComputedStyle(columns).gridTemplateColumns,
    ratio: left.width / (left.width + right.width),
    errors,
    box: { x: Number(box.getAttribute('x')), y: Number(box.getAttribute('y')), width: Number(box.getAttribute('width')), height: Number(box.getAttribute('height')) },
    scriptNodes: document.querySelectorAll('.object-card script').length,
    escapedText: document.body.innerText.includes('<script>文本目标</script>'),
  }
})()`)
assert.ok(evidence.imageDetail.ratio > .65 && evidence.imageDetail.ratio < .75)
assert.ok(Object.values(evidence.imageDetail.errors).every(value => value <= 2))
assert.equal(evidence.imageDetail.scriptNodes, 0)
assert.equal(evidence.imageDetail.escapedText, true)

await select('[data-testid="annotation-box-mode"]', '3d')
await waitFor(`document.querySelectorAll('[data-testid="annotation-box-1"] line').length === 12 && !document.querySelector('[data-testid="annotation-box-1"] rect')`, '3D-only rendering')
evidence.mode3d = await evaluate(`({ lines: document.querySelectorAll('[data-testid="annotation-box-1"] line').length, rects: document.querySelectorAll('[data-testid="annotation-box-1"] rect').length })`)
await select('[data-testid="annotation-box-mode"]', 'both')
await waitFor(`document.querySelectorAll('[data-testid="annotation-box-1"] line').length === 12 && !!document.querySelector('[data-testid="annotation-box-1"] rect')`, 'combined rendering')
const firstBox = await rect(`document.querySelector('[data-testid="annotation-box-1"] rect')`)
await command('Input.dispatchMouseEvent', { type: 'mousePressed', x: firstBox.x + firstBox.width / 2, y: firstBox.y + firstBox.height / 2, button: 'left', clickCount: 1 })
await command('Input.dispatchMouseEvent', { type: 'mouseReleased', x: firstBox.x + firstBox.width / 2, y: firstBox.y + firstBox.height / 2, button: 'left', clickCount: 1 })
await waitFor(`document.querySelector('[data-testid="annotation-object-1"]').classList.contains('selected')`, 'box to list selection')
await click(`document.querySelector('[data-testid="annotation-object-2"] .object-select')`)
await waitFor(`document.querySelector('[data-testid="annotation-box-2"]').classList.contains('selected')`, 'list to box selection')
evidence.objectLink = true

await command('Emulation.setDeviceMetricsOverride', {
  width: 760, height: 900, deviceScaleFactor: 1, mobile: false,
})
await waitFor(`getComputedStyle(document.querySelector('.detail-columns')).gridTemplateColumns.split(' ').length === 1`, 'responsive stacked detail')
evidence.narrowColumns = await evaluate(`getComputedStyle(document.querySelector('.detail-columns')).gridTemplateColumns`)
await command('Emulation.setDeviceMetricsOverride', {
  width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false,
})
await click(`document.querySelector('[data-testid="annotation-close"]')`)
await waitFor(`!document.querySelector('[data-testid="annotation-detail"]')`, 'image detail closed')

await click(`document.querySelector('[data-testid="annotation-media-media-002"] .detail-link')`)
await waitFor(`!!document.querySelector('[data-testid="annotation-video"]') && document.body.innerText.includes('已加载 4 个帧记录')`, 'video detail')
await waitFor(`document.querySelector('[data-testid="annotation-video"]').readyState >= 1`, 'renewed video metadata')
const metricsAfterRenew = await (await fetch('http://127.0.0.1:8000/api/fixture/metrics')).json()
evidence.previewRenewals = metricsAfterRenew.data.previewLease
assert.equal(evidence.previewRenewals, 2)

await click(`document.querySelector('[data-testid="annotation-frame-1"]')`)
await waitFor(`document.body.innerText.includes('当前帧目标 2')`, 'sample frame objects')
await evaluate(`(() => {
  const video = document.querySelector('[data-testid="annotation-video"]')
  video.currentTime = 1.251
  video.dispatchEvent(new Event('timeupdate'))
})()`)
await waitFor(`document.body.innerText.includes('无对应标注帧，已隐藏框') && document.body.innerText.includes('当前帧目标 —')`, 'outside 250ms window')
evidence.outsideWindow = true
await evaluate(`(() => {
  const video = document.querySelector('[data-testid="annotation-video"]')
  video.currentTime = 1.25
  video.dispatchEvent(new Event('timeupdate'))
})()`)
await waitFor(`document.body.innerText.includes('当前帧目标 2')`, 'inclusive 250ms window')

await select('[data-testid="annotation-view-mode"]', 'exact')
await waitFor(`!!document.querySelector('[data-testid="annotation-exact-frame"]') && document.body.innerText.includes('当前帧目标 2')`, 'exact frame mode')
await click(`document.querySelector('[data-testid="annotation-next-frame"]')`)
await waitFor(`!!document.querySelector('[data-testid="annotation-exact-frame"]') && document.body.innerText.includes('未发现目标（标注成功）')`, 'next exact frame objects')
evidence.exactFrame = await evaluate(`({
  source: document.querySelector('[data-testid="annotation-exact-frame"]')?.src,
  objectCount: document.querySelector('[data-testid="annotation-object-count"]')?.textContent.trim(),
})`)
assert.match(evidence.exactFrame.source, /^blob:/)
await click(`document.querySelector('[data-testid="annotation-close"]')`)
await waitFor(`!document.querySelector('[data-testid="annotation-detail"]') && !document.querySelector('[data-testid="annotation-video"]')`, 'video close cleanup')

await navigate('/tasks')
await waitFor(`document.body.innerText.includes('fixture-task') && document.body.innerText.includes('部分失败')`, 'task progress')
evidence.taskProgress = await evaluate(`document.body.innerText.includes('文件 2/2；') && document.body.innerText.includes('帧 5/5')`)
assert.equal(evidence.taskProgress, true)

const metrics = await (await fetch('http://127.0.0.1:8000/api/fixture/metrics')).json()
evidence.requests = {
  resultSetBody: metrics.data.requestLog.find(item => item.path === '/api/annotations/result-sets')?.body,
  scopedSearchPages: metrics.data.requestLog.filter(item => item.path === '/api/annotations/search' && item.body?.result_set_id === 'scope-45').map(item => item.body.page),
  filenameBody: metrics.data.requestLog.filter(item => item.path === '/api/annotations/search' && item.body?.filenames).at(-1)?.body,
  frameRequests: metrics.data.requestLog.filter(item => item.path.includes('/frames')).map(item => item.path),
}
assert.deepEqual(evidence.requests.resultSetBody, {
  tags: [{ source: 'default', category: 'scene', name: 'fixture-road' }], logic: 'AND',
})
assert.ok(evidence.requests.scopedSearchPages.includes(3))
assert.equal(evidence.requests.filenameBody.filenames, '"fixture-wide.jpg","fixture-video.mp4"')

console.log(JSON.stringify(evidence, null, 2))
socket.close()
