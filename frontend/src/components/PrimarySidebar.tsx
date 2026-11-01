import { MessageCircle, Gauge, Edit3, Sparkles, Search, User, LogOut, Lightbulb, ClipboardList, MessageSquare, GraduationCap } from 'lucide-react'
import { useState } from 'react'
import { cn } from '../utils'
import { useAuth } from '../contexts/AuthContext'

interface PrimarySidebarProps {
  currentView: string
  onOpenChat: () => void
  onOpenSearch: () => void
  onOpenAI: () => void
  onOpenAdmin?: () => void
  onOpenCustom?: () => void
  onOpenExtractor?: () => void
  onOpenQuiz?: () => void
  onOpenAgent?: () => void
  onOpenTraining?: () => void
  onLoginClick?: () => void
}

export default function PrimarySidebar(props: PrimarySidebarProps) {
  const { user, isAuthenticated, logout } = useAuth()
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const NavButton = ({ 
    icon: Icon, 
    label, 
    active, 
    onClick 
  }: { 
    icon: any, 
    label: string, 
    active: boolean, 
    onClick?: () => void 
  }) => (
    <button
      onClick={onClick}
      className={cn(
        "relative w-12 h-12 flex items-center justify-center rounded-xl transition-all group",
        active 
          ? "bg-accent-primary/20 text-accent-primary" 
          : "text-gray-400 hover:bg-dark-700/50 hover:text-gray-200"
      )}
      title={label}
    >
      {active && (
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-accent-primary rounded-r-md" />
      )}
      <Icon size={24} strokeWidth={active ? 2.5 : 2} />
    </button>
  )

  return (
    <nav className="w-20 h-full flex-shrink-0 bg-[#1e1e20] border-r border-dark-600 flex flex-col items-center py-6 gap-6 z-20">
      {/* Logo */}
      <div className="w-12 h-12 rounded-full bg-gradient-to-br from-accent-primary to-accent-secondary flex items-center justify-center shadow-lg shadow-accent-primary/20 flex-shrink-0 mb-2">
        <MessageCircle size={28} className="text-white" />
      </div>

      {/* Nav Actions */}
      <div className="flex-1 flex flex-col items-center gap-3 w-full">
        <NavButton 
          icon={MessageCircle} 
          label="会话列表" 
          active={props.currentView === 'chat'} 
          onClick={props.onOpenChat} 
        />
        {props.onOpenAdmin && (
          <NavButton 
            icon={Gauge} 
            label="数据质检中心"
            active={props.currentView === 'admin'} 
            onClick={props.onOpenAdmin} 
          />
        )}
        {props.onOpenCustom && (
          <NavButton 
            icon={Edit3} 
            label="自定义数据" 
            active={props.currentView === 'custom'} 
            onClick={props.onOpenCustom} 
          />
        )}
        {props.onOpenExtractor && (
          <NavButton 
            icon={Lightbulb} 
            label="知识提炼" 
            active={props.currentView === 'extractor'} 
            onClick={props.onOpenExtractor} 
          />
        )}
        {props.onOpenQuiz && (
          <NavButton 
            icon={ClipboardList} 
            label="AI 考核" 
            active={props.currentView === 'quiz'} 
            onClick={props.onOpenQuiz} 
          />
        )}
        <NavButton
          icon={Sparkles}
          label="AI 问答"
          active={props.currentView === 'ai'}
          onClick={props.onOpenAI}
        />
        {props.onOpenAgent && (
          <NavButton
            icon={MessageSquare}
            label="智能客服 Agent"
            active={props.currentView === 'agent'}
            onClick={props.onOpenAgent}
          />
        )}
        {props.onOpenTraining && (
          <NavButton
            icon={GraduationCap}
            label="训练数据管理"
            active={props.currentView === 'training'}
            onClick={props.onOpenTraining}
          />
        )}
      </div>

      {/* Bottom Actions */}
      <div className="flex flex-col items-center gap-3 w-full pb-4">
        <NavButton 
          icon={Search} 
          label="全局搜索" 
          active={props.currentView === 'search'} 
          onClick={props.onOpenSearch} 
        />

        {/* User Profile / Login */}
        <div className="relative mt-2">
          {isAuthenticated ? (
            <>
              <button
                onClick={() => setShowProfileMenu(!showProfileMenu)}
                className="w-12 h-12 flex flex-col items-center justify-center rounded-xl hover:bg-dark-700/50 transition-colors tooltip group relative"
                title={user?.nickname || undefined}
              >
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center">
                  <span className="text-white text-xs font-bold">
                    {(user?.nickname || user?.username || 'U').charAt(0).toUpperCase()}
                  </span>
                </div>
              </button>

              {/* Profile Dropdown */}
              {showProfileMenu && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setShowProfileMenu(false)} />
                  <div className="absolute left-full ml-4 bottom-0 w-48 bg-dark-800 border border-dark-600 rounded-xl shadow-xl overflow-hidden animate-in fade-in slide-in-from-left-2 z-50">
                    <div className="px-4 py-3 border-b border-dark-700">
                      <p className="text-sm font-medium text-white max-w-[160px] truncate">{user?.nickname}</p>
                      <p className="text-xs text-gray-500 max-w-[160px] truncate">@{user?.username}</p>
                      <p className="text-[10px] mt-1 text-accent-primary uppercase tracking-wider">{user?.role}</p>
                    </div>
                    <div className="p-1">
                      <button 
                        onClick={() => {
                          logout()
                          setShowProfileMenu(false)
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-dark-700 rounded-lg transition-colors"
                      >
                        <LogOut size={16} /> 退出登录
                      </button>
                    </div>
                  </div>
                </>
              )}
            </>
          ) : (
            <button
              onClick={props.onLoginClick}
              className="w-12 h-12 flex items-center justify-center rounded-xl bg-dark-800 text-gray-400 hover:text-accent-primary hover:bg-dark-700 transition-all border border-dark-600/50 hover:border-accent-primary/20"
              title="登录"
            >
              <User size={20} />
            </button>
          )}
        </div>
      </div>
    </nav>
  )
}
