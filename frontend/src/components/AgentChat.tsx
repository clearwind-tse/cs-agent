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
  neutral: 'bg-panel-2',
  joy: 'bg-ok',
  anger: 'bg-bad',
  sadness: 'bg-iris',
  fear: 'bg-iris',
  anxiety: 'bg-warn',
  disappointment: 'bg-warn',
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
  faq: 'bg-iris/20 text-info border-iris/30',
  refund_return: 'bg-warn/20 text-warn border-warn/30',
  logistics: 'bg-iris/20 text-iris border-iris/30',
  complaint: 'bg-bad/20 text-bad border-bad/30',
  order_inquiry: 'bg-ok/20 text-ok border-ok/30',
  other: 'bg-panel-2/20 text-ink border-line/30',
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
    <div className="flex-1 flex flex-col animate-fade-in h-full overflow-hidden">
      {/* 头部 */}
      <header className="h-16 px-4 sm:px-6 flex items-center justify-between border-b border-line bg-panel/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-iris to-iris flex items-center justify-center flex-shrink-0">
            <User size={20} className="text-ink" />
          </div>
          <div className="min-w-0">
            <h2 className="font-medium text-ink truncate">智能客服 Agent</h2>
            <p className="text-xs text-ink-subtle flex items-center gap-1.5 flex-wrap">
              {session && (
                <>
                  <span className="truncate">{SESSION_NAME(session)}</span>
                  <span className="text-ink-muted">·</span>
                  <span className="flex items-center gap-0.5 truncate">
                    <Hash size={10} />
                    {session.session_id}
                  </span>
                  {session.user_id && (
                    <>
                      <span className="text-ink-muted">·</span>
                      <span className="flex items-center gap-0.5">
                        <UserIcon size={10} />
                        {session.user_id}
                      </span>
                    </>
                  )}
                  {session.message_count > 0 && (
                    <>
                      <span className="text-ink-muted">·</span>
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
            <span className="ml-2 px-2 py-0.5 text-[10px] rounded-full bg-iris/20 text-info border border-iris/30 animate-pulse flex-shrink-0">
              处理中
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {lastMsg?.needsTransfer && (
            <button
              onClick={() => showToast('已为您转接人工客服，请稍候...', 'info')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-bad/20 text-bad border border-bad/30 rounded-lg hover:bg-bad/30 transition-colors"
            >
              <Phone size={14} />
              转人工客服
            </button>
          )}
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-line text-ink-muted hover:text-ink transition-colors"
          >
            <X size={18} />
          </button>
        </div>
      </header>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 sm:px-6 py-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-ink-subtle max-w-md">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-mint/30 bg-mint/10 shadow-glow">
                <User size={28} className="text-mint" />
              </div>
              <h3 className="font-display text-2xl font-bold tracking-tight text-ink mb-2">智能客服 Agent</h3>
              <p className="text-sm text-ink-muted mb-4">意图识别 · 情绪监控 · 工单闭环 · 五信号转人工</p>
              <div className="space-y-2 text-left">
                <p className="text-xs text-ink-subtle">试试问：</p>
                {[
                  '我的订单什么时候到？',
                  '我要退款',
                  '物流卡了三天没动静',
                  '我要投诉你们商家',
                ].map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setInput(q)}
                    className="block w-full px-3 py-2 text-sm text-left text-ink-muted bg-panel/60 border border-line rounded-xl hover:border-iris/40 hover:text-ink backdrop-blur-sm transition-all"
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
        <div className="px-4 py-2 border-t border-line bg-canvas/60 flex flex-wrap gap-2 items-center text-xs">
          <span className="text-ink-subtle">转人工信号：</span>
          {transferSignals.map((s) => (
            <span key={s} className="px-2 py-0.5 rounded-full bg-bad/15 text-bad border border-bad/20">
              {SIGNAL_LABEL[s] ?? s}
            </span>
          ))}
        </div>
      )}

      {/* 输入框 */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-line flex-shrink-0">
        <div className="flex gap-2 sm:gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="描述您的问题..."
            disabled={busy || streaming}
            className="flex-1 min-w-0 px-3 sm:px-4 py-3 bg-panel-2 border border-line-strong rounded-xl text-ink placeholder-ink-subtle focus:outline-none focus:border-iris/50 transition-colors disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy || streaming}
            className="px-3 sm:px-4 py-3 bg-iris hover:bg-iris text-ink rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          >
            <Send size={18} />
          </button>
          {(busy || streaming) && (
            <button
              type="button"
              onClick={abort}
              className="px-3 py-3 bg-line hover:bg-line-strong text-ink rounded-xl transition-colors flex-shrink-0"
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
          ? 'bg-gradient-to-br from-mint to-mint'
          : 'bg-gradient-to-br from-iris to-iris',
      )}>
        {isUser ? (
          <span className="text-ink text-sm font-medium">我</span>
        ) : (
          <User size={16} className="text-ink" />
        )}
      </div>
      <div className={cn('flex-1 min-w-0 max-w-[85%]', isUser && 'text-right')}>
        <div className={cn(
          'inline-block px-4 py-3 rounded-2xl text-sm text-left relative',
          isUser
            ? 'bg-iris text-ink rounded-br-md'
            : 'bg-line text-ink rounded-bl-md',
        )}>
          <p className="whitespace-pre-wrap break-words">
            {message.content}
            {isStreaming && <span className="inline-block w-1.5 h-4 bg-iris ml-0.5 animate-pulse align-middle" />}
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
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-panel-2 border border-line-strong text-ink-muted">
                  <span className={cn('w-1.5 h-1.5 rounded-full', EMOTION_COLOR[message.emotion] ?? 'bg-panel-2')} />
                  {EMOTION_LABEL[message.emotion] ?? message.emotion}
                  {message.emotionIntensity != null && `·${message.emotionIntensity}/5`}
                </span>
              )}
              {/* DST：本轮新记住的上下文槽位（教材 Ch5 对话状态追踪） */}
              {message.slots && Object.entries(message.slots).map(([k, v]) => (
                <span
                  key={k}
                  title={`对话状态已记录：${k} = ${v}`}
                  className="px-1.5 py-0.5 rounded bg-iris/10 text-info border border-iris/25"
                >
                  {k} {String(v).length > 22 ? `${String(v).slice(0, 22)}…` : v}
                </span>
              ))}
              {message.ticketNo && (
                <span className="px-1.5 py-0.5 rounded bg-ok/15 text-ok border border-ok/25 flex items-center gap-1">
                  工单 {message.ticketNo}
                  {message.ticketCategory && ` · ${message.ticketCategory}`}
                  {onOpenTickets && (
                    <button
                      onClick={onOpenTickets}
                      className="underline underline-offset-2 decoration-ok/40 hover:text-ok"
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
                  className="px-1.5 py-0.5 rounded bg-warn/15 text-warn border border-warn/30 flex items-center gap-1"
                >
                  待坐席确认
                  {onOpenTickets && (
                    <button
                      onClick={onOpenTickets}
                      className="underline underline-offset-2 decoration-warn/40 hover:text-warn"
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