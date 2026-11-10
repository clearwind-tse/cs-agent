import React, { useReducer, useState } from 'react'
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import PrimarySidebar from './components/PrimarySidebar'
import AppContextBar from './components/AppContextBar'
import ChatView from './components/ChatView'
import SearchView from './components/SearchView'
import AIChat from './components/AIChat'
import AdminView from './components/AdminView'
import AgentWorkbench from './components/AgentWorkbench'
import { type AgentSessionData } from './api'
import CustomDataView from './components/CustomDataView'
import ExtractorView from './components/ExtractorView'
import QuizView from './components/QuizView'
import TrainingView from './components/TrainingView'
import GlobalOverviewView, { type OverviewTab } from './components/GlobalOverviewView'
import StudioWorkbench from './components/StudioWorkbench'
import SettingsView from './components/SettingsView'
import LoginPage from './components/LoginPage'
import ToastContainer from './components/Toast'
import { ToastProvider, useToast } from './contexts/ToastContext'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { getSession } from './api'
import { Session } from './types'
import { reduceChatNavigationState } from './components/chatNavigation'
import { getAppMainLayoutClasses } from './appLayout'
import { OVERVIEW_ITEM, WORKSPACES, type NavItem } from './navigation'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { AuroraBackground } from './components/ui/AuroraBackground'
import {
  buildAgentPath,
  buildChatPath,
  buildStudioPath,
  buildViewPath,
  getAgentPaneFromPath,
  getChatRouteState,
  getStudioPaneFromPath,
  getViewModeFromPath,
  type AgentPane,
  type StudioPane,
  type ViewMode,
} from './appRoutes'

