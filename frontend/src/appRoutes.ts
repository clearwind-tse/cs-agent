export type ViewMode =
  | 'overview'
  | 'studio'
  | 'chat'
  | 'search'
  | 'ai'
  | 'agent'
  | 'admin'
  | 'custom'
  | 'extractor'
  | 'quiz'
  | 'training'
  | 'settings'

/**
 * 智能客服 Agent 工作台的子页面。
 * 原来散在「后台管理」里的 Agent 配置 / Skill & MCP / 工单，统一收进 Agent 视图，
 * 用 URL 子路径表达，保证刷新和分享链接都能落到同一页。
 */
export type AgentPane = 'chat' | 'ticket' | 'skill' | 'config'

/**
 * AI 创作的子页面。
 *
 * 这一组是从 picsetai 那类「商品图生产」产品复刻过来的能力，
 * 与本项目的客服链路无关，因此单独成一个工作区，用 URL 子路径表达，
 * 保证刷新、分享、回退都能落到同一个功能。
 */
export type StudioPane = 'home' | 'set' | 'style' | 'sku' | 'outfit' | 'retouch' | 'canvas' | 'assets' | 'endpoints'

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

const STUDIO_PANE_PATHS: Record<StudioPane, string> = {
  home: '/studio',
  set: '/studio/set',
  style: '/studio/style',
  sku: '/studio/sku',
  outfit: '/studio/outfit',
  retouch: '/studio/retouch',
  canvas: '/studio/canvas',
  assets: '/studio/assets',
  endpoints: '/studio/endpoints',
}

const PATH_TO_STUDIO_PANE: Record<string, StudioPane> = {
  '/studio': 'home',
  '/studio/set': 'set',
  '/studio/style': 'style',
  '/studio/sku': 'sku',
  '/studio/outfit': 'outfit',
  '/studio/retouch': 'retouch',
  '/studio/canvas': 'canvas',
  '/studio/assets': 'assets',
  '/studio/endpoints': 'endpoints',
}

export const buildStudioPath = (pane: StudioPane): string => STUDIO_PANE_PATHS[pane]

export const getStudioPaneFromPath = (pathname: string): StudioPane => {
  const normalized = pathname.replace(/\/+$/, '') || '/'
  return PATH_TO_STUDIO_PANE[normalized] ?? 'home'
}

const VIEW_PATHS: Record<Exclude<ViewMode, 'chat'>, string> = {
  overview: '/overview',
  studio: '/studio',
  search: '/search',
  ai: '/ai',
  agent: '/agent',
  admin: '/admin',
  custom: '/custom',
  extractor: '/extractor',
  quiz: '/quiz',
  training: '/training',
  settings: '/settings',
}

export const getViewModeFromPath = (pathname: string): ViewMode => {
  const normalized = pathname.replace(/\/+$/, '') || '/'

  // 质检已并入「后台管理」，旧深链 /qc 别名到 admin，避免历史链接 404
  if (normalized === '/qc') {
    return 'admin'
  }

  // 导出数据已合并进「训练数据管理」，旧深链 /export 落到 training 视图
  if (normalized === '/export') {
    return 'training'
  }

  // /agent 及其子页面（/agent/ticket 等）都属于 Agent 视图
  if (normalized === '/agent' || normalized.startsWith('/agent/')) {
    return 'agent'
  }

  // /studio 及其子页面（/studio/set 等）都属于 AI 创作视图
  if (normalized === '/studio' || normalized.startsWith('/studio/')) {
    return 'studio'
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
