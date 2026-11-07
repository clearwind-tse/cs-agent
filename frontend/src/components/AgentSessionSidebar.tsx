// -*- coding: utf-8 -*-
/**
 * AgentSessionSidebar — Agent 会话侧边栏
 *
 * 功能：
 * - 顶部「客服工作台」入口：会话 / 工单 / Skill & MCP / Agent 配置（跳转到对应子页面）
 * - 列出所有 AgentSession（支持按 user_id 过滤）
 * - 新建会话弹窗（可填写 session_id / user_id，自动生成交替选项）
 * - 点击切换当前会话；悬浮出现「本会话工单」跳转
 * - 删除会话（二次确认）
 */
import {
  Plus, Trash2, MessageSquare, User, RefreshCw,
  Loader2, AlertCircle, X, Hash, Clock,
  LifeBuoy, Tag, Bot, ChevronRight,
} from 'lucide-react'
import {
  listAgentSessions,
  createAgentSession,
  deleteAgentSession,
  ticketStats,
  type AgentSessionData,
} from '../api'
import { cn, formatTime, truncate } from '../utils'
import { useState, useEffect, useCallback } from 'react'
import type { AgentPane } from '../appRoutes'

interface AgentSessionSidebarProps {
  selectedSession: AgentSessionData | null
  onSelectSession: (session: AgentSessionData | null) => void
  onCreateSession: (session: AgentSessionData | null) => void
  /** 当前工作台子页面（不传则不显示工作台入口，保持向后兼容） */
  pane?: AgentPane
  onSelectPane?: (pane: AgentPane) => void
  /** 跳到「只属于这个会话」的工单列表 */
  onOpenSessionTickets?: (sessionId: string) => void
}

interface WorkbenchNavItem {
  key: AgentPane
  label: string
  icon: typeof MessageSquare
}

const WORKBENCH_NAV: WorkbenchNavItem[] = [
  { key: 'chat', label: '会话', icon: MessageSquare },
  { key: 'ticket', label: '工单', icon: LifeBuoy },
  { key: 'skill', label: 'Skill & MCP', icon: Tag },
  { key: 'config', label: 'Agent 配置', icon: Bot },
]

interface NewSessionForm {
  session_id: string
  user_id: string
  display_name: string
}

