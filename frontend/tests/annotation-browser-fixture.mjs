import http from 'node:http'
import { execFileSync } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const port = Number(process.env.FIXTURE_PORT || 8000)
const videoPath = join(tmpdir(), 'annotation-browser-fixture.mp4')
const ffmpeg = new URL('../../.tools/ffmpeg/ffmpeg', import.meta.url).pathname

if (!existsSync(videoPath)) {
  execFileSync(ffmpeg, [
    '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
    '-i', 'color=c=0x334155:s=640x360:d=4:r=30',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', videoPath,
  ])
}

const now = '2026-09-19T10:00:00Z'
const media = Array.from({ length: 45 }, (_, index) => {
  const number = index + 1
  const isVideo = number === 2
  return {
    media_id: `media-${String(number).padStart(3, '0')}`,
    user_id: 'fixture-user',
    file_name: isVideo ? 'fixture-video.mp4' : number === 1 ? 'fixture-wide.jpg' : `fixture-${String(number).padStart(3, '0')}.jpg`,
    tos_url: `tos://fixture/path-${number}/${isVideo ? 'fixture-video.mp4' : `fixture-${number}.jpg`}`,
    file_type: isVideo ? 'video' : 'image',
    status: number === 3 ? 'failed' : number === 4 ? 'not_started' : number === 5 ? 'skipped' : 'completed',
    published_run_id: number === 4 ? null : `run-${number}`,
    latest_run_id: number === 4 ? null : `run-${number}`,
    object_count: number === 4 ? 0 : 2,
    progress: number === 3
      ? { planned_frames: 4, processed_frames: 4, completed_frames: 3, failed_frames: 1 }
      : { planned_frames: isVideo ? 4 : 1, processed_frames: isVideo ? 4 : 1, completed_frames: isVideo ? 4 : 1, failed_frames: 0 },
    annotation_mode: number === 4 ? null : number % 2 ? 'default' : 'custom',
    created_at: new Date(Date.UTC(2026, 8, 19, 9, 0, 45 - index)).toISOString(),
    updated_at: now,
  }
})

const object = (id, name, category, confidence, bbox, cuboid = null) => ({
  object_id: id, name, category, confidence, bbox_2d: bbox, cuboid_3d: cuboid,
  cuboid_unavailable_reason: cuboid ? null : '视角不足', occluded: id.endsWith('2'), truncated: false,
})
const cuboid = [
  [.12, .18], [.42, .18], [.42, .58], [.12, .58],
  [.18, .12], [.48, .12], [.48, .52], [.18, .52],
]
const imageObjects = [
  object('image-1', '测试车辆', 'vehicle', .96, [.1, .2, .5, .7], cuboid),
  object('image-2', '<script>文本目标</script>', 'person', .62, [.62, .18, .78, .72]),
]
const videoObjects = [
  object('video-1', '视频车辆', 'vehicle', .91, [.2, .25, .6, .75], cuboid),
  object('video-2', '交通锥', 'road_facility', .72, [.7, .55, .8, .82]),
]
const videoFrames = [0, 1000, 2000, 3000].map((timestamp, index) => ({
  id: `video-frame-${index}`, user_id: 'fixture-user', run_id: 'run-2',
  frame_index: index, timestamp_ms: timestamp, width: 640, height: 360,
  status: 'completed', objects: index === 1 ? videoObjects : [], error: null,
}))
const imageFrame = {
  id: 'image-frame-0', user_id: 'fixture-user', run_id: 'run-1',
  frame_index: 0, timestamp_ms: null, width: 1600, height: 900,
  status: 'completed', objects: imageObjects, error: null,
}

let previewLease = 0
const requestLog = []

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(status >= 400 ? data : { code: 200, message: 'ok', data })
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
  res.end(body)
}

