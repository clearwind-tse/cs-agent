import { useState, useRef, useEffect } from 'react'
import { Send, Sparkles, X, ExternalLink, Pencil, RefreshCw, ThumbsDown } from 'lucide-react'
import { cn } from '../utils'
import { maskSessionId } from '../sessionDisplay'
import { useToast } from '../contexts/ToastContext'
import axios from 'axios'

interface AIChatProps {
  sessionId?: string
  onClose: () => void
  onJumpToMessage?: (sessionId: string, messageId?: number) => void
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: Array<{
    id: number
    type?: string
    session_id: string
    summary: string
    similarity: number
    source_ids?: number[]
  }>
  timestamp: number
}

export default function AIChat({ sessionId, onClose, onJumpToMessage }: AIChatProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  
  const { showToast } = useToast()
  
  // 确认弹窗状态
  const [confirmConfig, setConfirmConfig] = useState<{
    isOpen: boolean
    title: string
    message: string
    onConfirm: () => void
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {}
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading) return

    const userMessage: Message = {
      role: 'user',
      content: input.trim(),
      timestamp: Date.now() / 1000
    }

    setMessages(prev => [...prev, userMessage])
    const question = input.trim()
    setInput('')
    setLoading(true)

    // 添加空的 assistant 消息用于流式填充
    const assistantMessage: Message = {
      role: 'assistant',
      content: '',
      timestamp: Date.now() / 1000
    }
    setMessages(prev => [...prev, assistantMessage])

    try {
      const response = await fetch('/api/knowledge/ask/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          session_id: sessionId || null,
          top_k: 3
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) throw new Error('No readable stream')

      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // 保留未完成的行

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          const data = trimmed.slice(6)

          if (data === '[DONE]') break

          try {
            const parsed = JSON.parse(data)
            
            if (parsed.type === 'sources') {
              // 更新最后一条 assistant 消息的 sources
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  last.sources = parsed.sources
                }
                return updated
              })
            } else if (parsed.type === 'content') {
              // 逐 token 追加内容（不直接 mutate state，避免 StrictMode 双重渲染导致重复）
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: last.content + parsed.content }
                }
                return updated
              })
            } else if (parsed.type === 'error') {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  last.content = parsed.content
                }
                return updated
              })
            }
          } catch {
            // 忽略解析错误
          }
        }
      }
    } catch (error: any) {
      console.error('AI stream request failed:', error)
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last.role === 'assistant') {
          last.content = '请求失败，请检查后端服务是否运行。'
        }
        return updated
      })
    } finally {
      setLoading(false)
    }
  }

  const handleRefine = async (originalContent: string, feedback: string) => {
    if (loading) return
    setLoading(true)

    // 从消息历史中找到最近的真实用户问题（排除 [优化反馈] 消息）
    const originalQuestion = [...messages].reverse().find(
      m => m.role === 'user' && !m.content.startsWith('[优化反馈]')
    )?.content || ''

    const refineMessage: Message = {
      role: 'user',
      content: `[优化反馈] ${feedback}`,
      timestamp: Date.now() / 1000
    }
    setMessages(prev => [...prev, refineMessage])

    const assistantMessage: Message = {
      role: 'assistant',
      content: '',
      timestamp: Date.now() / 1000
    }
    setMessages(prev => [...prev, assistantMessage])

    const refineQuestion = `用户对你上一次回答不满意，请根据反馈重新回答。

上一次回答：
${originalContent}

用户反馈：
${feedback}

请根据反馈改进回答，仍然只使用数据源中的信息。`

    try {
      const response = await fetch('/api/knowledge/ask/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: refineQuestion,
          session_id: sessionId || null,
          top_k: 5,
          original_question: originalQuestion
        })
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}`)

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) throw new Error('No readable stream')

      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          const data = trimmed.slice(6)
          if (data === '[DONE]') break

          try {
            const parsed = JSON.parse(data)
            if (parsed.type === 'sources') {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last.role === 'assistant') last.sources = parsed.sources
                return updated
              })
            } else if (parsed.type === 'content') {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: last.content + parsed.content }
                }
                return updated
              })
            }
          } catch {}
        }
      }
    } catch {
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last.role === 'assistant') last.content = '重新生成失败，请重试。'
        return updated
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-dark-800 animate-fade-in h-full overflow-hidden">
      {/* 头部 */}
      <header className="h-16 px-4 sm:px-6 flex items-center justify-between border-b border-dark-600 bg-dark-800/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-accent-primary to-accent-secondary flex items-center justify-center">
            <Sparkles size={20} className="text-white" />
          </div>
          <div>
            <h2 className="font-medium text-white">智能助手</h2>
            <p className="text-xs text-gray-500">
              快速检索红包 · 返利 · 霸王餐 · 订单处理
              {sessionId && ' · 当前会话'}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>
      </header>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 sm:px-6 py-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-gray-500 max-w-md">
              <Sparkles size={48} className="mx-auto mb-4 opacity-30" />
              <h3 className="text-lg font-medium text-gray-400 mb-2">智能助手</h3>
              <p className="text-sm mb-4">
                基于聊天记录，快速检索客服话术和用户问题处理
              </p>

              {/* 构建知识库按钮 */}
              <div className="flex flex-col gap-2 mb-4">
                <button
                  onClick={() => {
                    setConfirmConfig({
                      isOpen: true,
                      title: '从标注数据构建知识库',
                      message: '确定要将已审核的人工标注数据加入知识库吗？',
                      onConfirm: async () => {
                        setConfirmConfig(prev => ({ ...prev, isOpen: false }))
                        try {
                          const response = await axios.post('/api/knowledge/build-from-labeled', null, {
                            params: { clear_existing: true }
                          })
                          showToast(response.data.message || '已开始构建知识库', 'success')
                        } catch (error: any) {
                          showToast('构建失败：' + (error.response?.data?.detail || error.message), 'error')
                        }
                      }
                    })
                  }}
                  className="px-4 py-2 bg-accent-primary/20 text-accent-primary rounded-lg hover:bg-accent-primary/30 transition-colors text-sm border border-accent-primary/20"
                >
                  <div className="flex items-center justify-center gap-2">
                    <span className="text-base">📋</span>
                    <span>从标注数据构建知识库</span>
                  </div>
                </button>
              </div>

              <div className="space-y-2 text-left">
                <p className="text-xs text-gray-600">试试问：</p>
                {[
                  '霸王餐怎么参加？',
                  '客户嫌返利太少怎么回复？',
                  '优惠券为什么用不了？',
                  '客户要投诉商家怎么处理？'
                ].map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setInput(q)}
                    className="block w-full px-3 py-2 text-sm text-left text-gray-400 bg-dark-700 rounded-lg hover:bg-dark-600 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message, index) => (
              <ChatMessage key={index} message={message} isStreaming={loading && index === messages.length - 1 && message.role === 'assistant'} onJumpToMessage={onJumpToMessage} onRefine={handleRefine} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* 输入框 */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-dark-600 flex-shrink-0">
        <div className="flex gap-2 sm:gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入问题..."
            disabled={loading}
            className="flex-1 min-w-0 px-3 sm:px-4 py-3 bg-dark-700 border border-dark-500 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary/50 transition-colors disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="px-3 sm:px-4 py-3 bg-accent-primary hover:bg-accent-secondary text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          >
            <Send size={18} />
          </button>
        </div>
      </form>
      
      {/* 自定义确认弹窗 */}
      <ConfirmDialog
        isOpen={confirmConfig.isOpen}
        title={confirmConfig.title}
        message={confirmConfig.message}
        onConfirm={confirmConfig.onConfirm}
        onCancel={() => setConfirmConfig(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  )
}

function ChatMessage({ message, isStreaming = false, onJumpToMessage, onRefine }: {
  message: Message
  isStreaming?: boolean
  onJumpToMessage?: (sessionId: string, messageId?: number) => void
  onRefine?: (originalContent: string, feedback: string) => void
}) {
  const isUser = message.role === 'user'
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedbackText, setFeedbackText] = useState('')

  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div className={cn(
        'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0',
        isUser
          ? 'bg-gradient-to-br from-green-500 to-emerald-600'
          : 'bg-gradient-to-br from-accent-primary to-accent-secondary'
      )}>
        {isUser ? (
          <span className="text-white text-sm font-medium">我</span>
        ) : (
          <Sparkles size={16} className="text-white" />
        )}
      </div>

      <div className={cn('flex-1 min-w-0 max-w-[85%]', isUser && 'text-right')}>
        <div className={cn(
          'inline-block px-4 py-3 rounded-2xl text-sm text-left relative group',
          isUser
            ? 'bg-accent-primary text-white rounded-br-md'
            : 'bg-dark-600 text-gray-200 rounded-bl-md'
        )}>
          <p className="whitespace-pre-wrap break-words">
            {message.content}
            {isStreaming && <span className="inline-block w-1.5 h-4 bg-accent-primary ml-0.5 animate-pulse align-middle" />}
          </p>

          {/* 编辑/反馈按钮 */}
          {!isUser && !isStreaming && onRefine && (
            <button
              onClick={() => setShowFeedback(!showFeedback)}
              className="absolute top-2 right-2 p-1.5 rounded-lg bg-dark-500/80 hover:bg-dark-400 text-gray-500 hover:text-yellow-400 transition-all opacity-0 group-hover:opacity-100"
              title="反馈优化"
            >
              <Pencil size={12} />
            </button>
          )}
        </div>

        {/* 反馈面板 */}
        {showFeedback && !isUser && (
          <div className="mt-2 bg-dark-700 border border-dark-500 rounded-xl p-3 text-left animate-in fade-in slide-in-from-top-2 duration-200">
            <p className="text-xs text-gray-400 mb-2 flex items-center gap-1.5">
              <ThumbsDown size={12} />
              告诉 AI 哪里不好，它会重新生成
            </p>
            <textarea
              value={feedbackText}
              onChange={e => setFeedbackText(e.target.value)}
              placeholder="例如：回答太笼统，需要给出具体话术示例；或者：引用的数据不对应..."
              className="w-full bg-dark-800 border border-dark-600 text-gray-200 text-sm rounded-lg p-2.5 outline-none focus:ring-1 focus:ring-accent-primary/50 resize-none placeholder:text-gray-600"
              rows={2}
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-2">
              <button
                onClick={() => { setShowFeedback(false); setFeedbackText('') }}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => {
                  if (feedbackText.trim() && onRefine) {
                    onRefine(message.content, feedbackText.trim())
                    setShowFeedback(false)
                    setFeedbackText('')
                  }
                }}
                disabled={!feedbackText.trim()}
                className="px-3 py-1.5 text-xs bg-accent-primary text-white rounded-lg hover:bg-accent-secondary transition-colors flex items-center gap-1 disabled:opacity-40"
              >
                <RefreshCw size={12} />
                重新生成
              </button>
            </div>
          </div>
        )}

        {/* 来源引用 */}
        {message.sources && message.sources.length > 0 && (
          <div className="mt-2 space-y-1 text-left">
            <p className="text-xs text-gray-600">参考来源:</p>
            {message.sources.map((source, i) => {
              const canJump = onJumpToMessage && source.session_id
              return (
                <div
                  key={i}
                  onClick={() => {
                    if (canJump) {
                      const messageId = source.source_ids?.[0]
                      onJumpToMessage(source.session_id, messageId)
                    }
                  }}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 bg-dark-700/50 rounded-lg text-xs max-w-full overflow-hidden",
                    canJump && "cursor-pointer hover:bg-dark-600/70 transition-colors"
                  )}
                >
                  <ExternalLink size={12} className="text-accent-primary flex-shrink-0" />
                  <span className="text-gray-400 truncate flex-1 min-w-0">
                    {source.summary?.slice(0, 50) || maskSessionId(source.session_id)}
                  </span>
                  <span className="text-gray-600 flex-shrink-0">
                    {(source.similarity * 100).toFixed(0)}%
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

// 提取的确认弹窗组件
function ConfirmDialog({ 
  isOpen, 
  title, 
  message, 
  onConfirm, 
  onCancel 
}: { 
  isOpen: boolean
  title: string
  message: string
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      
      <div className="relative w-full max-w-sm bg-dark-900 border border-dark-600 rounded-2xl shadow-2xl overflow-hidden animate-scale-in mx-4">
        <div className="p-6">
          <h3 className="text-xl font-bold text-white mb-2">{title}</h3>
          <p className="text-gray-400 text-sm leading-relaxed">
            {message}
          </p>
        </div>
        
        <div className="px-6 py-4 border-t border-dark-600/50 bg-dark-800/50 flex flex-col-reverse sm:flex-row gap-3 sm:justify-end">
          <button
            onClick={onCancel}
            className="w-full sm:w-auto px-5 py-2.5 rounded-xl border border-dark-500 text-gray-300 hover:text-white hover:bg-dark-700/50 transition-all text-sm font-medium"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-accent-primary/10 text-accent-primary hover:bg-accent-primary border border-accent-primary/20 hover:border-accent-primary hover:text-white transition-all text-sm font-medium shadow-sm"
          >
            确认执行
          </button>
        </div>
      </div>
    </div>
  )
}