function generateSessionId(): string {
  return `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export default function AgentSessionSidebar({
  selectedSession,
  onSelectSession,
  onCreateSession,
  pane,
  onSelectPane,
  onOpenSessionTickets,
}: AgentSessionSidebarProps) {
  const [sessions, setSessions] = useState<AgentSessionData[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [showNewDialog, setShowNewDialog] = useState(false)
  const [form, setForm] = useState<NewSessionForm>({
    session_id: '',
    user_id: '',
    display_name: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [autoSessionId, setAutoSessionId] = useState(false)
  /** 工单入口右侧的「未结」角标，点开工单页后回来能看到最新值 */
  const [openTickets, setOpenTickets] = useState<number | null>(null)

  const loadSessions = useCallback(async () => {
    try {
      setLoading(true)
      const res = await listAgentSessions({ limit: 100 })
      setSessions(res.sessions ?? [])
      setError(null)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadSessions() }, [loadSessions])

  // 工单角标：轻量统计，失败就静默不显示（不打扰主流程）
  useEffect(() => {
    let cancelled = false
    ticketStats()
      .then((s) => { if (!cancelled) setOpenTickets(s?.open_total ?? null) })
      .catch(() => { if (!cancelled) setOpenTickets(null) })
    return () => { cancelled = true }
  }, [pane])

  const handleCreate = async () => {
    const sid = autoSessionId ? generateSessionId() : form.session_id.trim()
    if (!sid) return
    const uid = form.user_id.trim() || undefined
    const displayName = form.display_name.trim() || undefined
    setCreating(true)
    try {
      const session = await createAgentSession({
        session_id: sid,
        user_id: uid,
        display_name: displayName,
      })
      setSessions(prev => [session, ...prev])
      onSelectSession(session)
      onCreateSession(session)
      setShowNewDialog(false)
      setForm({ session_id: '', user_id: '', display_name: '' })
      setAutoSessionId(false)
      setError(null)
    } catch (e: any) {
      const msg = e?.response?.data?.detail
      if (msg === 'session_id 已存在') {
        setError('session_id 已存在，请更换')
      } else {
        setError(msg ?? '创建失败')
      }
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (sessionId: string) => {
    if (!window.confirm(`确认删除会话「${sessionId}」？\n该操作不可恢复。`)) return
    setDeletingId(sessionId)
    try {
      await deleteAgentSession(sessionId)
      setSessions(prev => prev.filter(s => s.session_id !== sessionId))
      if (selectedSession?.session_id === sessionId) {
        onSelectSession(null)
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? '删除失败')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <aside className="w-72 flex-shrink-0 bg-canvas border-r border-line flex flex-col overflow-hidden relative">
      {/* 客服工作台入口：会话 / 工单 / Skill & MCP / Agent 配置 */}
      {pane && onSelectPane && (
        <div className="p-2 border-b border-line flex-shrink-0">
          <p className="px-2 pb-1 text-[10px] font-medium tracking-widest text-ink-subtle uppercase">
            客服工作台
          </p>
          <div className="space-y-0.5">
            {WORKBENCH_NAV.map((item) => {
              const Icon = item.icon
              const active = pane === item.key
              return (
                <button
                  key={item.key}
                  onClick={() => onSelectPane(item.key)}
                  className={cn(
                    'w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs border transition-colors',
                    active
                      ? 'bg-iris/15 text-info border-iris/25'
                      : 'text-ink-muted hover:bg-panel-2/60 hover:text-ink border-transparent',
                  )}
                >
                  <Icon size={14} className="flex-shrink-0" />
                  <span className="flex-1 text-left truncate">{item.label}</span>
                  {item.key === 'ticket' && openTickets != null && openTickets > 0 && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-warn/20 text-warn border border-warn/30">
                      {openTickets}
                    </span>
                  )}
                  {active && <ChevronRight size={12} className="opacity-60 flex-shrink-0" />}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* 头部 */}
      <div className="p-3 border-b border-line flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare size={16} className="text-info" />
          <span className="text-sm font-medium text-ink">会话列表</span>
          <span className="text-xs text-ink-subtle bg-panel-2 px-1.5 py-0.5 rounded-full">
            {sessions.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={loadSessions}
            title="刷新"
            className="p-1.5 rounded hover:bg-panel-2 text-ink-muted hover:text-ink transition-colors"
          >
            {loading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
          </button>
          <button
            onClick={() => setShowNewDialog(true)}
            title="新建会话"
            className="p-1.5 rounded hover:bg-iris/20 text-ink-muted hover:text-info transition-colors"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mx-3 mt-3 px-3 py-2 bg-bad/10 border border-bad/30 rounded-lg text-xs text-bad flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-bad hover:text-bad">
            <X size={12} />
          </button>
        </div>
      )}

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 && !loading ? (
          <div className="px-4 py-12 text-center text-ink-subtle">
            <MessageSquare size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm mb-1">暂无 Agent 会话</p>
            <p className="text-xs text-ink-subtle">点击右上角 + 创建新会话</p>
          </div>
        ) : (
          sessions.map((session) => (
            <SessionItem
              key={session.session_id}
              session={session}
              isSelected={selectedSession?.session_id === session.session_id}
              onClick={() => onSelectSession(session)}
              onDelete={() => handleDelete(session.session_id)}
              onOpenTickets={onOpenSessionTickets ? () => onOpenSessionTickets(session.session_id) : undefined}
              deleting={deletingId === session.session_id}
            />
          ))
        )}
      </div>

      {/* 新建会话弹窗 */}
      {showNewDialog && (
        <div className="absolute inset-0 z-50 bg-canvas/95 backdrop-blur flex flex-col animate-fade-in">
          <div className="p-4 border-b border-line flex items-center justify-between">
            <h3 className="text-sm font-medium text-ink">新建 Agent 会话</h3>
            <button onClick={() => setShowNewDialog(false)} className="text-ink-muted hover:text-ink">
              <X size={18} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* session_id */}
            <div>
              <label className="block text-xs text-ink-muted mb-1.5 flex items-center gap-1">
                <Hash size={12} />
                会话 ID <span className="text-bad">*</span>
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={form.session_id}
                  onChange={(e) => setForm(f => ({ ...f, session_id: e.target.value }))}
                  disabled={autoSessionId}
                  placeholder="例如：agent-12345"
                  className="flex-1 min-w-0 px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-sm text-ink placeholder-ink-subtle focus:outline-none focus:border-iris/50 disabled:opacity-50"
                />
                <button
                  onClick={() => {
                    setAutoSessionId(v => !v)
                    if (!autoSessionId) {
                      setForm(f => ({ ...f, session_id: generateSessionId() }))
                    }
                  }}
                  className={cn(
                    'px-2.5 py-2 rounded-lg text-xs border transition-colors',
                    autoSessionId
                      ? 'bg-iris/20 border-iris/40 text-info'
                      : 'bg-panel-2 border-line-strong text-ink-muted hover:text-ink',
                  )}
                  title={autoSessionId ? '使用手动输入' : '自动生成 session_id'}
                >
                  自动
                </button>
              </div>
            </div>
            {/* user_id */}
            <div>
              <label className="block text-xs text-ink-muted mb-1.5 flex items-center gap-1">
                <User size={12} />
                用户 ID
              </label>
              <input
                type="text"
                value={form.user_id}
                onChange={(e) => setForm(f => ({ ...f, user_id: e.target.value }))}
                placeholder="选填，例如：user-001"
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-sm text-ink placeholder-ink-subtle focus:outline-none focus:border-iris/50"
              />
            </div>
            {/* display_name */}
            <div>
              <label className="block text-xs text-ink-muted mb-1.5 flex items-center gap-1">
                <User size={12} />
                显示名称
              </label>
              <input
                type="text"
                value={form.display_name}
                onChange={(e) => setForm(f => ({ ...f, display_name: e.target.value }))}
                placeholder="选填，例如：张三"
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-sm text-ink placeholder-ink-subtle focus:outline-none focus:border-iris/50"
              />
              <p className="mt-1 text-[11px] text-ink-subtle">未填写则自动生成：Agent · {form.user_id || 'anonymous'}</p>
            </div>
          </div>
          <div className="p-4 border-t border-line flex justify-end gap-2 flex-shrink-0">
            <button
              onClick={() => setShowNewDialog(false)}
              className="px-3 py-1.5 text-sm text-ink-muted hover:text-ink transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleCreate}
              disabled={creating || (!autoSessionId && !form.session_id.trim())}
              className="px-4 py-1.5 text-sm bg-iris hover:bg-iris disabled:opacity-50 disabled:cursor-not-allowed text-ink rounded-lg transition-colors flex items-center gap-1.5"
            >
              {creating && <Loader2 size={14} className="animate-spin" />}
              创建会话
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}

function SessionItem({
  session,
  isSelected,
  onClick,
  onDelete,
  onOpenTickets,
  deleting,
}: {
  session: AgentSessionData
  isSelected: boolean
  onClick: () => void
  onDelete: () => void
  onOpenTickets?: () => void
  deleting: boolean
}) {
  const name = session.display_name || `Agent · ${session.user_id || 'anonymous'}`
  return (
    <div
      className={cn(
        'mx-2 my-0.5 px-3 py-2.5 rounded-lg cursor-pointer transition-all group',
        isSelected
          ? 'bg-line border border-iris/30'
          : 'hover:bg-panel-2/60 border border-transparent',
      )}
      onClick={onClick}
    >
      <div className="flex items-start gap-2.5">
        {/* 头像 */}
        <div className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center text-ink text-xs font-medium flex-shrink-0',
          isSelected
            ? 'bg-gradient-to-br from-iris to-iris'
            : 'bg-gradient-to-br from-panel-2 to-panel-2',
        )}>
          {name.charAt(0).toUpperCase()}
        </div>
        {/* 信息 */}
        <div className="flex-1 min-w-0 text-left">
          <div className="flex items-center gap-1.5">
            <span className={cn(
              'text-sm font-medium truncate',
              isSelected ? 'text-ink' : 'text-ink',
            )}>
              {truncate(name, 18)}
            </span>
          </div>
          <p className="text-xs text-ink-subtle truncate mt-0.5">
            {truncate(session.last_message || '暂无消息', 28)}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[11px] text-ink-subtle flex items-center gap-0.5">
              <Hash size={10} />
              {truncate(session.session_id, 12)}
            </span>
            {session.user_id && (
              <span className="text-[11px] text-ink-subtle flex items-center gap-0.5">
                <User size={10} />
                {session.user_id}
              </span>
            )}
            <span className="text-[11px] text-ink-subtle ml-auto flex items-center gap-0.5">
              <Clock size={10} />
              {session.updated_at ? formatTime(Math.floor(new Date(session.updated_at).getTime() / 1000)) : '未知'}
            </span>
          </div>
        </div>
        {/* 本会话工单 / 删除 */}
        {onOpenTickets && (
          <button
            onClick={(e) => { e.stopPropagation(); onOpenTickets() }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-warn/20 text-ink-subtle hover:text-warn transition-all flex-shrink-0"
            title="查看本会话工单"
          >
            <LifeBuoy size={13} />
          </button>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          disabled={deleting}
          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-bad/20 text-ink-subtle hover:text-bad transition-all flex-shrink-0"
          title="删除会话"
        >
          {deleting ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <Trash2 size={13} />
          )}
        </button>
      </div>
      {session.message_count > 0 && (
        <div className="mt-1.5 flex items-center gap-1">
          <span className="text-[11px] text-ink-subtle bg-panel px-1.5 py-0.5 rounded">
            {session.message_count} 轮对话
          </span>
        </div>
      )}
    </div>
  )
}
