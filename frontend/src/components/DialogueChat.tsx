import { useState, useEffect, useRef, useCallback } from 'react'
import {
  ChevronLeft, Send, Loader2, Bot, ChevronDown, AlertCircle, Flag,
} from 'lucide-react'
import {
  startDialogueSession, replyDialogue, finishDialogue,
  type DialogueScenario, type DialogueTurn,
} from '../api'
import { cn } from '../utils'

const DIFFICULTY_LABELS: Record<string, { text: string; color: string }> = {
  easy: { text: '简单', color: 'text-ok bg-ok/10' },
  medium: { text: '中等', color: 'text-warn bg-warn/10' },
  hard: { text: '困难', color: 'text-bad bg-bad/10' },
}

/** 单条气泡：客户在左（AI 扮演），客服在右（本人作答） */
function Bubble({ turn }: { turn: DialogueTurn }) {
  const isAgent = turn.role === 'agent'
  return (
    <div className={cn('flex gap-3', isAgent && 'flex-row-reverse')}>
      <div
        className={cn(
          'w-9 h-9 rounded-full flex items-center justify-center text-ink text-xs font-medium flex-shrink-0 bg-gradient-to-br',
          isAgent ? 'from-mint to-mint' : 'from-iris to-flare'
        )}
      >
        {isAgent ? '我' : <Bot size={16} />}
      </div>
      <div className="max-w-[75%]">
        <p className={cn('text-xs text-ink-subtle mb-1', isAgent && 'text-right')}>
          {isAgent ? '客服（我）' : '客户'}
        </p>
        <div
          className={cn(
            'inline-block px-4 py-2.5 rounded-2xl text-sm whitespace-pre-wrap break-words',
            isAgent
              ? 'bg-iris text-ink rounded-br-md'
              : 'bg-line text-ink rounded-bl-md'
          )}
        >
          {turn.content}
        </div>
      </div>
    </div>
  )
}

/** 只读的对话记录（结果页复用） */
export function DialogueTranscript({ turns }: { turns: DialogueTurn[] }) {
  if (!turns.length) return <p className="text-sm text-ink-subtle">（无对话记录）</p>
  return (
    <div className="space-y-4">
      {turns.map((t, i) => <Bubble key={i} turn={t} />)}
    </div>
  )
}

// 练习界面：客服正在作答。
// 【红线】此处严禁渲染 scenario.reference_replies / source_transcript（真实客服参考答案与原始对话），
// 否则等于练习中泄题。后端也只在会话结束后才下发这两个字段；本组件永远拿不到它们。
interface DialogueChatProps {
  setId: number
  scenario: DialogueScenario
  onExit: () => void
}

