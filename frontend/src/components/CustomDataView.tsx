import { useState, useEffect } from 'react'
import { Plus, Edit2, Trash2, Power, PowerOff, Save, X, Database, Sparkles, Square, Download, XCircle, Eye, CheckCircle2, ChevronDown, ChevronUp, Pencil } from 'lucide-react'
import { cn } from '../utils'
import axios from 'axios'
import { useToast } from '../contexts/ToastContext'
import ConfirmDialog from './ConfirmDialog'

const API_BASE = ''

interface ConversationTurn {
  role: 'user' | 'assistant' | 'system'
  content: string
}

interface CustomConversation {
  id: number
  conversation_json: ConversationTurn[]
  category: string
  quality: string
  system_prompt?: string
  title?: string
  description?: string
  tags?: string[]
  source: string
  created_by?: string
  created_at: string
  updated_at: string
  is_active: boolean
}

interface CustomDataStats {
  total: number
  active: number
  inactive: number
  by_category: Record<string, number>
  by_quality: Record<string, number>
}

const CATEGORIES = [
  { id: 'savings_explain', name: '省钱讲解' },
  { id: 'rebate_query', name: '返利查询' },
  { id: 'coupon_issue', name: '优惠券问题' },
  { id: 'order_problem', name: '订单问题' },
  { id: 'complaint', name: '投诉处理' },
  { id: 'merchant', name: '到店霸王餐' },
  { id: 'brand_promo', name: '品牌活动' },
  { id: 'points_box', name: '积分盲盒' },
  { id: 'onboarding', name: '新人引导' },
  { id: 'chitchat', name: '闲聊' },
]

const QUALITIES = [
  { id: 'high', name: '高质量' },
  { id: 'medium', name: '中等' },
  { id: 'low', name: '低质量' },
]