function AppContent() {
  const reduceMotion = useReducedMotion()
  const layoutClasses = getAppMainLayoutClasses()
  const location = useLocation()
  const navigate = useNavigate()
  const [{ selectedSession, targetMessageId }, dispatchChatNavigation] = useReducer(
    reduceChatNavigationState,
    {
      selectedSession: null as Session | null,
      targetMessageId: null as number | null,
    },
  )
  const [showLogin, setShowLogin] = useState(false)
  const { showToast } = useToast()
  const { isAuthenticated, isLoading } = useAuth()
  const [agentSession, setAgentSession] = useState<AgentSessionData | null>(null)
  const viewMode = React.useMemo(() => getViewModeFromPath(location.pathname), [location.pathname])
  // Agent 工作台的子页面（会话 / 工单 / Skill & MCP / Agent 配置），由 URL 决定
  const agentPane = React.useMemo(() => getAgentPaneFromPath(location.pathname), [location.pathname])
  // AI 创作工作区的子页面（套图 / 风格 / SKU / …），同样由 URL 决定
  const studioPane = React.useMemo(() => getStudioPaneFromPath(location.pathname), [location.pathname])
  /** 当前视图的子页，供导航条与上下文条定位（Agent 与 AI 创作各有一套 pane 取值） */
  const activePane: AgentPane | StudioPane | null =
    viewMode === 'agent' ? agentPane : viewMode === 'studio' ? studioPane : null
  /** 全局总览的两个视角：默认落在「待办」，统计作为第二个 Tab */
  const overviewTab: OverviewTab = React.useMemo(
    () => (new URLSearchParams(location.search).get('tab') === 'stats' ? 'stats' : 'todo'),
    [location.search],
  )
  const chatRouteState = React.useMemo(
    () => getChatRouteState(location.pathname, location.search),
    [location.pathname, location.search],
  )

  React.useEffect(() => {
    const handleUnauthorized = () => {
      showToast('登录已过期，请重新登录', 'error')
      setShowLogin(true)
    }
    window.addEventListener('auth:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('auth:unauthorized', handleUnauthorized)
  }, [showToast])

  // 未登录时强制弹出登录页
  const loginVisible = showLogin || (!isAuthenticated && !isLoading)

  React.useEffect(() => {
    if (viewMode !== 'chat' || !chatRouteState.sessionId) {
      return
    }

    if (selectedSession?.session_id === chatRouteState.sessionId) {
      if (chatRouteState.messageId != null && targetMessageId !== chatRouteState.messageId) {
        dispatchChatNavigation({
          type: 'jump-to-message',
          session: selectedSession,
          messageId: chatRouteState.messageId,
        })
      }
      return
    }

    let cancelled = false

    ;(async () => {
      try {
        const session = await getSession(chatRouteState.sessionId!)
        if (cancelled) return

        if (chatRouteState.messageId != null) {
          dispatchChatNavigation({
            type: 'jump-to-message',
            session,
            messageId: chatRouteState.messageId,
          })
        } else {
          dispatchChatNavigation({ type: 'select-session', session })
        }
      } catch (error) {
        console.error('Failed to restore chat route:', error)
        if (cancelled) return
        showToast('会话加载失败，已返回聊天首页', 'error')
        navigate(buildChatPath(), { replace: true })
      }
    })()

    return () => {
      cancelled = true
    }
  }, [
    viewMode,
    chatRouteState.sessionId,
    chatRouteState.messageId,
    selectedSession,
    targetMessageId,
    navigate,
    showToast,
  ])

  const openView = React.useCallback((nextView: ViewMode) => {
    navigate(buildViewPath(nextView, selectedSession?.session_id))
  }, [navigate, selectedSession?.session_id])

  /** 导航面板 / 上下文条的统一出口：会话记录保留当前选中会话，其余走精确路径 */
  const handleNavigateItem = React.useCallback((item: NavItem) => {
    if (item.view === 'chat') {
      openView('chat')
      return
    }
    navigate(item.path)
  }, [navigate, openView])

  // 搜索结果跳转到具体消息
  const handleJumpToMessage = async (sessionId: string, messageId?: number) => {
    try {
      // 获取 Session 对象
      const session = await getSession(sessionId)
      dispatchChatNavigation({ type: 'jump-to-message', session, messageId })
      navigate(buildChatPath(sessionId, messageId ?? null))
    } catch (error) {
      console.error('Failed to jump to message:', error)
      // 降级：至少切换到聊天视图
      navigate(buildChatPath(sessionId))
    }
  }

  return (
    <>
      <div className="relative flex h-[100dvh] w-screen overflow-hidden bg-canvas">
        {/* 极光氛围层：纯 CSS 光晕，位于所有内容之下 */}
        <AuroraBackground variant="subtle" className="absolute inset-0" />

        {/* 左侧主导航 - Primary Sidebar */}
        <PrimarySidebar
          currentView={viewMode}
          currentPane={activePane}
          onNavigate={(path) => navigate(path)}
          onOpenChat={() => openView('chat')}
          onOpenSearch={() => openView('search')}
          onOpenAI={() => openView('ai')}
          onOpenAdmin={() => openView('admin')}
          onOpenCustom={() => openView('custom')}
          onOpenExtractor={() => openView('extractor')}
          onOpenQuiz={() => openView('quiz')}
          onOpenTraining={() => openView('training')}
          onOpenAgent={() => openView('agent')}
          onLoginClick={() => setShowLogin(true)}
        />

        {/* 会话列表 - Secondary Sidebar (仅在聊天视图显示) */}
        {viewMode === 'chat' && (
          <div className="hidden md:block md:w-64 xl:w-80 flex-shrink-0">
            <Sidebar
              selectedSession={selectedSession}
              onSelectSession={(session) => {
                dispatchChatNavigation({ type: 'select-session', session })
                navigate(buildChatPath(session.session_id))
              }}
            />
          </div>
        )}

        {/* 主内容区 - 防止溢出 */}
        <main className={layoutClasses.main}>
          {/* 统一上下文条：位置 / 链路步骤 / 跨链路关联，不随视图转场重建 */}
          <AppContextBar view={viewMode} pane={activePane} onNavigate={handleNavigateItem} />

          {/* 只做透明度转场：transform / filter 会创建 containing block，破坏视图内的 fixed 弹窗 */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={viewMode}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduceMotion ? 0 : 0.22, ease: 'easeOut' }}
              className="flex flex-1 min-h-0 flex-col"
            >
          {viewMode === 'search' ? (
            <SearchView
              onClose={() => openView('chat')}
              onJumpToMessage={handleJumpToMessage}
            />
          ) : viewMode === 'ai' ? (
            <AIChat
              sessionId={selectedSession?.session_id}
              onClose={() => openView('chat')}
              onJumpToMessage={handleJumpToMessage}
            />
          ) : viewMode === 'agent' ? (
            <AgentWorkbench
              pane={agentPane}
              onPaneChange={(next: AgentPane) => navigate(buildAgentPath(next))}
              session={agentSession}
              onSelectSession={(s) => setAgentSession(s)}
              onCreateSession={(s) => setAgentSession(s)}
              onClose={() => openView('chat')}
              onJumpToMessage={handleJumpToMessage}
            />
          ) : viewMode === 'admin' ? (
            <AdminView onClose={() => openView('chat')} />
          ) : viewMode === 'custom' ? (
            <CustomDataView />
          ) : viewMode === 'extractor' ? (
            <ExtractorView />
          ) : viewMode === 'quiz' ? (
            <QuizView onClose={() => openView('chat')} />
          ) : viewMode === 'training' ? (
            <TrainingView />
          ) : viewMode === 'studio' ? (
            <StudioWorkbench
              pane={studioPane}
              onPaneChange={(next: StudioPane) => navigate(buildStudioPath(next))}
            />
          ) : viewMode === 'settings' ? (
            <SettingsView />
          ) : viewMode === 'overview' ? (
            <GlobalOverviewView
              tab={overviewTab}
              onTabChange={(next) => navigate(next === 'stats' ? '/overview?tab=stats' : '/overview')}
              onNavigate={handleNavigateItem}
            />
          ) : selectedSession ? (
            <ChatView
              session={selectedSession}
              targetMessageId={targetMessageId}
              onTargetReached={() => {
                dispatchChatNavigation({ type: 'target-reached' })
                navigate(buildChatPath(selectedSession.session_id), { replace: true })
              }}
            />
          ) : (
            <EmptyState onNavigate={(path) => navigate(path)} />
          )}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      {loginVisible && (
        <LoginPage
          onClose={() => setShowLogin(false)}
          onSuccess={() => setShowLogin(false)}
          canClose={isAuthenticated}
        />
      )}
    </>
  )
}

