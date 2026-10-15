import { useState, useEffect } from 'react'
import { X, Trash2, Tag, ChevronLeft, ChevronRight, RefreshCw, Loader2, Edit3, Sparkles } from 'lucide-react'
import { cn } from '../utils'
import axios from 'axios'
import { useToast } from '../contexts/ToastContext'
import ConfirmDialog from './ConfirmDialog'

interface LabelingViewProps {
  onClose: () => void
}

interface LabeledItem {
  id: number
  conversation_text: string
  session_id: string
  auto_category: string
  auto_quality_score: number
  human_category: string | null
  human_quality: string | null
  human_notes: string | null
  status: string
  created_at: string
  labeled_at: string | null
}

interface Stats {
  raw_messages: number
  labeled_total: number
  by_status: {
    pending: number
    approved: number
    rejected: number
  }
  by_category: Record<string, number>
}

const CATEGORIES = [
  { id: 'savings_explain', name: '省钱讲解', color: 'bg-yellow-500' },
  { id: 'rebate_query', name: '返利查询', color: 'bg-blue-500' },
  { id: 'coupon_issue', name: '优惠券问题', color: 'bg-red-500' },
  { id: 'order_problem', name: '订单问题', color: 'bg-green-500' },
  { id: 'complaint', name: '投诉处理', color: 'bg-purple-500' },
  { id: 'merchant', name: '到店霸王餐', color: 'bg-pink-500' },
  { id: 'brand_promo', name: '品牌活动', color: 'bg-orange-500' },
  { id: 'points_box', name: '积分盲盒', color: 'bg-teal-500' },
  { id: 'onboarding', name: '新人引导', color: 'bg-cyan-500' },
  { id: 'chitchat', name: '闲聊', color: 'bg-slate-500' },
  { id: 'junk', name: '垃圾数据', color: 'bg-gray-500' },
]

const STATUS_LABELS: Record<string, { name: string; color: string }> = {
  pending: { name: '待审核', color: 'text-yellow-400' },
  approved: { name: '已通过', color: 'text-green-400' },
  rejected: { name: '已拒绝', color: 'text-red-400' },
  modified: { name: '已修改', color: 'text-blue-400' },
}

