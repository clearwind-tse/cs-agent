// -*- coding: utf-8 -*-
/**
 * useSSE — 通用 SSE 流式读取 hook
 *
 * 用法：
 *   const { streaming, post, abort } = useSSE({
 *     onMetadata: (d) => { ... },
 *     onToken:    (t) => { ... },
 *     onAnswer:   (a) => { ... },
 *     onError:    (e) => { ... },
 *     onDone:     (d) => { ... },
 *   })
 *
 *   // 发起请求
 *   await post('/api/agent/message/stream', { message: '...', session_id: '...' })
 */
import { useState, useRef, useCallback } from 'react'

export interface SSECallbacks {
  onMetadata?: (data: Record<string, any>) => void
  onToken?: (token: string) => void
  onAnswer?: (answer: string) => void
  onError?: (error: string) => void
  onDone?: (data: Record<string, any>) => void
}

export function useSSE(callbacks: SSECallbacks) {
  const [streaming, setStreaming] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  // 用 ref 持有最新回调，避免闭包 stale
  const callbacksRef = useRef(callbacks)
  callbacksRef.current = callbacks

  const post = useCallback(async (url: string, body: Record<string, any>) => {
    // 中止上一次未完成的请求
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    setStreaming(true)
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok) {
        const text = await response.text().catch(() => '')
        throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No readable stream')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (controller.signal.aborted) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? '' // 保留未完成的行

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          // SSE data 行可能以 "data: " 开头，也可能直接是 JSON（FastAPI StreamingResponse 默认不带前缀）
          const raw = trimmed.startsWith('data: ') ? trimmed.slice(6) : trimmed
          if (!raw) continue

          try {
            const parsed = JSON.parse(raw) as Record<string, any>
            const type = parsed.type
            if (!type) continue
            const c = callbacksRef.current
            if (type === 'metadata' && c.onMetadata) c.onMetadata(parsed)
            else if (type === 'token' && c.onToken) c.onToken(parsed.content ?? '')
            else if (type === 'answer' && c.onAnswer) c.onAnswer(parsed.content ?? '')
            else if (type === 'error' && c.onError) c.onError(parsed.message ?? parsed.content ?? '未知错误')
            else if (type === 'done' && c.onDone) c.onDone(parsed)
          } catch {
            // 非 JSON 行忽略（SSE 允许纯文本 event 行）
          }
        }
      }

      // 兜底：若流在 done 事件之前就已断开（异常中断）
      if (!controller.signal.aborted) {
        const c = callbacksRef.current
        c.onDone?.({ type: 'done', __eof: true })
      }
    } catch (err: any) {
      if (err.name === 'AbortError') return // 用户主动中止，不发错误提示
      const msg = err?.message ?? String(err)
      callbacksRef.current.onError?.(msg)
    } finally {
      setStreaming(false)
      controllerRef.current = null
    }
  }, [])

  const abort = useCallback(() => {
    controllerRef.current?.abort()
    setStreaming(false)
    controllerRef.current = null
  }, [])

  return { streaming, post, abort }
}
