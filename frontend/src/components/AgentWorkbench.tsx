// -*- coding: utf-8 -*-
/**
 * AgentWorkbench — 智能客服 Agent 工作台
 *
 * 把原来放在「数据质检中心」里的 Agent 配置 / Skill & MCP / 工单收进 Agent 视图，
 * 左侧会话列表变成「会话 + 四个工作台入口」，右侧按 AgentPane 切换内容：
 *
 *   /agent          → 会话对话（AgentChat）
 *   /agent/ticket   → 工单（可带 ?session 过滤，从某个会话一键跳过来）
 *   /agent/skill    → Skill & MCP
 *   /agent/config   → Agent 配置
 *
 * 设计取舍：
 * - pane 由 URL 决定（单一数据源），组件只负责「决定去哪」，不自己存当前页；
 * - 工单的会话过滤是视图态，放在本组件，切走时清空，避免下次进来还以为在过滤。
 */
import { useState } from 'react'
import { Bot, LifeBuoy, MessageSquare, Tag, X } from 'lucide-react'
import { cn } from '../utils'
import type { AgentPane } from '../appRoutes'
import type { AgentSessionData } from '../api'
import AgentChat from './AgentChat'
import AgentConfigView from './AgentConfigView'
import AgentSessionSidebar from './AgentSessionSidebar'
import SkillsTabView from './SkillsTabView'
import TicketView from './TicketView'

interface AgentWorkbenchProps {
  pane: AgentPane
  onPaneChange: (pane: AgentPane) => void
  session: AgentSessionData | null
  onSelectSession: (session: AgentSessionData | null) => void
  onCreateSession: (session: AgentSessionData | null) => void
  onClose: () => void
  onJumpToMessage: (sessionId: string, messageId?: number) => void
}

const PANE_META: Record<Exclude<AgentPane, 'chat'>, {
  title: string
  desc: string
  icon: typeof LifeBuoy
  iconCls: string
  boxCls: string
}> = {
  ticket: {
    title: '工单',
    desc: 'Agent 自动建单 · 人工审批挂起 · SLA 计时',
    icon: LifeBuoy,
    iconCls: 'text-amber-300',
    boxCls: 'bg-amber-500/15',
  },
  skill: {
    title: 'Skill & MCP',
    desc: '能力包与外部业务系统接入',
    icon: Tag,
    iconCls: 'text-cyan-300',
    boxCls: 'bg-cyan-500/15',
  },
  config: {
    title: 'Agent 配置',
    desc: '子 Agent 注册 · 意图路由 · 提示词',
    icon: Bot,
    iconCls: 'text-violet-300',
    boxCls: 'bg-violet-500/15',
  },
}

export default function AgentWorkbench({
  pane,
  onPaneChange,
  session,
  onSelectSession,
  onCreateSession,
  onClose,
  onJumpToMessage,
}: AgentWorkbenchProps) {
  /** 工单页的会话过滤（从会话列表某个会话点「工单」跳过来时生效） */
  const [ticketSessionId, setTicketSessionId] = useState<string | null>(null)

  const openPane = (next: AgentPane) => {
    // 直接点导航进工单 = 看全部；只有从具体会话跳过来才带过滤
    setTicketSessionId(null)
    onPaneChange(next)
  }

  const openSessionTickets = (sessionId: string) => {
    setTicketSessionId(sessionId)
    onPaneChange('ticket')
  }

  const handleSelectSession = (next: AgentSessionData | null) => {
    onSelectSession(next)
    // 点会话就是回来聊天，避免停在工单页看着一个不相关的会话
    if (pane !== 'chat') onPaneChange('chat')
  }

  if (pane === 'chat') {
    return (
      <div className="flex-1 flex overflow-hidden">
        <AgentSessionSidebar
          pane={pane}
          onSelectPane={openPane}
          onOpenSessionTickets={openSessionTickets}
          selectedSession={session}
          onSelectSession={handleSelectSession}
          onCreateSession={onCreateSession}
        />
        <AgentChat
          session={session}
          onClose={onClose}
          onJumpToMessage={onJumpToMessage}
          onOpenTickets={openSessionTickets}
        />
      </div>
    )
  }

  const meta = PANE_META[pane]
  const Icon = meta.icon

  return (
    <div className="flex-1 flex overflow-hidden">
      <AgentSessionSidebar
        pane={pane}
        onSelectPane={openPane}
        onOpenSessionTickets={openSessionTickets}
        selectedSession={session}
        onSelectSession={handleSelectSession}
        onCreateSession={onCreateSession}
      />

      <div className="flex-1 min-w-0 min-h-0 flex flex-col bg-dark-800">
        <header className="h-14 px-5 flex items-center justify-between border-b border-dark-600 flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0', meta.boxCls)}>
              <Icon size={16} className={meta.iconCls} />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-medium text-white leading-tight">{meta.title}</h2>
              <p className="text-[11px] text-gray-500 truncate">{meta.desc}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {pane === 'ticket' && ticketSessionId && (
              <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-[11px] text-amber-200">
                <MessageSquare size={11} />
                仅看会话 {ticketSessionId}
                <button
                  onClick={() => setTicketSessionId(null)}
                  className="text-amber-300/70 hover:text-amber-100"
                  title="清除会话过滤"
                >
                  <X size={11} />
                </button>
              </span>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-white transition-colors"
              title="返回聊天"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        <div className="flex-1 min-h-0 flex flex-col p-4">
          {pane === 'ticket' ? (
            <TicketView sessionFilter={ticketSessionId} />
          ) : pane === 'skill' ? (
            <SkillsTabView />
          ) : (
            <AgentConfigView />
          )}
        </div>
      </div>
    </div>
  )
}