export default function LabelingView({ onClose }: LabelingViewProps) {
  const { showSuccess, showError } = useToast()
  const [stats, setStats] = useState<Stats | null>(null)
  const [items, setItems] = useState<LabeledItem[]>([])
  const [loading, setLoading] = useState(false)
  const [cleaning, setCleaning] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [currentItem, setCurrentItem] = useState<LabeledItem | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('pending')
  const [editingText, setEditingText] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    onConfirm: () => void
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => { },
  })

  // 加载统计
  const loadStats = async () => {
    try {
      const res = await axios.get('/api/labeling/stats')
      setStats(res.data)
    } catch (e) {
      console.error('Load stats failed:', e)
    }
  }

  // 加载列表
  const loadItems = async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/labeling/list', {
        params: { status: statusFilter, page, page_size: 20 }
      })
      setItems(res.data.items)
      setTotal(res.data.total)
    } catch (e) {
      console.error('Load items failed:', e)
    } finally {
      setLoading(false)
    }
  }

  // 清洗数据
  const handleClean = async () => {
    setCleaning(true)
    try {
      const res = await axios.post('/api/labeling/clean', {
        time_window_seconds: 300,
        max_turns: 20,
        min_quality: 'low',
        limit: 500
      })
      showSuccess(`清洗完成！新增 ${res.data.created} 条待标注数据`)
      loadStats()
      loadItems()
    } catch (e: any) {
      showError('清洗失败: ' + (e.response?.data?.detail || e.message))
    } finally {
      setCleaning(false)
    }
  }

  // 标注单个
  const handleLabel = async (id: number, category: string) => {
    try {
      await axios.post(`/api/labeling/item/${id}/label`, {
        category,
        quality: 'medium',
        modified_text: isEditing ? editingText : null
      })
      loadItems()
      loadStats()
      // 自动跳到下一个
      const idx = items.findIndex(i => i.id === id)
      if (idx < items.length - 1) {
        setCurrentItem(items[idx + 1])
        setEditingText(items[idx + 1].conversation_text)
      } else {
        setCurrentItem(null)
      }
      setIsEditing(false)
    } catch (e) {
      console.error('Label failed:', e)
    }
  }

  // 拒绝
  const handleReject = async (id: number) => {
    try {
      await axios.post(`/api/labeling/item/${id}/reject`)
      loadItems()
      loadStats()
      const idx = items.findIndex(i => i.id === id)
      if (idx < items.length - 1) {
        setCurrentItem(items[idx + 1])
      } else {
        setCurrentItem(null)
      }
    } catch (e) {
      console.error('Reject failed:', e)
    }
  }

  // 批量操作
  const handleBatch = async (action: string, category?: string) => {
    if (selectedIds.size === 0) return
    try {
      await axios.post('/api/labeling/batch', {
        ids: Array.from(selectedIds),
        action,
        category
      })
      setSelectedIds(new Set())
      loadItems()
      loadStats()
    } catch (e) {
      console.error('Batch failed:', e)
    }
  }

  useEffect(() => {
    loadStats()
    loadItems()
  }, [statusFilter, page])

  useEffect(() => {
    if (currentItem) {
      setEditingText(currentItem.conversation_text)
    }
  }, [currentItem])

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-dark-800 animate-fade-in">
      {/* 头部 */}
      <header className="h-16 px-6 flex items-center justify-between border-b border-dark-600 bg-dark-800/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-orange-500 to-pink-600 flex items-center justify-center">
            <Tag size={20} className="text-white" />
          </div>
          <div>
            <h2 className="font-medium text-white">数据标注中心</h2>
            <p className="text-xs text-gray-500">清洗数据 · 人工标注 · 质量把控</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：统计 + 列表 */}
        <div className="w-96 border-r border-dark-600 flex flex-col">
          {/* 统计卡片 */}
          {stats && (
            <div className="p-4 border-b border-dark-600">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-dark-700 rounded-lg p-2">
                  <p className="text-lg font-bold text-white">{stats.by_status.pending}</p>
                  <p className="text-xs text-yellow-400">待审核</p>
                </div>
                <div className="bg-dark-700 rounded-lg p-2">
                  <p className="text-lg font-bold text-white">{stats.by_status.approved}</p>
                  <p className="text-xs text-green-400">已通过</p>
                </div>
                <div className="bg-dark-700 rounded-lg p-2">
                  <p className="text-lg font-bold text-white">{stats.by_status.rejected}</p>
                  <p className="text-xs text-red-400">已拒绝</p>
                </div>
              </div>

              {/* 操作按钮 */}
              <div className="flex gap-2 mt-3">
                <button
                  onClick={handleClean}
                  disabled={cleaning}
                  className="flex-1 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg text-sm flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {cleaning ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                  {cleaning ? '清洗中...' : '清洗数据'}
                </button>
                <button
                  onClick={() => {
                    setConfirmDialog({
                      isOpen: true,
                      title: '清空所有标注数据',
                      message: '确定要清空所有标注数据吗？此操作不可恢复！',
                      onConfirm: async () => {
                        try {
                          await axios.delete('/api/labeling/clear')
                          showSuccess('已清空所有标注数据')
                          loadStats()
                          loadItems()
                        } catch (e) {
                          showError('清空失败')
                        }
                        setConfirmDialog({ ...confirmDialog, isOpen: false })
                      },
                    })
                  }}
                  className="py-2 px-3 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-lg text-sm flex items-center justify-center gap-1"
                  title="清空所有标注数据"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          )}

          {/* 筛选 */}
          <div className="p-3 border-b border-dark-600 flex gap-2">
            {['pending', 'approved', 'rejected'].map(s => (
              <button
                key={s}
                onClick={() => { setStatusFilter(s); setPage(1) }}
                className={cn(
                  'px-3 py-1 rounded-full text-xs',
                  statusFilter === s
                    ? 'bg-accent-primary text-white'
                    : 'bg-dark-700 text-gray-400 hover:text-white'
                )}
              >
                {STATUS_LABELS[s].name}
              </button>
            ))}
          </div>

          {/* 批量操作 */}
          {selectedIds.size > 0 && (
            <div className="p-2 bg-dark-700 flex items-center gap-2 text-sm">
              <span className="text-gray-400">已选 {selectedIds.size} 项</span>
              <button
                onClick={() => handleBatch('approve')}
                className="px-2 py-1 bg-green-600 text-white rounded text-xs"
              >
                批量通过
              </button>
              <button
                onClick={() => handleBatch('reject')}
                className="px-2 py-1 bg-red-600 text-white rounded text-xs"
              >
                批量拒绝
              </button>
            </div>
          )}

          {/* 列表 */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="animate-spin text-accent-primary" />
              </div>
            ) : items.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <p>暂无数据</p>
                <p className="text-xs mt-1">点击"清洗原始数据"开始</p>
              </div>
            ) : (
              items.map(item => (
                <div
                  key={item.id}
                  onClick={() => setCurrentItem(item)}
                  className={cn(
                    'p-3 border-b border-dark-700 cursor-pointer hover:bg-dark-700/50 transition-colors',
                    currentItem?.id === item.id && 'bg-dark-700'
                  )}
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(item.id)}
                      onChange={e => {
                        e.stopPropagation()
                        const newSet = new Set(selectedIds)
                        if (e.target.checked) newSet.add(item.id)
                        else newSet.delete(item.id)
                        setSelectedIds(newSet)
                      }}
                      className="mt-1"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-300 line-clamp-2">
                        {item.conversation_text}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={cn('text-xs', STATUS_LABELS[item.status]?.color)}>
                          {STATUS_LABELS[item.status]?.name}
                        </span>
                        {item.auto_category && (
                          <span className="text-xs text-gray-500">
                            AI: {CATEGORIES.find(c => c.id === item.auto_category)?.name}
                          </span>
                        )}
                        {item.auto_quality_score && (
                          <span className="text-xs text-gray-600">
                            {item.auto_quality_score.toFixed(1)}分
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 分页 */}
          <div className="p-3 border-t border-dark-600 flex items-center justify-between text-sm">
            <span className="text-gray-500">共 {total} 条</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1 hover:bg-dark-700 rounded disabled:opacity-50"
              >
                <ChevronLeft size={16} />
              </button>
              <span className="text-gray-400">{page}</span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={items.length < 20}
                className="p-1 hover:bg-dark-700 rounded disabled:opacity-50"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </div>

        {/* 右侧：详情 + 标注 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {currentItem ? (
            <>
              {/* 对话内容 */}
              <div className="flex-1 overflow-y-auto p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-medium text-white">对话内容</h3>
                  <button
                    onClick={() => setIsEditing(!isEditing)}
                    className={cn(
                      'px-3 py-1 rounded-lg text-sm flex items-center gap-1',
                      isEditing ? 'bg-blue-600 text-white' : 'bg-dark-600 text-gray-400 hover:text-white'
                    )}
                  >
                    <Edit3 size={14} />
                    {isEditing ? '编辑中' : '编辑'}
                  </button>
                </div>

                {isEditing ? (
                  <textarea
                    value={editingText}
                    onChange={e => setEditingText(e.target.value)}
                    className="w-full h-64 p-4 bg-dark-700 border border-dark-500 rounded-xl text-gray-200 text-sm resize-none focus:outline-none focus:border-accent-primary"
                    placeholder="编辑对话内容..."
                  />
                ) : (
                  <div className="bg-dark-700 rounded-xl p-4 space-y-3">
                    {currentItem.conversation_text.split('\n').map((line, i) => {
                      const isCustomer = line.startsWith('客户:') || line.startsWith('客户：')
                      return (
                        <div key={i} className={cn('flex', isCustomer ? '' : 'justify-end')}>
                          <div className={cn(
                            'max-w-[80%] px-4 py-2 rounded-2xl text-sm',
                            isCustomer
                              ? 'bg-dark-600 text-gray-200 rounded-bl-md'
                              : 'bg-accent-primary text-white rounded-br-md'
                          )}>
                            {line.replace(/^(客户|商家)[：:]\s*/, '')}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* AI 建议 */}
                {currentItem.auto_category && (
                  <div className="mt-4 p-3 bg-dark-700/50 rounded-lg">
                    <div className="flex items-center gap-2 text-sm">
                      <Sparkles size={14} className="text-yellow-400" />
                      <span className="text-gray-400">AI 建议分类：</span>
                      <span className="text-white">
                        {CATEGORIES.find(c => c.id === currentItem.auto_category)?.name}
                      </span>
                      {currentItem.auto_quality_score && (
                        <span className="text-gray-500">
                          （质量分：{currentItem.auto_quality_score.toFixed(1)}）
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* 标注操作 */}
              <div className="p-4 border-t border-dark-600 bg-dark-800">
                <p className="text-sm text-gray-400 mb-3">选择分类：</p>
                <div className="flex flex-wrap gap-2">
                  {CATEGORIES.map(cat => (
                    <button
                      key={cat.id}
                      onClick={() => handleLabel(currentItem.id, cat.id)}
                      className={cn(
                        'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                        cat.id === 'junk'
                          ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                          : 'bg-dark-600 text-white hover:bg-dark-500'
                      )}
                    >
                      {cat.name}
                    </button>
                  ))}
                </div>
                <div className="flex gap-3 mt-4">
                  <button
                    onClick={() => handleReject(currentItem.id)}
                    className="flex-1 py-2 bg-red-600/20 text-red-400 rounded-lg hover:bg-red-600/30 flex items-center justify-center gap-2"
                  >
                    <Trash2 size={16} />
                    拒绝/删除
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500">
              <div className="text-center">
                <Tag size={48} className="mx-auto mb-4 opacity-30" />
                <p>选择左侧数据进行标注</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirm Dialog */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        variant="danger"
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}
      />
    </div>
  )
}