export default function DialogueChat({ setId, scenario, onExit }: DialogueChatProps) {
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [transcript, setTranscript] = useState<DialogueTurn[]>([])
  const [input, setInput] = useState('')
  const [starting, setStarting] = useState(true)
  const [sending, setSending] = useState(false)
  const [ended, setEnded] = useState(false)
  const [turnCount, setTurnCount] = useState(0)
  const [maxTurns, setMaxTurns] = useState(12)
  const [showBackground, setShowBackground] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  // 进入即开启一条会话，拿到客户开场白
  useEffect(() => {
    let cancelled = false
    setStarting(true)
    ;(async () => {
      try {
        const res = await startDialogueSession(setId, scenario.id)
        if (cancelled) return
        setSessionId(res.session_id)
        setTranscript(res.transcript)
        setTurnCount(res.turn_count)
        setMaxTurns(res.max_turns)
      } catch (e: any) {
        if (!cancelled) setError(e?.response?.data?.detail || '开启会话失败')
      } finally {
        if (!cancelled) setStarting(false)
      }
    })()
    return () => { cancelled = true }
  }, [setId, scenario.id])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript, sending])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || sending || ended || !sessionId) return
    setError('')
    setInput('')
    setTranscript(prev => [...prev, { role: 'agent', content: text }])
    setSending(true)
    try {
      const res = await replyDialogue(sessionId, text)
      setTranscript(prev => [...prev, { role: 'customer', content: res.customer_reply }])
      setTurnCount(res.turn_count)
      setMaxTurns(res.max_turns)
      if (res.is_end) setEnded(true)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '客户回复失败')
    } finally {
      setSending(false)
    }
  }, [input, sending, ended, sessionId])

  const handleFinish = useCallback(async () => {
    if (!sessionId || ended || sending) return
    setSending(true)
    try {
      await finishDialogue(sessionId)
      setEnded(true)
    } catch { /* ignore */ } finally { setSending(false) }
  }, [sessionId, ended, sending])

  const diff = DIFFICULTY_LABELS[scenario.difficulty] || DIFFICULTY_LABELS.medium

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-line">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onExit} className="p-2 rounded-lg hover:bg-panel-2 text-ink-muted">
            <ChevronLeft size={20} />
          </button>
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-ink truncate">对话实训 · 客户情景</h2>
            <p className="text-sm text-ink-subtle">
              已完成 {turnCount}/{maxTurns} 轮
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className={cn('text-xs px-2 py-0.5 rounded-full', diff.color)}>{diff.text}</span>
          {ended ? (
            <span className="text-xs px-2 py-0.5 rounded-full text-ok bg-ok/10">
              已结束
            </span>
          ) : (
            <button
              onClick={handleFinish}
              disabled={sending || starting}
              className="px-3 py-1.5 bg-panel-2 text-ink rounded-lg hover:bg-line disabled:opacity-50 text-sm flex items-center gap-1"
            >
              <Flag size={14} /> 结束对话
            </button>
          )}
        </div>
      </div>

      {/* 客户背景（默认折叠，供参考） */}
      <div className="px-6 pt-3">
        <button
          onClick={() => setShowBackground(v => !v)}
          className="text-sm text-ink-subtle hover:text-ink flex items-center gap-1"
        >
          <ChevronDown size={14} className={cn('transition-transform', showBackground && 'rotate-180')} />
          客户背景 / 考察点
        </button>
        {showBackground && (
          <div className="mt-2 bg-panel border border-line rounded-lg p-4 text-sm space-y-1.5">
            <p className="text-ink-muted"><span className="text-ink-subtle">人设：</span>{scenario.customer_persona}</p>
            <p className="text-ink-muted"><span className="text-ink-subtle">背景：</span>{scenario.customer_background}</p>
            <p className="text-ink-muted"><span className="text-ink-subtle">隐藏诉求：</span>{scenario.hidden_needs}</p>
            <p className="text-ink-muted"><span className="text-ink-subtle">考察点：</span>{scenario.expected_points}</p>
          </div>
        )}
      </div>

      {error && (
        <div className="mx-6 mt-3 px-4 py-2 bg-bad/10 border border-bad/30 rounded-lg text-bad text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* 对话区 */}
      <div className="flex-1 overflow-y-auto p-6">
        {starting ? (
          <div className="flex items-center justify-center h-full text-ink-subtle">
            <Loader2 size={20} className="animate-spin mr-2" /> 正在接入客户...
          </div>
        ) : (
          <>
            <DialogueTranscript turns={transcript} />
            {sending && (
              <div className="flex gap-3 mt-4">
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-ink bg-gradient-to-br from-iris to-flare flex-shrink-0">
                  <Bot size={16} />
                </div>
                <div className="bg-line text-ink-muted px-4 py-2.5 rounded-2xl rounded-bl-md text-sm">
                  <span className="inline-flex gap-1">
                    <span className="animate-pulse">●</span>
                    <span className="animate-pulse [animation-delay:150ms]">●</span>
                    <span className="animate-pulse [animation-delay:300ms]">●</span>
                  </span>
                </div>
              </div>
            )}
            {ended && (
              <p className="text-center text-sm text-ink-subtle mt-6">— 对话已结束 —</p>
            )}
            <div ref={endRef} />
          </>
        )}
      </div>

      {/* 输入区 */}
      <div className="border-t border-line p-4">
        {ended ? (
          <div className="flex items-center justify-between">
            <p className="text-sm text-ink-subtle">本次对话已完成。</p>
            <button
              onClick={onExit}
              className="px-4 py-2 bg-iris text-ink rounded-lg hover:bg-iris/80 text-sm font-medium"
            >
              返回情景列表
            </button>
          </div>
        ) : (
          <div className="flex items-end gap-3">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              disabled={starting || sending}
              placeholder="以客服身份回复客户...（回车发送）"
              className="flex-1 bg-panel-2 border border-line-strong rounded-lg px-4 py-3 text-ink placeholder-ink-subtle focus:outline-none focus:border-iris/50 disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={starting || sending || !input.trim()}
              className="px-4 py-3 bg-iris text-ink rounded-lg hover:bg-iris/80 disabled:opacity-50 flex items-center gap-2 text-sm font-medium"
            >
              {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              发送
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