function sendSvg(res, label) {
  const body = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
    <rect width="1600" height="900" fill="#334155"/><path d="M0 820L650 360h300l650 460z" fill="#64748b"/>
    <rect x="160" y="180" width="640" height="450" fill="#2563eb" opacity=".35"/>
    <text x="40" y="70" fill="white" font-size="36">${label}</text>
  </svg>`
  res.writeHead(200, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'no-store' })
  res.end(body)
}

function runSummary(item) {
  return {
    id: item.latest_run_id, user_id: 'fixture-user', media_id: item.media_id, task_id: 'fixture-task',
    revision: 1, status: item.status, annotation_mode: item.annotation_mode || 'default',
    annotation_box_mode: '2d+3d', template_version: 'fixture-v1', model: 'doubao-seed-2-1-lite-260915',
    annotation_sample_interval_seconds: 1, annotation_max_frames: 60, progress: item.progress,
    model_elapsed_ms: 1234, error: null, created_at: now, updated_at: now, completed_at: now,
  }
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`)
  let body = ''
  req.on('data', chunk => { body += chunk })
  req.on('end', () => {
    const parsed = body ? JSON.parse(body) : null
    requestLog.push({ method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), body: parsed })

    if (url.pathname === '/api/auth/me') {
      return sendJson(res, { id: 'fixture-user', username: 'fixture', email: null, role: 'user', is_demo: 0, is_active: 1, created_at: now })
    }
    if (url.pathname === '/api/system/config') {
      return sendJson(res, {
        apiPrefix: '/api', appName: 'fixture', version: 'test',
        model_catalog: {
          embedding_models: { embedding: { name: 'Embedding', dimensions: [1024], default_dimension: 1024 } },
          tag_models: { 'doubao-seed-2-1-lite-260915': { name: 'Seed 2.1 Lite', description: 'fixture' } },
          defaults: { embedding_model: 'embedding', embedding_dimension: 1024, tag_model: 'doubao-seed-2-1-lite-260915', text_search_min_score: 0 },
          vector_space: { model: 'embedding', dimension: 1024, corpus_instruction_version: 'v1', query_instruction_version: 'v1', collection: 'media_vectors_v2' },
        },
      })
    }
    if (url.pathname === '/api/annotations/config') {
      return sendJson(res, {
        default_prompt: 'FIXTURE 默认自动驾驶标注 Prompt', template_version: 'fixture-v1',
        model: 'doubao-seed-2-1-lite-260915', categories: ['vehicle', 'person'], box_modes: ['2d', '2d+3d'],
        defaults: { generate_annotations: true, annotation_mode: 'default', custom_annotation_prompt: null, annotation_box_mode: '2d+3d', annotation_sample_interval_seconds: 1, annotation_max_frames: 60 },
        limits: { max_prompt_length: 8000 },
      })
    }
    if (url.pathname === '/api/tags') {
      return sendJson(res, { default: [{ source: 'default', category: 'scene', name: 'fixture-road' }], custom: [], default_prompt: 'fixture tag prompt' })
    }
    if (url.pathname === '/api/search/tags') {
      const page = parsed.page || 1
      const size = parsed.size || 12
      return sendJson(res, {
        items: media.slice((page - 1) * size, page * size).map(item => ({ ...item, similarity: 1, tags: [] })),
        total: 45, page, size,
      })
    }
    if (url.pathname === '/api/annotations/result-sets' && req.method === 'POST') {
      return sendJson(res, {
        result_set_id: 'scope-45', total: 45, source: parsed,
        created_at: now, expires_at: '2099-09-20T10:00:00Z',
      })
    }
    if (url.pathname === '/api/annotations/result-sets/scope-45') {
      return sendJson(res, {
        result_set_id: 'scope-45', total: 45,
        source: { tags: [{ source: 'default', category: 'scene', name: 'fixture-road' }], logic: 'AND' },
        created_at: now, expires_at: '2099-09-20T10:00:00Z',
      })
    }
    if (url.pathname === '/api/annotations/search') {
      const page = parsed.page || 1
      const size = parsed.size || 20
      let items = media
      if (parsed.filenames) {
        const names = [...parsed.filenames.matchAll(/"((?:""|[^"])*)"/g)].map(match => match[1].replaceAll('""', '"'))
        items = items.filter(item => names.includes(item.file_name))
      }
      if (parsed.file_type) items = items.filter(item => item.file_type === parsed.file_type)
      if (parsed.status) items = items.filter(item => item.status === parsed.status)
      return sendJson(res, { results: items.slice((page - 1) * size, page * size), total: items.length, page, size })
    }
    const mediaMatch = url.pathname.match(/^\/api\/annotations\/media\/([^/]+)$/)
    if (mediaMatch) {
      const item = media.find(value => value.media_id === decodeURIComponent(mediaMatch[1]))
      const run = item?.latest_run_id ? runSummary(item) : null
      return sendJson(res, { media: item, latest_run: run, published_run: run })
    }
    const framesMatch = url.pathname.match(/^\/api\/annotations\/runs\/([^/]+)\/frames$/)
    if (framesMatch) {
      const frames = decodeURIComponent(framesMatch[1]) === 'run-2' ? videoFrames : [imageFrame]
      return sendJson(res, { results: frames, total: frames.length, page: 1, size: 100 })
    }
    const previewMatch = url.pathname.match(/^\/api\/annotations\/media\/([^/]+)\/preview$/)
    if (previewMatch) {
      const id = decodeURIComponent(previewMatch[1])
      if (id === 'media-002') {
        previewLease++
        return sendJson(res, { media_id: id, preview_url: `/api/fixture/video.mp4?lease=${previewLease}`, expires_at: '2099-09-20T10:00:00Z' })
      }
      return sendJson(res, { media_id: id, preview_url: '/api/fixture/image.svg', expires_at: '2099-09-20T10:00:00Z' })
    }
    if (url.pathname === '/api/fixture/image.svg') return sendSvg(res, '1600 x 900 fixture')
    if (url.pathname.startsWith('/api/annotations/frames/') && url.pathname.endsWith('/image')) return sendSvg(res, 'exact decoded frame')
    if (url.pathname === '/api/fixture/video.mp4') {
      if (url.searchParams.get('lease') === '1') return sendJson(res, { detail: 'fixture expired signature' }, 403)
      const data = readFileSync(videoPath)
      res.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': data.length, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' })
      return res.end(data)
    }
    if (url.pathname === '/api/import/tasks') {
      return sendJson(res, { tasks: [{
        task_id: 'fixture-task', tos_directory: 'tos://fixture/', tag_mode: 'default', status: 'completed',
        total_files: 2, processed_files: 2, failed_files: 0, created_at: now,
        generate_vectors: true, generate_tags: true, generate_annotations: true,
        vector_status: 'completed', tag_status: 'completed', annotation_status: 'partial',
        annotation_mode: 'default', annotation_box_mode: '2d+3d',
        annotation_sample_interval_seconds: 1, annotation_max_frames: 60,
        annotation_progress: { total_files: 2, processed_files: 2, completed_files: 1, failed_files: 1, planned_frames: 5, processed_frames: 5, completed_frames: 4, failed_frames: 1, current_media_id: 'media-002', current_frame_index: 3, elapsed_ms: 1234 },
      }] })
    }
    if (url.pathname === '/api/fixture/metrics') return sendJson(res, { previewLease, requestLog })
    sendJson(res, { detail: `No fixture for ${req.method} ${url.pathname}` }, 404)
  })
})

server.listen(port, '127.0.0.1', () => {
  console.log(`annotation fixture listening on http://127.0.0.1:${port}`)
})
