import React, { useReducer, useState } from 'react'
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import PrimarySidebar from './components/PrimarySidebar'
import ChatView from './components/ChatView'
import SearchView from './components/SearchView'
import AIChat from './components/AIChat'
import ExportView from './components/ExportView'
import AdminView from './components/AdminView'
import AgentWorkbench from './components/AgentWorkbench'
import { type AgentSessionData } from './api'
import CustomDataView from './components/CustomDataView'
import ExtractorView from './components/ExtractorView'
import QuizView from './components/QuizView'
import LoginPage from './components/LoginPage'
import ToastContainer from './components/Toast'
import { ToastProvider, useToast } from './contexts/ToastContext'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { getSession } from './api'
import { Session } from './types'
import { reduceChatNavigationState } from './components/chatNavigation'
import { getAppMainLayoutClasses } from './appLayout'
import {
  buildAgentPath,
  buildChatPath,
  buildViewPath,
  getAgentPaneFromPath,
  getChatRouteState,
  getViewModeFromPath,
  type AgentPane,
  type ViewMode,
} from './appRoutes'

function AppContent() {
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
      <div className="flex h-screen w-screen overflow-hidden bg-dark-950">
        {/* 左侧主导航 - Primary Sidebar */}
        <PrimarySidebar
          currentView={viewMode}
          onOpenChat={() => openView('chat')}
          onOpenSearch={() => openView('search')}
          onOpenAI={() => openView('ai')}
          onOpenExport={() => openView('export')}
          onOpenAdmin={() => openView('admin')}
          onOpenCustom={() => openView('custom')}
          onOpenExtractor={() => openView('extractor')}
          onOpenQuiz={() => openView('quiz')}
          onOpenAgent={() => openView('agent')}
          onLoginClick={() => setShowLogin(true)}
        />

        {/* 会话列表 - Secondary Sidebar (仅在聊天视图显示) */}
        {viewMode === 'chat' && (
          <div className="w-80 flex-shrink-0">
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
          ) : viewMode === 'export' ? (
            <ExportView onClose={() => openView('chat')} />
          ) : viewMode === 'admin' ? (
            <AdminView onClose={() => openView('chat')} />
          ) : viewMode === 'custom' ? (
            <CustomDataView />
          ) : viewMode === 'extractor' ? (
            <ExtractorView />
          ) : viewMode === 'quiz' ? (
            <QuizView onClose={() => openView('chat')} />
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
            <EmptyState />
          )}
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

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
      {/* Background Decorative Element */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-accent-primary/5 rounded-full blur-[120px] pointer-events-none"></div>
      
      <div className="text-center animate-fade-in relative z-10 max-w-lg">
        <div className="w-24 h-24 mx-auto mb-8 rounded-3xl bg-dark-700/50 flex items-center justify-center shadow-2xl border border-dark-600/50">
          <svg className="w-12 h-12 text-accent-primary/80" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
        </div>
        <h2 className="text-4xl font-extrabold tracking-tighter text-white mb-3">Agent CS Playbook</h2>
        <h3 className="text-xl text-accent-primary font-medium mb-6">数据质检中心 · 智能客服 Agent 工作台</h3>
        <p className="text-gray-500 text-base leading-relaxed mb-10 font-light">
          ← 点击左侧会话查看聊天记录
        </p>
      </div>
    </div>
  )
}

export default App
