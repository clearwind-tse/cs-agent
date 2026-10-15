import { useState, useEffect, useCallback } from 'react'
import { Search, MessageCircle } from 'lucide-react'
import { getSessions } from '../api'
import { Session } from '../types'
import { cn, formatTime, truncate, getAvatarColor, getInitials } from '../utils'
import { sessionLabel } from '../sessionDisplay'

interface SidebarProps {
  selectedSession: Session | null
  onSelectSession: (session: Session) => void
}

export default function Sidebar({ selectedSession, onSelectSession }: SidebarProps) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)

  const loadSessions = useCallback(async (reset = false) => {
    try {
      setLoading(true)
      const currentPage = reset ? 1 : page
      const result = await getSessions({
        page: currentPage,
        page_size: 50,
        search: searchQuery || undefined,
        session_type: 'private',
        exclude_chatroom: true,
      })

      if (reset) {
        setSessions(result.items)
        setPage(1)
      } else {
        setSessions(prev => [...prev, ...result.items])
      }
      setHasMore(result.has_more)
    } catch (error) {
      console.error('Failed to load sessions:', error)
    } finally {
      setLoading(false)
    }
  }, [page, searchQuery])

  useEffect(() => {
    loadSessions(true)
  }, [searchQuery])

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.target as HTMLDivElement
    if (
      hasMore &&
      !loading &&
      target.scrollHeight - target.scrollTop <= target.clientHeight + 100
    ) {
      setPage(prev => prev + 1)
      loadSessions()
    }
  }

  return (
    <aside className="w-full h-full bg-dark-900 border-r border-dark-600 flex flex-col overflow-hidden">
      {/* 顶部标题和搜索 */}
      <div className="p-4 border-b border-dark-600">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-lg font-semibold bg-gradient-to-r from-accent-primary to-accent-secondary bg-clip-text text-transparent">
            会话列表
          </h1>
        </div>

        {/* 搜索框 */}
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="搜索会话..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary/50 transition-colors"
          />
        </div>
      </div>

      {/* 会话列表 */}
      <div
        className="flex-1 overflow-y-auto"
        onScroll={handleScroll}
      >
        {sessions.length === 0 && !loading ? (
          <div className="p-8 text-center text-gray-500">
            <MessageCircle size={32} className="mx-auto mb-2 opacity-50" />
            <p className="text-sm">暂无会话</p>
          </div>
        ) : (
          <div className="py-2">
            {sessions.map((session, index) => (
              <SessionItem
                key={session.session_id}
                session={session}
                isSelected={selectedSession?.session_id === session.session_id}
                onClick={() => onSelectSession(session)}
                style={{ animationDelay: `${index * 20}ms` }}
              />
            ))}
            {loading && (
              <div className="p-4 text-center">
                <div className="inline-block w-5 h-5 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin" />
              </div>
            )}
          </div>
        )}
      </div>

      {/* 底部统计 */}
      <div className="p-3 border-t border-dark-600 text-xs text-gray-500 text-center">
        共 {sessions.length} 个会话
      </div>
    </aside>
  )
}

interface SessionItemProps {
  session: Session
  isSelected: boolean
  onClick: () => void
  style?: React.CSSProperties
}

function SessionItem({ session, isSelected, onClick, style }: SessionItemProps) {
  const displayName = sessionLabel(session.display_name, session.session_id)
  const avatarColor = getAvatarColor(displayName)

  return (
    <button
      onClick={onClick}
      style={style}
      className={cn(
        'w-full px-3 py-3 flex items-center gap-3 transition-all animate-fade-in',
        isSelected
          ? 'bg-dark-600'
          : 'hover:bg-dark-700/50'
      )}
    >
      {/* 头像 */}
      <div className={cn(
        'w-10 h-10 rounded-full flex items-center justify-center text-white font-medium bg-gradient-to-br flex-shrink-0',
        avatarColor
      )}>
        {getInitials(displayName)}
      </div>

      {/* 会话信息 */}
      <div className="flex-1 min-w-0 text-left">
        <div className="flex items-center justify-between">
          <span className={cn(
            'font-medium truncate',
            isSelected ? 'text-white' : 'text-gray-200'
          )}>
            {truncate(displayName, 15)}
          </span>
          {session.last_time && (
            <span className="text-xs text-gray-500 flex-shrink-0 ml-2">
              {formatTime(session.last_time)}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between mt-0.5">
          <p className="text-sm text-gray-500 truncate">
            {truncate(session.last_message, 20) || '暂无消息'}
          </p>
          <span className="text-xs text-gray-600 flex-shrink-0 ml-2">
            {session.message_count}条
          </span>
        </div>
      </div>
    </button>
  )
}
