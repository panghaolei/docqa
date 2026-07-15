import { getToken } from './api'

/**
 * 基于 fetch + ReadableStream 的 SSE 消费工具
 * 因为 EventSource 不支持自定义请求头（无法带 Authorization），故使用 fetch 实现。
 *
 * @param {string} url 请求地址（完整或相对）
 * @param {object} body POST body
 * @param {object} handlers { onSession, onMeta, onToken, onDone, onError }
 */
export async function streamChat(url, body, handlers) {
  const { onSession, onMeta, onToken, onDone, onError } = handlers
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + getToken(),
        'Accept': 'text/event-stream'
      },
      body: JSON.stringify(body)
    })

    if (!resp.ok || !resp.body) {
      const text = await resp.text().catch(() => '')
      throw new Error('SSE 请求失败: ' + resp.status + ' ' + text)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let streamEnded = false

    // 解析 SSE 帧
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE 帧以空行分隔
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (parseFrame(frame, { onSession, onMeta, onToken, onDone })) {
          streamEnded = true
        }
      }
    }
    // 处理末尾残留
    if (buffer.trim()) parseFrame(buffer, { onSession, onMeta, onToken, onDone })
    if (!streamEnded) onDone && onDone()
  } catch (e) {
    onError && onError(e)
  }
}

/**
 * @returns {boolean} 是否为 done 事件
 */
function parseFrame(frame, { onSession, onMeta, onToken, onDone }) {
  let event = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
    else if (line.startsWith(':')) continue // comment / keep-alive
  }
  if (event === 'session') onSession && onSession(data)
  else if (event === 'meta') onMeta && onMeta(data)
  else if (event === 'token') onToken && onToken(data)
  else if (event === 'done') { onDone && onDone(data); return true }
  return false
}
