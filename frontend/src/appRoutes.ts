export type ViewMode =
  | 'chat'
  | 'search'
  | 'ai'
  | 'agent'
  | 'export'
  | 'admin'
  | 'custom'
  | 'extractor'
  | 'quiz'

/**
 * 智能客服 Agent 工作台的子页面。
 * 原来散在「后台管理」里的 Agent 配置 / Skill & MCP / 工单，统一收进 Agent 视图，
 * 用 URL 子路径表达，保证刷新和分享链接都能落到同一页。
 */
export type AgentPane = 'chat' | 'ticket' | 'skill' | 'config'

const AGENT_PANE_PATHS: Record<AgentPane, string> = {
  chat: '/agent',
  ticket: '/agent/ticket',
  skill: '/agent/skill',
  config: '/agent/config',
}

const PATH_TO_AGENT_PANE: Record<string, AgentPane> = {
  '/agent': 'chat',
  '/agent/ticket': 'ticket',
  '/agent/skill': 'skill',
  '/agent/config': 'config',
}

export const buildAgentPath = (pane: AgentPane): string => AGENT_PANE_PATHS[pane]

export const getAgentPaneFromPath = (pathname: string): AgentPane => {
  const normalized = pathname.replace(/\/+$/, '') || '/'
  return PATH_TO_AGENT_PANE[normalized] ?? 'chat'
}

const VIEW_PATHS: Record<Exclude<ViewMode, 'chat'>, string> = {
  search: '/search',
  ai: '/ai',
  agent: '/agent',
  export: '/export',
  admin: '/admin',
  custom: '/custom',
  extractor: '/extractor',
  quiz: '/quiz',
}

export const getViewModeFromPath = (pathname: string): ViewMode => {
  const normalized = pathname.replace(/\/+$/, '') || '/'

  // 质检已并入「后台管理」，旧深链 /qc 别名到 admin，避免历史链接 404
  if (normalized === '/qc') {
    return 'admin'
  }

  // /agent 及其子页面（/agent/ticket 等）都属于 Agent 视图
  if (normalized === '/agent' || normalized.startsWith('/agent/')) {
    return 'agent'
  }

  for (const [viewMode, path] of Object.entries(VIEW_PATHS)) {
    if (normalized === path) {
      return viewMode as Exclude<ViewMode, 'chat'>
    }
  }

  if (normalized === '/' || normalized === '/chat' || normalized.startsWith('/chat/')) {
    return 'chat'
  }

  return 'chat'
}

export const buildChatPath = (sessionId?: string | null, messageId?: number | null): string => {
  const basePath = sessionId ? `/chat/${encodeURIComponent(sessionId)}` : '/chat'

  if (messageId == null) {
    return basePath
  }

  return `${basePath}?messageId=${messageId}`
}

export const buildViewPath = (viewMode: ViewMode, sessionId?: string | null, messageId?: number | null): string => {
  if (viewMode === 'chat') {
    return buildChatPath(sessionId, messageId)
  }

  return VIEW_PATHS[viewMode]
}

export const getChatRouteState = (
  pathname: string,
  search: string,
): { sessionId: string | null; messageId: number | null } => {
  if (getViewModeFromPath(pathname) !== 'chat') {
    return { sessionId: null, messageId: null }
  }

  const match = pathname.match(/^\/chat\/([^/?#]+)/)
  const sessionId = match ? decodeURIComponent(match[1]) : null
  const rawMessageId = new URLSearchParams(search).get('messageId')
  const messageId = rawMessageId && /^\d+$/.test(rawMessageId) ? Number(rawMessageId) : null

  if (!sessionId) {
    return { sessionId: null, messageId: null }
  }

  return { sessionId, messageId }
}
