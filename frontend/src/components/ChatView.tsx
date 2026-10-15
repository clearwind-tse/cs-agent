import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Users, MoreVertical, ChevronUp, ArrowDown, Play, Square } from 'lucide-react'
import { getChatHistory, getMessageContext } from '../api'
import { Session, Message, MSG_TYPES } from '../types'
import { cn, formatTime, formatDateTime, getAvatarColor, getInitials, getMsgTypeLabel } from '../utils'
import { calculateTargetScrollTop, shouldAutoLoadMoreOnScroll } from './chatPositioning'
import { getHistoryRequestPage, prependUniqueMessages } from './chatHistoryPagination'
import { sessionLabel } from '../sessionDisplay'

interface ChatViewProps {
  session: Session
  targetMessageId?: number | null
  onTargetReached?: () => void
}

export default function ChatView({ session, targetMessageId, onTargetReached }: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [page, setPage] = useState(1)
  const containerRef = useRef<HTMLDivElement>(null)
  const [showScrollBottom, setShowScrollBottom] = useState(false)
  const [highlightId, setHighlightId] = useState<number | null>(null)
  const [isTargetPositioning, setIsTargetPositioning] = useState(false)
  // 用于追踪当前激活的会话ID，解决快速切换会话时的竞态问题
  const sessionRef = useRef(session.session_id)
  const highlightTimerRef = useRef<number | null>(null)

  useEffect(() => {
    sessionRef.current = session.session_id
  }, [session.session_id])

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) {
        window.clearTimeout(highlightTimerRef.current)
      }
    }
  }, [])

  const loadMessages = useCallback(async (reset = false, explicitPage?: number) => {
    // 保存发起请求时的 session_id
    const currentSessionId = session.session_id
    const { pageToLoad, nextPage } = explicitPage
      ? { pageToLoad: explicitPage, nextPage: explicitPage }
      : getHistoryRequestPage({ currentPage: page, reset })

    try {
      if (reset) {
        setLoading(true)
        setPage(1)
        setIsTargetPositioning(false)
      } else {
        setLoadingMore(true)
      }

      const result = await getChatHistory(currentSessionId, {
        page: pageToLoad,
        page_size: 50,
      })

      // 如果请求完成时，当前激活的 session_id 已经改变，则忽略该结果
      if (currentSessionId !== sessionRef.current) {
        return
      }

      if (reset) {
        setMessages(result.items)
        setPage(1)
      } else {
        // 加载更多时，新消息插入到前面
        setMessages(prev => prependUniqueMessages(prev, result.items))
        setPage(nextPage)
      }
      setHasMore(result.has_more)
    } catch (error) {
      // 即使出错也要检查是否是当前会话，避免错误提示显示在错误的会话中
      if (currentSessionId !== sessionRef.current) {
        return
      }
      console.error('Failed to load messages:', error)
    } finally {
      // 同样检查是否是当前会话
      if (currentSessionId === sessionRef.current) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [session.session_id, page])

  // 搜索跳转：加载目标消息上下文
  const loadMessageContext = useCallback(async (messageId: number) => {
    try {
      setLoading(true)
      setHighlightId(null)
      setIsTargetPositioning(true)
      const result = await getMessageContext(messageId)
      
      if (result.session_id !== sessionRef.current) return
      
      setMessages(result.items)
      setHasMore(true) // 上下文模式下允许继续加载前后消息
      setPage(1)
      
      // 渲染后精确滚动到目标消息并高亮
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const container = containerRef.current
          const el = document.getElementById(`msg-${messageId}`)

          if (container && el) {
            const scrollTop = calculateTargetScrollTop({
              containerHeight: container.clientHeight,
              contentHeight: container.scrollHeight,
              targetOffsetTop: el.offsetTop,
              targetHeight: el.clientHeight,
            })
            container.scrollTo({ top: scrollTop, behavior: 'auto' })
            setHighlightId(messageId)

            if (highlightTimerRef.current) {
              window.clearTimeout(highlightTimerRef.current)
            }
            highlightTimerRef.current = window.setTimeout(() => {
              setHighlightId(null)
            }, 3000)
          }

          requestAnimationFrame(() => {
            setIsTargetPositioning(false)
            onTargetReached?.()
          })
        })
      })
    } catch (error) {
      console.error('Failed to load message context:', error)
      // 降级到普通加载
      setIsTargetPositioning(false)
      loadMessages(true)
      onTargetReached?.()
    } finally {
      setLoading(false)
    }
  }, [onTargetReached])

  // 会话切换或搜索跳转
  useEffect(() => {
    if (targetMessageId) {
      loadMessageContext(targetMessageId)
    } else {
      loadMessages(true)
    }
  }, [session.session_id, targetMessageId])

  // 非跳转模式下，首次加载后滚动到底部
  useEffect(() => {
    if (!loading && containerRef.current && !loadingMore && !targetMessageId) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [loading, session.session_id])

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.target as HTMLDivElement

    // 检测是否需要显示"滚动到底部"按钮
    const isNearBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 200
    setShowScrollBottom(!isNearBottom)

    // 向上滚动加载更多
    if (shouldAutoLoadMoreOnScroll({
      hasMore,
      loadingMore,
      scrollTop: target.scrollTop,
      isTargetPositioning,
    })) {
      const { nextPage } = getHistoryRequestPage({ currentPage: page, reset: false })
      loadMessages(false, nextPage)
    }
  }

  const scrollToBottom = () => {
    if (containerRef.current) {
      containerRef.current.scrollTo({
        top: containerRef.current.scrollHeight,
        behavior: 'smooth'
      })
    }
  }

  const displayName = sessionLabel(session.display_name, session.session_id)

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* 头部 */}
      <header className="h-16 px-4 sm:px-6 flex items-center justify-between border-b border-dark-600 bg-dark-800/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className={cn(
            'w-10 h-10 rounded-full flex items-center justify-center text-white font-medium bg-gradient-to-br flex-shrink-0',
            getAvatarColor(displayName)
          )}>
            {session.is_chatroom ? <Users size={18} /> : getInitials(displayName)}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="font-medium text-white truncate">{displayName}</h2>
            <p className="text-xs text-gray-500 truncate">
              {session.message_count} 条消息
              {session.is_chatroom && ' · 群聊'}
            </p>
          </div>
        </div>
        <button className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-white transition-colors flex-shrink-0">
          <MoreVertical size={18} />
        </button>
      </header>

      {/* 消息列表 */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto overflow-x-hidden px-4 sm:px-6 py-4"
        onScroll={handleScroll}
      >
        {/* 加载更多指示器 */}
        {loadingMore && (
          <div className="text-center py-3">
            <div className="inline-flex items-center gap-2 text-sm text-gray-500">
              <div className="w-4 h-4 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin" />
              加载更多...
            </div>
          </div>
        )}

        {hasMore && !loadingMore && (
          <button
            onClick={() => {
              const { nextPage } = getHistoryRequestPage({ currentPage: page, reset: false })
              loadMessages(false, nextPage)
            }}
            className="w-full py-2 text-sm text-accent-primary hover:text-accent-secondary transition-colors"
          >
            <ChevronUp size={16} className="inline mr-1" />
            加载更早消息
          </button>
        )}

        {loading ? (
          <div className="flex-1 flex items-center justify-center py-20">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin mx-auto mb-3" />
              <p className="text-gray-500 text-sm">加载中...</p>
            </div>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex-1 flex items-center justify-center py-20">
            <p className="text-gray-500">暂无消息</p>
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((message, index) => (
              <MessageBubble
                key={message.id}
                message={message}
                showDate={index === 0 || shouldShowDate(messages[index - 1], message)}
                isHighlighted={highlightId === message.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* 滚动到底部按钮 */}
      {showScrollBottom && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-6 right-6 w-10 h-10 rounded-full bg-accent-primary text-white shadow-lg hover:bg-accent-secondary transition-colors flex items-center justify-center"
        >
          <ArrowDown size={18} />
        </button>
      )}
    </div>
  )
}

// 判断是否需要显示日期分隔
function shouldShowDate(prev: Message, current: Message): boolean {
  if (!prev) return true
  const prevDate = new Date(prev.timestamp * 1000).toDateString()
  const currentDate = new Date(current.timestamp * 1000).toDateString()
  return prevDate !== currentDate
}

interface MessageBubbleProps {
  message: Message
  showDate: boolean
  isHighlighted?: boolean
}

function MessageBubble({ message, showDate, isHighlighted }: MessageBubbleProps) {
  const isText = message.msg_type === MSG_TYPES.TEXT
  const senderName = message.sender_name || message.sender_wxid || '未知'
  const avatarColor = getAvatarColor(senderName)

  return (
    <>
      {/* 日期分隔 */}
      {showDate && (
        <div className="flex items-center justify-center py-3">
          <span className="px-3 py-1 text-xs text-gray-500 bg-dark-700 rounded-full">
            {formatDateTime(message.timestamp).split(' ')[0]}
          </span>
        </div>
      )}

      {/* 消息气泡 */}
      <div
        id={`msg-${message.id}`}
        className={cn(
          'flex gap-3 message-bubble transition-all duration-500',
          message.is_sender ? 'flex-row-reverse' : '',
          isHighlighted && 'message-highlight'
        )}
      >
        {/* 头像 */}
        <div className={cn(
          'w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-medium bg-gradient-to-br flex-shrink-0',
          avatarColor
        )}>
          {getInitials(senderName)}
        </div>

        {/* 消息内容 */}
        <div className={cn(
          'max-w-[75%] min-w-0 group',
          message.is_sender ? 'items-end' : 'items-start'
        )}>
          {/* 发送者名称 */}
          {!message.is_sender && (
            <div className="text-xs text-gray-500 mb-1 px-1 truncate max-w-full">
              {senderName}
            </div>
          )}

          {/* 气泡 */}
          <div className={cn(
            'px-4 py-2.5 rounded-2xl text-sm break-words overflow-hidden relative',
            message.is_sender
              ? 'bg-accent-primary text-white rounded-br-md shadow-sm'
              : 'bg-dark-600 text-gray-200 rounded-bl-md shadow-sm',
            message.msg_type === MSG_TYPES.VOICE ? 'p-1.5' : '' // 为语音消息减少内边距
          )}>
            {isText ? (
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
            ) : message.msg_type === MSG_TYPES.VOICE ? (
              <VoicePlayer message={message} />
            ) : (
              <div className="flex items-center gap-2 text-gray-400 flex-wrap">
                <span className="text-xs px-2 py-0.5 bg-dark-500 rounded flex-shrink-0">
                  {getMsgTypeLabel(message.msg_type)}
                </span>
                <span className="text-xs opacity-70 truncate">
                  {message.content?.slice(0, 50) || '不支持的消息类型'}
                </span>
              </div>
            )}
          </div>

          {/* 时间 */}
          <div className={cn(
            'text-xs text-gray-600 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity',
            message.is_sender ? 'text-right' : 'text-left'
          )}>
            {formatTime(message.timestamp)}
          </div>
        </div>
      </div>
    </>
  )
}

// 语音播放器组件
function VoicePlayer({ message }: { message: Message }) {
  const [isPlaying, setIsPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  
  // 解析语音时长
  const duration = useMemo(() => {
    if (!message.content) return 0
    const match = message.content.match(/voicelength\s*=\s*"(\d+)"/i)
    if (match && match[1]) {
      // 毫秒转秒，向上取整
      return Math.ceil(parseInt(match[1]) / 1000)
    }
    return 0
  }, [message.content])

  const togglePlay = () => {
    if (!message.voice_path) return

    if (!audioRef.current) {
      // 构建音频 URL，取 voice_path 的最后一部分（即文件名）
      const filename = message.voice_path.split('/').pop()
      audioRef.current = new Audio(`/api/chats/voice/${filename}`)
      audioRef.current.onended = () => setIsPlaying(false)
      audioRef.current.onerror = () => {
        console.error('Failed to load audio')
        setIsPlaying(false)
      }
    }
    
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause()
        audioRef.current.currentTime = 0
        setIsPlaying(false)
      } else {
        audioRef.current.play().catch(e => {
          console.error('Play error:', e)
          setIsPlaying(false)
        })
        setIsPlaying(true)
      }
    }
  }

  // 组件卸载时停止播放
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
        audioRef.current = null
      }
    }
  }, [])

  // 动态计算波形宽度 (基础宽度 80px，每秒增加 3px，最大 200px)
  const minWidth = Math.min(220, 80 + duration * 4)

  return (
    <div 
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-xl cursor-pointer select-none transition-all active:scale-[0.98]",
        message.is_sender ? "bg-white/10 hover:bg-white/15" : "bg-dark-500 hover:bg-dark-400",
        !message.voice_path && "opacity-60 cursor-not-allowed grayscale"
      )}
      onClick={togglePlay}
      style={{ minWidth: `${minWidth}px` }}
      title={!message.voice_path ? '语音文件未找到' : '点击播放'}
    >
      <button className={cn(
        "flex-shrink-0 flex items-center justify-center w-7 h-7 rounded-full text-white shadow-sm transition-transform",
        message.is_sender ? "bg-white/20" : "bg-dark-400",
        isPlaying && "scale-90"
      )}>
        {isPlaying ? (
          <Square size={10} fill="currentColor" />
        ) : (
          <Play size={12} fill="currentColor" className="ml-1" />
        )}
      </button>
      
      <div className="flex-1 flex gap-[3px] items-center px-1 overflow-hidden h-5">
        {/* 声波模拟 (随机高度或递进高度) */}
        {[6, 12, 8, 16, 10, 14, 8, 12].slice(0, Math.min(8, Math.max(3, Math.ceil(duration / 2 + 1)))).map((h, i) => (
          <div 
            key={i} 
            className={cn(
              "w-1 rounded-full bg-current opacity-70 transition-all duration-150",
              isPlaying && "animate-pulse"
            )} 
            style={{ 
              height: isPlaying ? '100%' : `${h}px`,
              animationDelay: `${i * 0.1}s`,
              animationDuration: '0.6s'
            }} 
          />
        ))}
      </div>
      
      <span className="text-sm font-medium opacity-90 flex-shrink-0 font-mono">
        {duration}"
      </span>
      
      {!message.voice_path && (
        <span className="absolute -bottom-5 right-1 text-[10px] text-red-400 whitespace-nowrap hidden group-hover:block">
          文件丢失
        </span>
      )}
    </div>
  )
}
