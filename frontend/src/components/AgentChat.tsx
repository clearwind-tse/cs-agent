// -*- coding: utf-8 -*-
/**
 * AgentChat — 智能客服 Agent 对话界面
 *
 * 调用 /api/agent/message/stream，响应协议：
 *   metadata  {type, intent, confidence, emotion, emotion_intensity, agent}
 *   token     {type, content}
 *   answer    {type, content, agent}
 *   error     {type, message|content}
 *   done      {type, needs_transfer, signals, agent, ticket_no?}
 *
 * 特性：
 * - 消息气泡 + 意图徽章（小字 badge）+ 情绪指示器（颜色条）
 * - needs_transfer 时展示转人工按钮与信号说明
 * - 创建工单后展示 ticket_no 与分类/SLA
 * - 复用 useSSE hook（DRY）
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Send, X, User, RefreshCw, Phone, Hash, UserIcon, Clock } from 'lucide-react'
import { cn } from '../utils'
import { useSSE, type SSECallbacks } from '../hooks/useSSE'
import { useToast } from '../contexts/ToastContext'
import { type AgentSessionData, listAgentMessages } from '../api'

interface AgentMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  intent?: string
  confidence?: number
  emotion?: string
  emotionIntensity?: number
  needsTransfer?: boolean
  signals?: string[]
  ticketNo?: string
  ticketCategory?: string
  /** HITL：本轮动作挂起，等待坐席在工单页确认 */
  pendingApproval?: boolean
  pendingTitle?: string
  agentName?: string
  /** DST：本轮新记住的上下文槽位（订单号/商品/原因/退款资格…） */
  slots?: Record<string, string>
  phase?: string
}

interface AgentChatProps {
  session?: AgentSessionData | null
  onClose: () => void
  onJumpToMessage?: (sessionId: string, messageId?: number) => void
  /** 跳到工单页（可带上本会话作为过滤条件），用于「待坐席确认 / 已建单」的后续处理 */
  onOpenTickets?: (sessionId: string) => void
}

const EMOTION_COLOR: Record<string, string> = {
  neutral: 'bg-gray-400',
  joy: 'bg-green-500',
  anger: 'bg-red-500',
  sadness: 'bg-blue-500',
  fear: 'bg-purple-500',
  anxiety: 'bg-orange-500',
  disappointment: 'bg-yellow-600',
}

const EMOTION_LABEL: Record<string, string> = {
  neutral: '平静',
  joy: '开心',
  anger: '愤怒',
  sadness: '悲伤',
  fear: '恐惧',
  anxiety: '焦虑',
  disappointment: '失望',
}

const INTENT_COLOR: Record<string, string> = {
  faq: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  refund_return: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  logistics: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  complaint: 'bg-red-500/20 text-red-300 border-red-500/30',
  order_inquiry: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  other: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
}

function intentBadgeClass(intent?: string) {
  return INTENT_COLOR[intent ?? 'other'] ?? INTENT_COLOR.other
}

const SESSION_NAME = (s: AgentSessionData | null): string =>
  s?.display_name ?? `Agent · ${s?.user_id ?? 'anonymous'}`

