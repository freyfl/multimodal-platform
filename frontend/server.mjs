import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DIST_DIR = path.join(__dirname, 'dist')
// API 后端地址，可通过环境变量覆盖
const API_TARGET = process.env.API_TARGET || 'http://localhost:8000'
const PORT = process.env.PORT || 3000
// CORS 允许的源列表，多个源用逗号分隔
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || 'http://localhost:3000').split(',')

// Content-Type 映射表
const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.map': 'application/json'
}

// 获取文件 Content-Type
function getContentType(filePath) {
  const ext = path.extname(filePath).toLowerCase()
  return MIME_TYPES[ext] || 'application/octet-stream'
}

function getCacheHeaders(filePath) {
  if (path.extname(filePath).toLowerCase() === '.html') {
    return {
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0'
    }
  }
  if (filePath.startsWith(path.join(DIST_DIR, 'assets') + path.sep)) {
    return { 'Cache-Control': 'public, max-age=31536000, immutable' }
  }
  return { 'Cache-Control': 'no-cache' }
}

// 检查客户端是否支持 gzip
function supportsGzip(req) {
  const acceptEncoding = req.headers['accept-encoding'] || ''
  return acceptEncoding.includes('gzip')
}

// 代理 API 请求到后端
function proxyRequest(req, res) {
  const targetUrl = new URL(req.url, API_TARGET)

  const targetParsed = new URL(API_TARGET)
  const options = {
    hostname: targetParsed.hostname,
    port: targetParsed.port || 8000,
    path: targetUrl.pathname + targetUrl.search,
    method: req.method,
    headers: {
      ...req.headers,
      host: `${targetParsed.hostname}:${targetParsed.port || 8000}`
    }
  }

  // 删除可能导致问题的 headers
  delete options.headers['accept-encoding']

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers)
    proxyRes.pipe(res)
  })

  proxyReq.on('error', (err) => {
    console.error(`[Proxy Error] ${req.method} ${req.url}:`, err.message)
    res.writeHead(502, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({
      error: 'Bad Gateway',
      message: '无法连接到后端服务',
      detail: err.message
    }))
  })

  req.pipe(proxyReq)
}

// 提供静态文件
function serveStatic(req, res) {
  // 解码 URL 路径
  let pathname = decodeURIComponent(req.url.split('?')[0])

  // 防止路径遍历攻击
  pathname = pathname.replace(/\.{2,}/g, '')

  let filePath = path.join(DIST_DIR, pathname)

  // 如果路径是目录，尝试查找 index.html
  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, 'index.html')
  }

  // 如果文件不存在，尝试查找 .gz 版本
  const hasGzip = supportsGzip(req)
  let finalPath = filePath
  let isGzipped = false

  // 检查文件是否存在
  if (!fs.existsSync(filePath)) {
    // 尝试查找 .gz 版本
    if (hasGzip && fs.existsSync(filePath + '.gz')) {
      finalPath = filePath + '.gz'
      isGzipped = true
    } else {
      // SPA fallback: 返回 index.html
      const indexPath = path.join(DIST_DIR, 'index.html')
      if (fs.existsSync(indexPath)) {
        finalPath = indexPath
      } else {
        res.writeHead(404, { 'Content-Type': 'text/plain' })
        res.end('Not Found')
        return
      }
    }
  } else if (hasGzip && fs.existsSync(filePath + '.gz')) {
    // 存在 gzip 版本，优先使用
    finalPath = filePath + '.gz'
    isGzipped = true
  }

  // 获取原始文件路径（用于确定 Content-Type）
  const originalPath = isGzipped ? finalPath.slice(0, -3) : finalPath
  const contentType = getContentType(originalPath)

  // 读取并返回文件
  fs.readFile(finalPath, (err, data) => {
    if (err) {
      console.error(`[Error] 读取文件失败: ${finalPath}`, err.message)
      res.writeHead(500, { 'Content-Type': 'text/plain' })
      res.end('Internal Server Error')
      return
    }

    const headers = {
      'Content-Type': contentType,
      ...getCacheHeaders(originalPath)
    }

    if (isGzipped) {
      headers['Content-Encoding'] = 'gzip'
    }

    res.writeHead(200, headers)
    res.end(data)
  })
}

// 创建 HTTP 服务器
const server = http.createServer((req, res) => {
  // 设置 CORS 头（仅允许配置的源）
  const origin = req.headers.origin
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin)
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization')

  // 处理 OPTIONS 预检请求
  if (req.method === 'OPTIONS') {
    res.writeHead(204)
    res.end()
    return
  }

  // 记录请求日志
  const timestamp = new Date().toISOString()
  console.log(`[${timestamp}] ${req.method} ${req.url}`)

  // 代理 /api/* 请求
  if (req.url.startsWith('/api/')) {
    proxyRequest(req, res)
    return
  }

  // 提供静态文件
  serveStatic(req, res)
})

// 启动服务器
server.listen(PORT, '0.0.0.0', () => {
  console.log(`=================================`)
  console.log(`  前端静态文件服务器已启动`)
  console.log(`=================================`)
  console.log(`监听地址: http://0.0.0.0:${PORT}`)
  console.log(`静态目录: ${DIST_DIR}`)
  console.log(`API 代理: ${API_TARGET}`)
  console.log(`=================================`)
})

// 错误处理
server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`错误: 端口 ${PORT} 已被占用`)
  } else {
    console.error('服务器错误:', err)
  }
  process.exit(1)
})

// 优雅关闭
process.on('SIGINT', () => {
  console.log('\n正在关闭服务器...')
  server.close(() => {
    console.log('服务器已关闭')
    process.exit(0)
  })
})

process.on('SIGTERM', () => {
  console.log('\n正在关闭服务器...')
  server.close(() => {
    console.log('服务器已关闭')
    process.exit(0)
  })
})