export default function CustomDataView() {
  const { showSuccess, showError } = useToast()
  const [conversations, setConversations] = useState<CustomConversation[]>([])
  const [stats, setStats] = useState<CustomDataStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>('')
  const [filterQuality, setFilterQuality] = useState<string>('')
  const [filterActive, setFilterActive] = useState<boolean | null>(null)
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    onConfirm: () => void
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {},
  })

  // AI 生成相关状态
  const [showGeneratePanel, setShowGeneratePanel] = useState(false)
  const [generateConfig, setGenerateConfig] = useState({
    targetCount: 200,
    categories: [] as string[],
  })
  const [generateProgress, setGenerateProgress] = useState<{
    total: number
    completed: number
    passed: number
    failed: number
    is_running: boolean
    error_count: number
    errors: string[]
  } | null>(null)
  const [isPolling, setIsPolling] = useState(false)

  // 审核相关状态
  const [showReviewPanel, setShowReviewPanel] = useState(false)
  const [reviewItems, setReviewItems] = useState<
    Array<{
      index: number
      category: string
      title: string
      description: string
      conversation_json: ConversationTurn[]
      turn_count: number
      approved: boolean
      edited: boolean
    }>
  >([])
  const [expandedReviewIdx, setExpandedReviewIdx] = useState<number | null>(null)
  const [editingReviewIdx, setEditingReviewIdx] = useState<number | null>(null)
  const [savingReview, setSavingReview] = useState(false)

  // 表单状态
  const [formData, setFormData] = useState<{
    title: string
    description: string
    category: string
    quality: string
    systemPrompt: string
    turns: ConversationTurn[]
  }>({
    title: '',
    description: '',
    category: 'savings_explain',
    quality: 'high',
    systemPrompt: '',
    turns: [
      { role: 'user', content: '' },
      { role: 'assistant', content: '' },
    ],
  })

  useEffect(() => {
    loadConversations()
    loadStats()
  }, [filterCategory, filterQuality, filterActive])

  const loadConversations = async () => {
    setLoading(true)
    try {
      const params: any = { limit: 500 }
      if (filterCategory) params.category = filterCategory
      if (filterQuality) params.quality = filterQuality
      if (filterActive !== null) params.is_active = filterActive

      const response = await axios.get(`${API_BASE}/api/custom/conversations`, { params })
      setConversations(response.data)
    } catch (error) {
      console.error('加载失败:', error)
      showError('加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/custom/stats`)
      setStats(response.data)
    } catch (error) {
      console.error('加载统计失败:', error)
    }
  }

  const handleCreate = async () => {
    try {
      // 验证
      if (formData.turns.length < 2) {
        showError('至少需要 2 轮对话')
        return
      }
      if (formData.turns.some((t) => !t.content.trim())) {
        showError('对话内容不能为空')
        return
      }

      const payload = {
        conversation_json: formData.turns,
        category: formData.category,
        quality: formData.quality,
        system_prompt: formData.systemPrompt || undefined,
        title: formData.title || undefined,
        description: formData.description || undefined,
        source: 'manual',
        created_by: 'admin',
      }

      await axios.post(`${API_BASE}/api/custom/conversations`, payload)
      showSuccess('创建成功')
      setShowForm(false)
      resetForm()
      loadConversations()
      loadStats()
    } catch (error: any) {
      console.error('创建失败:', error)
      showError(error.response?.data?.detail || '创建失败')
    }
  }

  const handleUpdate = async () => {
    if (!editingId) return

    try {
      const payload = {
        conversation_json: formData.turns,
        category: formData.category,
        quality: formData.quality,
        system_prompt: formData.systemPrompt || undefined,
        title: formData.title || undefined,
        description: formData.description || undefined,
      }

      await axios.put(`${API_BASE}/api/custom/conversations/${editingId}`, payload)
      showSuccess('更新成功')
      setShowForm(false)
      setEditingId(null)
      resetForm()
      loadConversations()
    } catch (error: any) {
      console.error('更新失败:', error)
      showError(error.response?.data?.detail || '更新失败')
    }
  }

  const handleDelete = async (id: number) => {
    setConfirmDialog({
      isOpen: true,
      title: '删除对话',
      message: '确定要删除这条对话吗？',
      onConfirm: async () => {
        try {
          await axios.delete(`${API_BASE}/api/custom/conversations/${id}`)
          showSuccess('删除成功')
          loadConversations()
          loadStats()
        } catch (error) {
          console.error('删除失败:', error)
          showError('删除失败')
        }
        setConfirmDialog({ ...confirmDialog, isOpen: false })
      },
    })
  }

  const handleToggle = async (id: number) => {
    try {
      await axios.post(`${API_BASE}/api/custom/conversations/${id}/toggle`)
      loadConversations()
      loadStats()
    } catch (error) {
      console.error('切换状态失败:', error)
      showError('切换状态失败')
    }
  }

  const handleEdit = (conv: CustomConversation) => {
    setEditingId(conv.id)
    setFormData({
      title: conv.title || '',
      description: conv.description || '',
      category: conv.category,
      quality: conv.quality,
      systemPrompt: conv.system_prompt || '',
      turns: conv.conversation_json,
    })
    setShowForm(true)
  }

  const resetForm = () => {
    setFormData({
      title: '',
      description: '',
      category: 'savings_explain',
      quality: 'high',
      systemPrompt: '',
      turns: [
        { role: 'user', content: '' },
        { role: 'assistant', content: '' },
      ],
    })
  }

  const addTurn = () => {
    const lastRole = formData.turns[formData.turns.length - 1]?.role
    const nextRole = lastRole === 'user' ? 'assistant' : 'user'
    setFormData({
      ...formData,
      turns: [...formData.turns, { role: nextRole, content: '' }],
    })
  }

  const removeTurn = (index: number) => {
    if (formData.turns.length <= 2) {
      showError('至少需要保留 2 轮对话')
      return
    }
    setFormData({
      ...formData,
      turns: formData.turns.filter((_, i) => i !== index),
    })
  }

  const updateTurn = (index: number, field: 'role' | 'content', value: string) => {
    const newTurns = [...formData.turns]
    newTurns[index] = { ...newTurns[index], [field]: value }
    setFormData({ ...formData, turns: newTurns })
  }

  // ===== AI 批量生成相关函数 =====

  const handleStartGenerate = async () => {
    try {
      const payload: any = { target_count: generateConfig.targetCount }
      if (generateConfig.categories.length > 0) {
        payload.categories = generateConfig.categories
      }
      await axios.post(`${API_BASE}/api/custom/conversations/generate`, payload)
      showSuccess('生成任务已启动')
      setIsPolling(true)
      pollProgress()
    } catch (error: any) {
      showError(error.response?.data?.detail || '启动生成失败')
    }
  }

  const pollProgress = async () => {
    const poll = async () => {
      try {
        const response = await axios.get(`${API_BASE}/api/custom/conversations/generate/progress`)
        setGenerateProgress(response.data)

        if (response.data.is_running) {
          setTimeout(poll, 1500)
        } else {
          setIsPolling(false)
          if (response.data.passed > 0) {
            showSuccess(`生成完成: ${response.data.passed} 条通过校验`)
          }
        }
      } catch (error) {
        console.error('获取进度失败:', error)
        setIsPolling(false)
      }
    }
    poll()
  }

  const handleEnterReview = async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/custom/conversations/generate/results`)
      const items = response.data.results.map((r: any) => ({
        ...r,
        approved: true,
        edited: false,
      }))
      setReviewItems(items)
      setExpandedReviewIdx(items.length > 0 ? 0 : null)
      setEditingReviewIdx(null)
      setShowGeneratePanel(false)
      setShowReviewPanel(true)
    } catch (error: any) {
      showError(error.response?.data?.detail || '加载预览数据失败')
    }
  }

  const handleSaveApproved = async () => {
    const approvedItems = reviewItems.filter((r) => r.approved)
    if (approvedItems.length === 0) {
      showError('请至少批准一条对话')
      return
    }
    // 收集编辑过的数据
    const edits: Record<number, ConversationTurn[]> = {}
    for (const item of approvedItems) {
      if (item.edited) {
        edits[item.index] = item.conversation_json
      }
    }
    setSavingReview(true)
    try {
      const response = await axios.post(`${API_BASE}/api/custom/conversations/generate/save`, {
        approved_indices: approvedItems.map((r) => r.index),
        edits: Object.keys(edits).length > 0 ? edits : undefined,
      })
      showSuccess(response.data.message)
      setShowReviewPanel(false)
      setReviewItems([])
      setEditingReviewIdx(null)
      setGenerateProgress(null)
      loadConversations()
      loadStats()
    } catch (error: any) {
      showError(error.response?.data?.detail || '保存失败')
    } finally {
      setSavingReview(false)
    }
  }

  const handleStopGenerate = async () => {
    try {
      await axios.post(`${API_BASE}/api/custom/conversations/generate/stop`)
      showSuccess('已发送停止信号')
    } catch (error) {
      showError('停止失败')
    }
  }

  const toggleCategory = (catId: string) => {
    setGenerateConfig((prev) => {
      const cats = prev.categories.includes(catId)
        ? prev.categories.filter((c) => c !== catId)
        : [...prev.categories, catId]
      return { ...prev, categories: cats }
    })
  }

  const toggleReviewApproval = (idx: number) => {
    setReviewItems((prev) =>
      prev.map((item, i) => (i === idx ? { ...item, approved: !item.approved } : item))
    )
  }

  const setAllReviewApproval = (approved: boolean) => {
    setReviewItems((prev) => prev.map((item) => ({ ...item, approved })))
  }

  const updateReviewTurnContent = (itemIdx: number, turnIdx: number, content: string) => {
    setReviewItems((prev) =>
      prev.map((item, i) => {
        if (i !== itemIdx) return item
        const newTurns = [...item.conversation_json]
        newTurns[turnIdx] = { ...newTurns[turnIdx], content }
        return { ...item, conversation_json: newTurns, edited: true }
      })
    )
  }

  const deleteReviewTurn = (itemIdx: number, turnIdx: number) => {
    setReviewItems((prev) =>
      prev.map((item, i) => {
        if (i !== itemIdx) return item
        if (item.conversation_json.length <= 2) return item
        const newTurns = item.conversation_json.filter((_, ti) => ti !== turnIdx)
        return { ...item, conversation_json: newTurns, turn_count: newTurns.length, edited: true }
      })
    )
  }

  const approvedCount = reviewItems.filter((r) => r.approved).length

  return (
    <div className="h-full flex flex-col bg-dark-900">
      {/* 头部 */}
      <div className="bg-dark-800 border-b border-dark-700 p-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
            <Database className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">自定义对话数据管理</h1>
        </div>
        <p className="text-gray-400 mt-2">手动添加高质量对话数据，可直接用于训练导出</p>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="bg-dark-800 border-b border-dark-700 p-4">
          <div className="grid grid-cols-5 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-accent-primary">{stats.total}</div>
              <div className="text-sm text-gray-400">总数</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-400">{stats.active}</div>
              <div className="text-sm text-gray-400">已启用</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-500">{stats.inactive}</div>
              <div className="text-sm text-gray-400">已禁用</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-400">
                {Object.keys(stats.by_category).length}
              </div>
              <div className="text-sm text-gray-400">分类数</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-400">
                {stats.by_quality.high || 0}
              </div>
              <div className="text-sm text-gray-400">高质量</div>
            </div>
          </div>
        </div>
      )}

      {/* 筛选和操作栏 */}
      <div className="bg-dark-800 border-b border-dark-700 p-4 flex items-center gap-4">
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
        >
          <option value="">全部分类</option>
          {CATEGORIES.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
            </option>
          ))}
        </select>

        <select
          value={filterQuality}
          onChange={(e) => setFilterQuality(e.target.value)}
          className="px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
        >
          <option value="">全部质量</option>
          {QUALITIES.map((q) => (
            <option key={q.id} value={q.id}>
              {q.name}
            </option>
          ))}
        </select>

        <select
          value={filterActive === null ? '' : filterActive.toString()}
          onChange={(e) =>
            setFilterActive(e.target.value === '' ? null : e.target.value === 'true')
          }
          className="px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
        >
          <option value="">全部状态</option>
          <option value="true">已启用</option>
          <option value="false">已禁用</option>
        </select>

        <div className="flex-1" />

        <button
          onClick={() => setShowGeneratePanel(true)}
          className="px-4 py-2 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-lg hover:from-purple-600 hover:to-pink-600 flex items-center gap-2 transition-all"
        >
          <Sparkles className="w-4 h-4" />
          AI 批量生成
        </button>

        <button
          onClick={() => {
            setEditingId(null)
            resetForm()
            setShowForm(true)
          }}
          className="px-4 py-2 bg-accent-primary text-white rounded-lg hover:bg-accent-secondary flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          新增对话
        </button>
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="text-center py-20 text-gray-500">加载中...</div>
        ) : conversations.length === 0 ? (
          <div className="text-center py-20 text-gray-500">暂无数据</div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={cn(
                  "bg-dark-800 border rounded-xl p-4 transition-all",
                  conv.is_active ? 'border-dark-700' : 'border-dark-700 opacity-60'
                )}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-medium text-white">
                        {conv.title || `对话 #${conv.id}`}
                      </h3>
                      <span
                        className={cn(
                          "px-2 py-0.5 text-xs rounded-full font-medium",
                          conv.category === 'savings_explain'
                            ? 'bg-blue-500/20 text-blue-400'
                            : conv.category === 'rebate_query'
                            ? 'bg-green-500/20 text-green-400'
                            : conv.category === 'complaint'
                            ? 'bg-red-500/20 text-red-400'
                            : 'bg-gray-500/20 text-gray-400'
                        )}
                      >
                        {CATEGORIES.find((c) => c.id === conv.category)?.name || conv.category}
                      </span>
                      <span
                        className={cn(
                          "px-2 py-0.5 text-xs rounded-full font-medium",
                          conv.quality === 'high'
                            ? 'bg-green-500/20 text-green-400'
                            : conv.quality === 'medium'
                            ? 'bg-yellow-500/20 text-yellow-400'
                            : 'bg-gray-500/20 text-gray-400'
                        )}
                      >
                        {QUALITIES.find((q) => q.id === conv.quality)?.name || conv.quality}
                      </span>
                    </div>
                    {conv.description && (
                      <p className="text-sm text-gray-400 mb-2">{conv.description}</p>
                    )}
                    <div className="text-xs text-gray-500">
                      {conv.conversation_json.length} 轮对话 · 创建于{' '}
                      {new Date(conv.created_at).toLocaleString('zh-CN')}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleToggle(conv.id)}
                      className={cn(
                        "p-2 rounded-lg transition-colors",
                        conv.is_active
                          ? 'text-green-400 hover:bg-green-500/10'
                          : 'text-gray-500 hover:bg-dark-700'
                      )}
                      title={conv.is_active ? '禁用' : '启用'}
                    >
                      {conv.is_active ? (
                        <Power className="w-4 h-4" />
                      ) : (
                        <PowerOff className="w-4 h-4" />
                      )}
                    </button>
                    <button
                      onClick={() => handleEdit(conv)}
                      className="p-2 text-accent-primary hover:bg-accent-primary/10 rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(conv.id)}
                      className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* 对话预览 */}
                <div className="space-y-2 bg-dark-700 rounded-lg p-3 max-h-60 overflow-y-auto">
                  {conv.system_prompt && (
                    <div className="p-2 rounded-lg text-sm bg-purple-500/20 text-purple-300">
                      <div className="font-medium text-xs mb-1 opacity-80">系统提示词:</div>
                      <div className="whitespace-pre-wrap">
                        {conv.system_prompt.length > 200
                          ? conv.system_prompt.substring(0, 200) + '...'
                          : conv.system_prompt}
                      </div>
                    </div>
                  )}
                  {conv.conversation_json.map((turn, idx) => (
                    <div
                      key={idx}
                      className={cn(
                        "p-2 rounded-lg text-sm",
                        turn.role === 'user'
                          ? 'bg-blue-500/20 text-blue-300'
                          : turn.role === 'assistant'
                          ? 'bg-green-500/20 text-green-300'
                          : 'bg-yellow-500/20 text-yellow-300'
                      )}
                    >
                      <div className="font-medium text-xs mb-1 opacity-80">
                        {turn.role === 'user'
                          ? '用户'
                          : turn.role === 'assistant'
                          ? '助手'
                          : '系统'}
                        :
                      </div>
                      <div className="whitespace-pre-wrap">
                        {turn.content.length > 200
                          ? turn.content.substring(0, 200) + '...'
                          : turn.content}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 创建/编辑表单 Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-dark-800 rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto border border-dark-700">
            <div className="sticky top-0 bg-dark-700 border-b border-dark-600 px-6 py-4 flex justify-between items-center">
              <h2 className="text-xl font-bold text-white">
                {editingId ? '编辑对话' : '新增对话'}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingId(null)
                  resetForm()
                }}
                className="p-2 hover:bg-dark-600 rounded-lg text-gray-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* 基本信息 */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  标题（可选）
                </label>
                <input
                  type="text"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  placeholder="为这个对话起一个标题"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  描述（可选）
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  placeholder="描述这个对话的用途或特点"
                  rows={2}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  系统提示词（可选）
                </label>
                <textarea
                  value={formData.systemPrompt}
                  onChange={(e) => setFormData({ ...formData, systemPrompt: e.target.value })}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  placeholder="自定义系统提示词，留空则导出时使用分类默认提示词"
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    分类 *
                  </label>
                  <select
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  >
                    {CATEGORIES.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    质量 *
                  </label>
                  <select
                    value={formData.quality}
                    onChange={(e) => setFormData({ ...formData, quality: e.target.value })}
                    className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  >
                    {QUALITIES.map((q) => (
                      <option key={q.id} value={q.id}>
                        {q.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* 对话轮次 */}
              <div>
                <div className="flex justify-between items-center mb-3">
                  <label className="block text-sm font-medium text-gray-300">
                    对话内容 *（至少 2 轮）
                  </label>
                  <button
                    onClick={addTurn}
                    className="px-3 py-1 text-sm bg-dark-600 hover:bg-dark-500 text-white rounded-lg flex items-center gap-1 transition-colors"
                  >
                    <Plus className="w-3 h-3" />
                    添加轮次
                  </button>
                </div>

                <div className="space-y-3">
                  {formData.turns.map((turn, idx) => (
                    <div key={idx} className="border border-dark-600 rounded-lg p-4 bg-dark-700">
                      <div className="flex justify-between items-center mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-300">
                            第 {idx + 1} 轮
                          </span>
                          <select
                            value={turn.role}
                            onChange={(e) =>
                              updateTurn(idx, 'role', e.target.value)
                            }
                            className="px-2 py-1 text-sm bg-dark-600 border border-dark-500 rounded text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
                          >
                            <option value="user">用户</option>
                            <option value="assistant">助手</option>
                            <option value="system">系统</option>
                          </select>
                        </div>
                        {formData.turns.length > 2 && (
                          <button
                            onClick={() => removeTurn(idx)}
                            className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                      <textarea
                        value={turn.content}
                        onChange={(e) => updateTurn(idx, 'content', e.target.value)}
                        className="w-full px-3 py-2 bg-dark-600 border border-dark-500 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent-primary"
                        placeholder={`输入${
                          turn.role === 'user'
                            ? '用户'
                            : turn.role === 'assistant'
                            ? '助手'
                            : '系统'
                        }的对话内容...`}
                        rows={3}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* 底部按钮 */}
            <div className="sticky bottom-0 bg-dark-700 border-t border-dark-600 px-6 py-4 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingId(null)
                  resetForm()
                }}
                className="px-4 py-2 text-white bg-dark-600 hover:bg-dark-500 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={editingId ? handleUpdate : handleCreate}
                className="px-4 py-2 bg-accent-primary text-white rounded-lg hover:bg-accent-secondary flex items-center gap-2 transition-colors"
              >
                <Save className="w-4 h-4" />
                {editingId ? '保存修改' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* AI 批量生成面板 */}
      {showGeneratePanel && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-dark-800 rounded-xl shadow-2xl w-full max-w-lg border border-dark-700">
            <div className="bg-dark-700 border-b border-dark-600 px-6 py-4 flex justify-between items-center rounded-t-xl">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-purple-400" />
                <h2 className="text-xl font-bold text-white">AI 批量生成</h2>
              </div>
              <button
                onClick={() => {
                  if (!isPolling) {
                    setShowGeneratePanel(false)
                    setGenerateProgress(null)
                  }
                }}
                className="p-2 hover:bg-dark-600 rounded-lg text-gray-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-5">
              {/* 数量配置 */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  生成数量
                </label>
                <input
                  type="number"
                  min={10}
                  max={500}
                  value={generateConfig.targetCount}
                  onChange={(e) =>
                    setGenerateConfig({ ...generateConfig, targetCount: Number(e.target.value) })
                  }
                  disabled={isPolling}
                  className="w-full px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
                />
              </div>

              {/* 分类选择 */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  指定分类 (不选 = 全部)
                </label>
                <div className="flex flex-wrap gap-2">
                  {CATEGORIES.filter((c) => c.id !== 'chitchat').map((cat) => (
                    <button
                      key={cat.id}
                      onClick={() => toggleCategory(cat.id)}
                      disabled={isPolling}
                      className={cn(
                        'px-3 py-1.5 text-sm rounded-lg border transition-colors',
                        generateConfig.categories.includes(cat.id)
                          ? 'bg-purple-500/30 border-purple-500 text-purple-300'
                          : 'bg-dark-700 border-dark-600 text-gray-400 hover:border-dark-500',
                        isPolling && 'opacity-50 cursor-not-allowed'
                      )}
                    >
                      {cat.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* 进度显示 */}
              {generateProgress && (
                <div className="bg-dark-700 rounded-lg p-4 space-y-3">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">
                      {generateProgress.is_running ? '生成中...' : '生成完成'}
                    </span>
                    <span className="text-white">
                      {generateProgress.completed} / {generateProgress.total}
                    </span>
                  </div>

                  {/* 进度条 */}
                  <div className="w-full bg-dark-600 rounded-full h-2.5">
                    <div
                      className="bg-gradient-to-r from-purple-500 to-pink-500 h-2.5 rounded-full transition-all duration-300"
                      style={{
                        width: `${generateProgress.total > 0 ? (generateProgress.completed / generateProgress.total) * 100 : 0}%`,
                      }}
                    />
                  </div>

                  {/* 统计 */}
                  <div className="grid grid-cols-3 gap-3 text-center">
                    <div>
                      <div className="text-lg font-bold text-green-400">
                        {generateProgress.passed}
                      </div>
                      <div className="text-xs text-gray-500">通过校验</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-red-400">
                        {generateProgress.failed}
                      </div>
                      <div className="text-xs text-gray-500">未通过</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-gray-400">
                        {generateProgress.total - generateProgress.completed}
                      </div>
                      <div className="text-xs text-gray-500">剩余</div>
                    </div>
                  </div>

                  {generateProgress.error_count > 0 && (
                    <div className="text-xs text-red-400 mt-1">
                      {generateProgress.errors[0]}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 底部按钮 */}
            <div className="bg-dark-700 border-t border-dark-600 px-6 py-4 flex justify-end gap-3 rounded-b-xl">
              {isPolling ? (
                <button
                  onClick={handleStopGenerate}
                  className="px-4 py-2 bg-red-500/20 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/30 flex items-center gap-2 transition-colors"
                >
                  <Square className="w-4 h-4" />
                  停止生成
                </button>
              ) : generateProgress && generateProgress.passed > 0 ? (
                <>
                  <button
                    onClick={() => {
                      setShowGeneratePanel(false)
                      setGenerateProgress(null)
                    }}
                    className="px-4 py-2 text-white bg-dark-600 hover:bg-dark-500 rounded-lg transition-colors"
                  >
                    丢弃全部
                  </button>
                  <button
                    onClick={handleEnterReview}
                    className="px-4 py-2 bg-gradient-to-r from-blue-500 to-cyan-500 text-white rounded-lg hover:from-blue-600 hover:to-cyan-600 flex items-center gap-2 transition-all"
                  >
                    <Eye className="w-4 h-4" />
                    进入审核 ({generateProgress.passed} 条)
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => {
                      setShowGeneratePanel(false)
                      setGenerateProgress(null)
                    }}
                    className="px-4 py-2 text-white bg-dark-600 hover:bg-dark-500 rounded-lg transition-colors"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleStartGenerate}
                    className="px-4 py-2 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-lg hover:from-purple-600 hover:to-pink-600 flex items-center gap-2 transition-all"
                  >
                    <Sparkles className="w-4 h-4" />
                    开始生成
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 人工审核面板 (全屏) */}
      {showReviewPanel && (
        <div className="fixed inset-0 bg-dark-900 z-50 flex flex-col">
          {/* 审核头部 */}
          <div className="bg-dark-800 border-b border-dark-700 px-6 py-4 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center">
                <Eye className="w-4 h-4 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">数据审核</h2>
                <p className="text-xs text-gray-400">
                  逐条预览生成的对话, 批准或拒绝后入库
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-green-400 font-medium">{approvedCount} 条批准</span>
                <span className="text-gray-600">/</span>
                <span className="text-gray-400">{reviewItems.length} 条总计</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setAllReviewApproval(true)}
                  className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 transition-colors"
                >
                  全选
                </button>
                <button
                  onClick={() => setAllReviewApproval(false)}
                  className="px-3 py-1.5 text-xs bg-dark-700 text-gray-400 border border-dark-600 rounded-lg hover:bg-dark-600 transition-colors"
                >
                  全不选
                </button>
              </div>
            </div>
          </div>

          {/* 审核列表 */}
          <div className="flex-1 overflow-y-auto p-4">
            <div className="max-w-4xl mx-auto space-y-3">
              {reviewItems.map((item, idx) => (
                <div
                  key={idx}
                  className={cn(
                    'border rounded-xl transition-all',
                    item.approved
                      ? 'border-green-500/30 bg-dark-800'
                      : 'border-red-500/30 bg-dark-800 opacity-60'
                  )}
                >
                  {/* 条目头部 */}
                  <div
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                    onClick={() =>
                      setExpandedReviewIdx(expandedReviewIdx === idx ? null : idx)
                    }
                  >
                    {/* 批准/拒绝按钮 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleReviewApproval(idx)
                      }}
                      className={cn(
                        'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-colors',
                        item.approved
                          ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                          : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                      )}
                    >
                      {item.approved ? (
                        <CheckCircle2 className="w-5 h-5" />
                      ) : (
                        <XCircle className="w-5 h-5" />
                      )}
                    </button>

                    {/* 信息 */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white truncate">
                          #{idx + 1} {item.title}
                        </span>
                        <span
                          className={cn(
                            'px-2 py-0.5 text-xs rounded-full font-medium shrink-0',
                            item.category === 'savings_explain'
                              ? 'bg-blue-500/20 text-blue-400'
                              : item.category === 'rebate_query'
                              ? 'bg-green-500/20 text-green-400'
                              : item.category === 'complaint'
                              ? 'bg-red-500/20 text-red-400'
                              : item.category === 'order_problem'
                              ? 'bg-yellow-500/20 text-yellow-400'
                              : 'bg-gray-500/20 text-gray-400'
                          )}
                        >
                          {CATEGORIES.find((c) => c.id === item.category)?.name || item.category}
                        </span>
                        <span className="text-xs text-gray-500 shrink-0">
                          {item.turn_count} 条消息
                        </span>
                      </div>
                      {/* 预览首句 */}
                      {expandedReviewIdx !== idx && item.conversation_json.length > 0 && (
                        <p className="text-xs text-gray-500 mt-1 truncate">
                          {item.conversation_json[0].content.split('\n')[0]}
                        </p>
                      )}
                    </div>

                    {/* 展开/收起 */}
                    <div className="shrink-0 text-gray-500">
                      {expandedReviewIdx === idx ? (
                        <ChevronUp className="w-4 h-4" />
                      ) : (
                        <ChevronDown className="w-4 h-4" />
                      )}
                    </div>
                  </div>

                  {/* 展开的对话内容 */}
                  {expandedReviewIdx === idx && (
                    <div className="border-t border-dark-700 px-4 py-3">
                      {/* 编辑/预览切换按钮 */}
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs text-gray-500">
                          {item.edited && <span className="text-yellow-400 mr-2">* 已修改</span>}
                          {editingReviewIdx === idx ? '编辑模式 - 点击消息可修改' : '预览模式'}
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditingReviewIdx(editingReviewIdx === idx ? null : idx)
                          }}
                          className={cn(
                            'px-2.5 py-1 text-xs rounded-lg flex items-center gap-1 transition-colors',
                            editingReviewIdx === idx
                              ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                              : 'bg-dark-700 text-gray-400 border border-dark-600 hover:border-dark-500'
                          )}
                        >
                          <Pencil className="w-3 h-3" />
                          {editingReviewIdx === idx ? '完成编辑' : '编辑'}
                        </button>
                      </div>
                      <div className="space-y-2 max-h-96 overflow-y-auto">
                        {item.conversation_json.map((turn, tIdx) => (
                          <div
                            key={tIdx}
                            className={cn(
                              'p-2.5 rounded-lg text-sm',
                              turn.role === 'user'
                                ? 'bg-blue-500/10 text-blue-300'
                                : 'bg-green-500/10 text-green-300'
                            )}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <div className="font-medium text-xs opacity-60">
                                {turn.role === 'user' ? '用户' : '助手'}
                              </div>
                              {editingReviewIdx === idx && item.conversation_json.length > 2 && (
                                <button
                                  onClick={() => deleteReviewTurn(idx, tIdx)}
                                  className="p-0.5 text-red-400/60 hover:text-red-400 transition-colors"
                                  title="删除此条"
                                >
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              )}
                            </div>
                            {editingReviewIdx === idx ? (
                              <textarea
                                value={turn.content}
                                onChange={(e) => updateReviewTurnContent(idx, tIdx, e.target.value)}
                                className="w-full bg-dark-700/50 border border-dark-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                                rows={Math.max(2, turn.content.split('\n').length)}
                              />
                            ) : (
                              <div className="whitespace-pre-wrap">{turn.content}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* 审核底部操作栏 */}
          <div className="bg-dark-800 border-t border-dark-700 px-6 py-4 flex items-center justify-between shrink-0">
            <button
              onClick={() => {
                setShowReviewPanel(false)
                setReviewItems([])
                setGenerateProgress(null)
              }}
              className="px-4 py-2 text-white bg-dark-700 hover:bg-dark-600 rounded-lg transition-colors"
            >
              丢弃全部并关闭
            </button>
            <button
              onClick={handleSaveApproved}
              disabled={approvedCount === 0 || savingReview}
              className={cn(
                'px-5 py-2.5 rounded-lg flex items-center gap-2 font-medium transition-all',
                approvedCount > 0
                  ? 'bg-green-500 text-white hover:bg-green-600'
                  : 'bg-dark-700 text-gray-500 cursor-not-allowed'
              )}
            >
              <Download className="w-4 h-4" />
              {savingReview
                ? '保存中...'
                : `入库已批准的 ${approvedCount} 条`}
            </button>
          </div>
        </div>
      )}

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