function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppContent />
          <ToastContainer />
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  )
}

function EmptyState({ onNavigate }: { onNavigate: (path: string) => void }) {
  /** 空状态不再只说「点左侧」，直接给出三条业务链路的入口 */
  const entries = WORKSPACES.map((workspace) => ({
    workspace,
    target: workspace.items.find((item) => item.view !== 'chat') ?? workspace.items[0],
  }))
  const OverviewIcon = OVERVIEW_ITEM.icon

  return (
    <div className="flex-1 flex flex-col items-center justify-center relative overflow-hidden px-6">
      <div className="text-center relative z-10 max-w-xl">
        <div className="font-mono text-[11px] uppercase tracking-[0.28em] text-ink-subtle mb-7">
          AiWxChat / Agent CS Playbook
        </div>
        <div className="w-20 h-20 mx-auto mb-8 rounded-3xl glass flex items-center justify-center shadow-glow">
          <svg className="w-10 h-10 text-mint" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
        </div>
        <h2 className="font-display text-4xl md:text-5xl font-extrabold tracking-[-0.04em] text-ink mb-4">
          数据，<span className="aurora-text">在光里流动。</span>
        </h2>
        <p className="text-ink-muted text-[15px] leading-[1.9] mb-10">
          在线服务 · 数据治理 · 模型优化 · AI 创作<br />
          从聊天记录到 SFT / DPO 训练数据，再到商品图生产。
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => onNavigate(OVERVIEW_ITEM.path)}
            title={OVERVIEW_ITEM.desc}
            className="glass inline-flex items-center gap-2 rounded-pill border border-iris/30 px-4 py-2 text-xs text-ink hover:border-iris/60 transition-colors"
          >
            <OverviewIcon size={14} /> 全局总览
          </button>
          {entries.map(({ workspace, target }) => {
            const Icon = workspace.icon
            return (
              <button
                key={workspace.id}
                type="button"
                onClick={() => onNavigate(target.path)}
                title={`${workspace.desc} · 进入${target.label}`}
                className="glass inline-flex items-center gap-2 rounded-pill px-4 py-2 text-xs text-ink-muted hover:text-ink transition-colors"
              >
                <Icon size={14} />
                <span className="font-mono text-[10px] text-ink-subtle">{workspace.index}</span>
                {workspace.label}
              </button>
            )
          })}
        </div>
        <p className="font-mono text-xs text-ink-subtle mt-8">← 左侧会话列表可直接打开聊天记录</p>
      </div>
    </div>
  )
}

export default App
