import { useState, useEffect, useCallback } from 'react'
import { Search, X, MessageCircle, Calendar, User, ChevronRight } from 'lucide-react'
import { searchMessages } from '../api'
import { SearchResult } from '../types'
import { formatDateTime, truncate } from '../utils'
import { getSearchViewLayoutClasses } from './searchViewLayout'
import { sessionLabel } from '../sessionDisplay'

interface SearchViewProps {
  onClose: () => void
  onJumpToMessage: (sessionId: string, messageId?: number) => void
}

export default function SearchView({ onClose, onJumpToMessage }: SearchViewProps) {
  const layoutClasses = getSearchViewLayoutClasses()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)

  const doSearch = useCallback(async (reset = false) => {
    if (!query.trim()) {
      setResults([])
      setTotal(0)
      return
    }

    try {
      setLoading(true)
      const currentPage = reset ? 1 : page
      const result = await searchMessages({
        q: query,
        page: currentPage,
        page_size: 20,
      })

      if (reset) {
        setResults(result.items)
        setPage(1)
      } else {
        setResults(prev => [...prev, ...result.items])
      }
      setTotal(result.total)
      setHasMore(result.has_more)
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      setLoading(false)
    }
  }, [query, page])

  // 防抖搜索
  useEffect(() => {
    const timer = setTimeout(() => {
      doSearch(true)
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  const handleLoadMore = () => {
    setPage(prev => prev + 1)
    doSearch()
  }

  return (
    <div className={layoutClasses.root}>
      {/* 搜索头部 */}
      <header className="h-16 px-6 flex items-center gap-4 border-b border-dark-600 bg-dark-800/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex-1 relative">
          <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="搜索聊天记录..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
            className="w-full pl-11 pr-4 py-2.5 bg-dark-700 border border-dark-500 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary/50 transition-colors"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-gray-500 hover:text-white transition-colors"
            >
              <X size={16} />
            </button>
          )}
        </div>
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
        >
          取消
        </button>
      </header>

      {/* 搜索结果 */}
      <div className={layoutClasses.results}>
        {loading && results.length === 0 ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin mx-auto mb-3" />
              <p className="text-gray-500 text-sm">搜索中...</p>
            </div>
          </div>
        ) : !query ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center text-gray-500">
              <Search size={48} className="mx-auto mb-4 opacity-30" />
              <p>输入关键词搜索聊天记录</p>
              <p className="text-sm mt-2 text-gray-600">支持搜索所有文本消息</p>
            </div>
          </div>
        ) : results.length === 0 ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center text-gray-500">
              <MessageCircle size={48} className="mx-auto mb-4 opacity-30" />
              <p>未找到相关消息</p>
              <p className="text-sm mt-2 text-gray-600">尝试使用其他关键词</p>
            </div>
          </div>
        ) : (
          <div className="p-4">
            {/* 结果统计 */}
            <div className="mb-4 text-sm text-gray-500">
              找到 <span className="text-accent-primary font-medium">{total}</span> 条相关消息
            </div>

            {/* 结果列表 */}
            <div className="space-y-2">
              {results.map((result, index) => (
                <SearchResultItem
                  key={`${result.id}-${index}`}
                  result={result}
                  query={query}
                  onClick={() => onJumpToMessage(result.session_id, result.id)}
                />
              ))}
            </div>

            {/* 加载更多 */}
            {hasMore && (
              <button
                onClick={handleLoadMore}
                disabled={loading}
                className="w-full mt-4 py-3 text-sm text-accent-primary hover:text-accent-secondary transition-colors disabled:opacity-50"
              >
                {loading ? (
                  <span className="inline-flex items-center gap-2">
                    <div className="w-4 h-4 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin" />
                    加载中...
                  </span>
                ) : (
                  '加载更多'
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

interface SearchResultItemProps {
  result: SearchResult
  query: string
  onClick: () => void
}

function SearchResultItem({ result, query, onClick }: SearchResultItemProps) {
  // 高亮关键词
  const highlightText = (text: string | null) => {
    if (!text) return null
    const regex = new RegExp(`(${query})`, 'gi')
    const parts = text.split(regex)
    return parts.map((part, i) =>
      regex.test(part) ? (
        <span key={i} className="search-highlight">{part}</span>
      ) : (
        <span key={i}>{part}</span>
      )
    )
  }

  return (
    <button
      onClick={onClick}
      className="w-full p-4 bg-dark-700/50 hover:bg-dark-600 rounded-xl text-left transition-colors group"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          {/* 会话名称 */}
          <div className="flex items-center gap-2 mb-2">
            <span className="font-medium text-white">
              {sessionLabel(result.session_name, result.session_id)}
            </span>
            {result.sender_name && (
              <>
                <span className="text-gray-600">·</span>
                <span className="text-sm text-gray-500 flex items-center gap-1">
                  <User size={12} />
                  {result.sender_name}
                </span>
              </>
            )}
          </div>

          {/* 消息内容 */}
          <p className="text-sm text-gray-400 leading-relaxed">
            {highlightText(result.highlight || truncate(result.content, 100))}
          </p>

          {/* 时间 */}
          <div className="flex items-center gap-1 mt-2 text-xs text-gray-600">
            <Calendar size={12} />
            {formatDateTime(result.timestamp)}
          </div>
        </div>

        {/* 跳转箭头 */}
        <ChevronRight
          size={18}
          className="text-gray-600 group-hover:text-accent-primary transition-colors flex-shrink-0 mt-1"
        />
      </div>
    </button>
  )
}