export default function AgentChat({ session, onClose, onOpenTickets }: AgentChatProps) {
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const metaRef = useRef<Record<string, any>>({})
  const { showToast } = useToast()

  const sessionId = session?.session_id ?? 'agent-default-session'
  const userLabel = session?.user_id ?? 'anonymous'

  // 加载历史消息
  useEffect(() => {
    if (!session?.session_id) {
      setMessages([])
      return
    }
    listAgentMessages(session.session_id).then((res) => {
      const loaded: AgentMessage[] = (res.messages ?? []).map(m => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        timestamp: m.created_at ? new Date(m.created_at).getTime() / 1000 : Date.now() / 1000,
        intent: m.intent ?? undefined,
        confidence: m.confidence != null ? m.confidence / 100 : undefined,
        emotion: m.emotion ?? undefined,
        emotionIntensity: m.emotion_intensity ?? undefined,
        needsTransfer: m.needs_transfer ?? false,
        ticketNo: m.ticket_no ?? undefined,
      }))
      setMessages(loaded)
    }).catch(() => setMessages([]))
  }, [session?.session_id])

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(() => { scrollToBottom() }, [messages])

  const buildCallbacks = useCallback((): SSECallbacks => ({
    onMetadata: (p) => {
      metaRef.current = { ...p }
      setMessages((prev) => {
        const copy = [...prev]
        const last = copy[copy.length - 1]
        if (last?.role === 'assistant') {
          copy[copy.length - 1] = {
            ...last,
            intent: p.intent,
            confidence: p.confidence,
            emotion: p.emotion,
            emotionIntensity: p.emotion_intensity,
            agentName: p.agent,
            slots: (p.slots && Object.keys(p.slots).length > 0) ? p.slots : last.slots,
            phase: p.phase ?? last.phase,
          }
        }
        return copy
      })
    },
    onToken: (token) => setMessages((prev) => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, content: last.content + token }
      return copy
    }),
    onAnswer: (answer) => setMessages((prev) => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, content: answer }
      return copy
    }),
    onError: (err) => {
      setMessages((prev) => {
        const copy = [...prev]
        const last = copy[copy.length - 1]
        if (last?.role === 'assistant') copy[copy.length - 1] = { ...last, content: `[错误] ${err}` }
        return copy
      })
      showToast(err, 'error')
    },
    onDone: (p) => {
      setMessages((prev) => {
        const copy = [...prev]
        const last = copy[copy.length - 1]
        if (last?.role === 'assistant') {
          copy[copy.length - 1] = {
            ...last,
            needsTransfer: !!p.needs_transfer,
            signals: Array.isArray(p.signals) ? p.signals : [],
            ticketNo: p.ticket_no,
            ticketCategory: (p.ticket as { category?: string } | undefined)?.category,
            pendingApproval: !!p.pending_approval,
            pendingTitle: (p.pending as { title?: string } | undefined)?.title,
          }
        }
        return copy
      })
      metaRef.current = {}
    },
  }), [showToast])

  const { streaming, post, abort } = useSSE(buildCallbacks())

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const q = input.trim()
    if (!q || busy || streaming) return
    setBusy(true)
    setInput('')
    const userMsg: AgentMessage = { role: 'user', content: q, timestamp: Date.now() / 1000 }
    setMessages((prev) => [...prev, userMsg])
    setMessages((prev) => [...prev, { role: 'assistant', content: '', timestamp: Date.now() / 1000 }])
    await post('/api/agent/message/stream', {
      message: q,
      session_id: sessionId,
      user_id: userLabel,
      stream: true,
    })
    setBusy(false)
  }

  const lastMsg = messages[messages.length - 1]
  const transferSignals = lastMsg?.signals ?? []
  const SIGNAL_LABEL: Record<string, string> = {
    explicit_request: '显式请求人工',
    low_confidence: '意图置信度不足',
    emotion_escalation: '情绪恶化',
    sensitive_topic: '敏感主题',
    repeated_failure: '多次未解决',
  }

  return (
    <div className="flex-1 flex flex-col bg-dark-800 animate-fade-in h-full overflow-hidden">
      {/* 头部 */}
      <header className="h-16 px-4 sm:px-6 flex items-center justify-between border-b border-dark-600 bg-dark-800/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center flex-shrink-0">
            <User size={20} className="text-white" />
          </div>
          <div className="min-w-0">
            <h2 className="font-medium text-white truncate">智能客服 Agent</h2>
            <p className="text-xs text-gray-500 flex items-center gap-1.5 flex-wrap">
              {session && (
                <>
                  <span className="truncate">{SESSION_NAME(session)}</span>
                  <span className="text-gray-700">·</span>
                  <span className="flex items-center gap-0.5 truncate">
                    <Hash size={10} />
                    {session.session_id}
                  </span>
                  {session.user_id && (
                    <>
                      <span className="text-gray-700">·</span>
                      <span className="flex items-center gap-0.5">
                        <UserIcon size={10} />
                        {session.user_id}
                      </span>
                    </>
                  )}
                  {session.message_count > 0 && (
                    <>
                      <span className="text-gray-700">·</span>
                      <span className="flex items-center gap-0.5">
                        <Clock size={10} />
                        {session.message_count} 轮
                      </span>
                    </>
                  )}
                </>
              )}
              {!session && <span>意图识别 · 情绪监控 · 自动工单 · 五信号转人工</span>}
            </p>
          </div>
          {streaming && (
            <span className="ml-2 px-2 py-0.5 text-[10px] rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 animate-pulse flex-shrink-0">
              处理中
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {lastMsg?.needsTransfer && (
            <button
              onClick={() => showToast('已为您转接人工客服，请稍候...', 'info')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-500/20 text-red-300 border border-red-500/30 rounded-lg hover:bg-red-500/30 transition-colors"
            >
              <Phone size={14} />
              转人工客服
            </button>
          )}
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>
      </header>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 sm:px-6 py-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-gray-500 max-w-md">
              <User size={48} className="mx-auto mb-4 opacity-30" />
              <h3 className="text-lg font-medium text-gray-400 mb-2">智能客服 Agent</h3>
              <p className="text-sm mb-4">意图识别 · 情绪监控 · 工单闭环 · 五信号转人工</p>
              <div className="space-y-2 text-left">
                <p className="text-xs text-gray-600">试试问：</p>
                {[
                  '我的订单什么时候到？',
                  '我要退款',
                  '物流卡了三天没动静',
                  '我要投诉你们商家',
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
            {messages.map((msg, index) => (
              <MessageBubble
                key={index}
                message={msg}
                isStreaming={streaming && index === messages.length - 1 && msg.role === 'assistant'}
                onOpenTickets={onOpenTickets && session?.session_id
                  ? () => onOpenTickets(session.session_id)
                  : undefined}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* 底部信号条（仅最后一轮有信号时展示） */}
      {transferSignals.length > 0 && (
        <div className="px-4 py-2 border-t border-dark-600 bg-dark-900/60 flex flex-wrap gap-2 items-center text-xs">
          <span className="text-gray-500">转人工信号：</span>
          {transferSignals.map((s) => (
            <span key={s} className="px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/20">
              {SIGNAL_LABEL[s] ?? s}
            </span>
          ))}
        </div>
      )}

      {/* 输入框 */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-dark-600 flex-shrink-0">
        <div className="flex gap-2 sm:gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="描述您的问题..."
            disabled={busy || streaming}
            className="flex-1 min-w-0 px-3 sm:px-4 py-3 bg-dark-700 border border-dark-500 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500/50 transition-colors disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy || streaming}
            className="px-3 sm:px-4 py-3 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          >
            <Send size={18} />
          </button>
          {(busy || streaming) && (
            <button
              type="button"
              onClick={abort}
              className="px-3 py-3 bg-dark-600 hover:bg-dark-500 text-gray-300 rounded-xl transition-colors flex-shrink-0"
              title="中止"
            >
              <RefreshCw size={18} className={streaming ? 'animate-spin' : ''} />
            </button>
          )}
        </div>
      </form>
    </div>
  )
}

function MessageBubble({ message, isStreaming, onOpenTickets }: {
  message: AgentMessage
  isStreaming?: boolean
  onOpenTickets?: () => void
}) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div className={cn(
        'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0',
        isUser
          ? 'bg-gradient-to-br from-green-500 to-emerald-600'
          : 'bg-gradient-to-br from-cyan-500 to-blue-600',
      )}>
        {isUser ? (
          <span className="text-white text-sm font-medium">我</span>
        ) : (
          <User size={16} className="text-white" />
        )}
      </div>
      <div className={cn('flex-1 min-w-0 max-w-[85%]', isUser && 'text-right')}>
        <div className={cn(
          'inline-block px-4 py-3 rounded-2xl text-sm text-left relative',
          isUser
            ? 'bg-cyan-600 text-white rounded-br-md'
            : 'bg-dark-600 text-gray-200 rounded-bl-md',
        )}>
          <p className="whitespace-pre-wrap break-words">
            {message.content}
            {isStreaming && <span className="inline-block w-1.5 h-4 bg-cyan-400 ml-0.5 animate-pulse align-middle" />}
          </p>

          {/* 底部元数据条 */}
          {!isUser && (message.intent || message.emotion || message.ticketNo || message.slots) && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
              {message.intent && (
                <span className={cn('px-1.5 py-0.5 rounded border', intentBadgeClass(message.intent))}>
                  {message.intent.replace(/_/g, ' ')}
                  {message.confidence != null && (
                    <span className="ml-1 opacity-70">{(message.confidence * 100).toFixed(0)}%</span>
                  )}
                </span>
              )}
              {message.emotion && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-dark-700 border border-dark-500 text-gray-400">
                  <span className={cn('w-1.5 h-1.5 rounded-full', EMOTION_COLOR[message.emotion] ?? 'bg-gray-500')} />
                  {EMOTION_LABEL[message.emotion] ?? message.emotion}
                  {message.emotionIntensity != null && `·${message.emotionIntensity}/5`}
                </span>
              )}
              {/* DST：本轮新记住的上下文槽位（教材 Ch5 对话状态追踪） */}
              {message.slots && Object.entries(message.slots).map(([k, v]) => (
                <span
                  key={k}
                  title={`对话状态已记录：${k} = ${v}`}
                  className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/25"
                >
                  {k} {String(v).length > 22 ? `${String(v).slice(0, 22)}…` : v}
                </span>
              ))}
              {message.ticketNo && (
                <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25 flex items-center gap-1">
                  工单 {message.ticketNo}
                  {message.ticketCategory && ` · ${message.ticketCategory}`}
                  {onOpenTickets && (
                    <button
                      onClick={onOpenTickets}
                      className="underline underline-offset-2 decoration-emerald-400/40 hover:text-emerald-100"
                    >
                      查看
                    </button>
                  )}
                </span>
              )}
              {/* HITL：本轮动作被挂起，等坐席在工单页确认后才执行 */}
              {message.pendingApproval && (
                <span
                  title={message.pendingTitle ?? '等待坐席确认后才会执行'}
                  className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 flex items-center gap-1"
                >
                  待坐席确认
                  {onOpenTickets && (
                    <button
                      onClick={onOpenTickets}
                      className="underline underline-offset-2 decoration-amber-400/40 hover:text-amber-100"
                    >
                      去处理
                    </button>
                  )}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}