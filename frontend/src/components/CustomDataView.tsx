import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Edit2, Trash2, Power, PowerOff, Save, X, Database, Sparkles, Square, Download, XCircle, Eye, CheckCircle2, ChevronDown, ChevronUp, Pencil } from 'lucide-react'
import { StatCard, ChartFrame, StatusDonut, CategoryBars, toChartData } from './ui'
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
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="bg-panel/50 border-b border-line p-6 backdrop-blur-xl">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-iris to-flare flex items-center justify-center">
            <Database className="w-5 h-5 text-ink" />
          </div>
          <h1 className="text-3xl font-bold text-ink">自定义对话数据管理</h1>
        </div>
        <p className="text-ink-muted mt-2">手动添加高质量对话数据，可直接用于训练导出</p>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="px-6 pb-2">
          <motion.div
            initial="hidden"
            animate="show"
            transition={{ staggerChildren: 0.05 }}
            className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5"
          >
            <StatCard label="总数" value={stats.total} hint="自定义对话" icon={<Database size={17} />} tone="iris" />
            <StatCard label="已启用" value={stats.active} hint="可用于训练导出" icon={<CheckCircle2 size={17} />} tone="mint" />
            <StatCard label="已禁用" value={stats.inactive} hint="暂不参与导出" icon={<XCircle size={17} />} tone="flare" />
            <StatCard label="分类数" value={Object.keys(stats.by_category).length} hint="覆盖业务场景" icon={<Square size={17} />} tone="iris" />
            <StatCard label="高质量" value={stats.by_quality.high || 0} hint="人工确认高质量" icon={<Sparkles size={17} />} tone="mint" />
          </motion.div>

          {/* 分布图：来自自定义对话统计接口当前快照 */}
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <ChartFrame title="业务分类分布" subtitle="按对话数 · 当前快照">
              <CategoryBars
                data={toChartData(stats.by_category, Object.fromEntries(CATEGORIES.map((c) => [c.id, c.name])))}
                unit=" 条"
              />
            </ChartFrame>
            <ChartFrame title="质量等级构成" subtitle="按对话数 · 当前快照">
              <StatusDonut
                data={toChartData(stats.by_quality, Object.fromEntries(QUALITIES.map((q) => [q.id, q.name])))}
                centerLabel="对话总数"
                unit=" 条"
              />
            </ChartFrame>
          </div>
        </div>
      )}

      {/* 筛选和操作栏 */}
      <div className="bg-panel/40 border-b border-line p-4 flex items-center gap-4 backdrop-blur-xl">
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="px-3 py-2 bg-panel-2 border border-line rounded-lg text-sm text-ink focus:outline-none focus:ring-2 focus:ring-iris"
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
          className="px-3 py-2 bg-panel-2 border border-line rounded-lg text-sm text-ink focus:outline-none focus:ring-2 focus:ring-iris"
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
          className="px-3 py-2 bg-panel-2 border border-line rounded-lg text-sm text-ink focus:outline-none focus:ring-2 focus:ring-iris"
        >
          <option value="">全部状态</option>
          <option value="true">已启用</option>
          <option value="false">已禁用</option>
        </select>

        <div className="flex-1" />

        <button
          onClick={() => setShowGeneratePanel(true)}
          className="px-4 py-2 bg-gradient-to-r from-iris to-flare text-ink rounded-lg hover:from-iris hover:to-flare flex items-center gap-2 transition-all"
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
          className="px-4 py-2 bg-iris text-ink rounded-lg hover:bg-flare flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          新增对话
        </button>
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="text-center py-20 text-ink-subtle">加载中...</div>
        ) : conversations.length === 0 ? (
          <div className="text-center py-20 text-ink-subtle">暂无数据</div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={cn(
                  "bg-panel border rounded-xl p-4 transition-all",
                  conv.is_active ? 'border-panel-2' : 'border-panel-2 opacity-60'
                )}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-medium text-ink">
                        {conv.title || `对话 #${conv.id}`}
                      </h3>
                      <span
                        className={cn(
                          "px-2 py-0.5 text-xs rounded-full font-medium",
                          conv.category === 'savings_explain'
                            ? 'bg-iris/20 text-info'
                            : conv.category === 'rebate_query'
                            ? 'bg-ok/20 text-ok'
                            : conv.category === 'complaint'
                            ? 'bg-bad/20 text-bad'
                            : 'bg-panel-2/20 text-ink-muted'
                        )}
                      >
                        {CATEGORIES.find((c) => c.id === conv.category)?.name || conv.category}
                      </span>
                      <span
                        className={cn(
                          "px-2 py-0.5 text-xs rounded-full font-medium",
                          conv.quality === 'high'
                            ? 'bg-ok/20 text-ok'
                            : conv.quality === 'medium'
                            ? 'bg-warn/20 text-warn'
                            : 'bg-panel-2/20 text-ink-muted'
                        )}
                      >
                        {QUALITIES.find((q) => q.id === conv.quality)?.name || conv.quality}
                      </span>
                    </div>
                    {conv.description && (
                      <p className="text-sm text-ink-muted mb-2">{conv.description}</p>
                    )}
                    <div className="text-xs text-ink-subtle">
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
                          ? 'text-ok hover:bg-ok/10'
                          : 'text-ink-subtle hover:bg-panel-2'
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
                      className="p-2 text-iris hover:bg-iris/10 rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(conv.id)}
                      className="p-2 text-bad hover:bg-bad/10 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* 对话预览 */}
                <div className="space-y-2 bg-panel-2 rounded-lg p-3 max-h-60 overflow-y-auto">
                  {conv.system_prompt && (
                    <div className="p-2 rounded-lg text-sm bg-iris/20 text-iris">
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
                          ? 'bg-iris/20 text-info'
                          : turn.role === 'assistant'
                          ? 'bg-ok/20 text-ok'
                          : 'bg-warn/20 text-warn'
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
        <div className="fixed inset-0 bg-scrim/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-panel rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto border border-panel-2">
            <div className="sticky top-0 bg-panel-2 border-b border-line px-6 py-4 flex justify-between items-center">
              <h2 className="text-xl font-bold text-ink">
                {editingId ? '编辑对话' : '新增对话'}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingId(null)
                  resetForm()
                }}
                className="p-2 hover:bg-line rounded-lg text-ink-muted hover:text-ink transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* 基本信息 */}
              <div>
                <label className="block text-sm font-medium text-ink mb-2">
                  标题（可选）
                </label>
                <input
                  type="text"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  className="w-full px-3 py-2 bg-panel-2 border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-iris"
                  placeholder="为这个对话起一个标题"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-ink mb-2">
                  描述（可选）
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 bg-panel-2 border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-iris"
                  placeholder="描述这个对话的用途或特点"
                  rows={2}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-ink mb-2">
                  系统提示词（可选）
                </label>
                <textarea
                  value={formData.systemPrompt}
                  onChange={(e) => setFormData({ ...formData, systemPrompt: e.target.value })}
                  className="w-full px-3 py-2 bg-panel-2 border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-iris"
                  placeholder="自定义系统提示词，留空则导出时使用分类默认提示词"
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-ink mb-2">
                    分类 *
                  </label>
                  <select
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    className="w-full px-3 py-2 bg-panel-2 border border-line rounded-lg text-ink focus:outline-none focus:ring-2 focus:ring-iris"
                  >
                    {CATEGORIES.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-ink mb-2">
                    质量 *
                  </label>
                  <select
                    value={formData.quality}
                    onChange={(e) => setFormData({ ...formData, quality: e.target.value })}
                    className="w-full px-3 py-2 bg-panel-2 border border-line rounded-lg text-ink focus:outline-none focus:ring-2 focus:ring-iris"
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
                  <label className="block text-sm font-medium text-ink">
                    对话内容 *（至少 2 轮）
                  </label>
                  <button
                    onClick={addTurn}
                    className="px-3 py-1 text-sm bg-line hover:bg-line-strong text-ink rounded-lg flex items-center gap-1 transition-colors"
                  >
                    <Plus className="w-3 h-3" />
                    添加轮次
                  </button>
                </div>

                <div className="space-y-3">
                  {formData.turns.map((turn, idx) => (
                    <div key={idx} className="border border-line rounded-lg p-4 bg-panel-2">
                      <div className="flex justify-between items-center mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-ink">
                            第 {idx + 1} 轮
                          </span>
                          <select
                            value={turn.role}
                            onChange={(e) =>
                              updateTurn(idx, 'role', e.target.value)
                            }
                            className="px-2 py-1 text-sm bg-line border border-line-strong rounded text-ink focus:outline-none focus:ring-2 focus:ring-iris"
                          >
                            <option value="user">用户</option>
                            <option value="assistant">助手</option>
                            <option value="system">系统</option>
                          </select>
                        </div>
                        {formData.turns.length > 2 && (
                          <button
                            onClick={() => removeTurn(idx)}
                            className="p-1 text-bad hover:bg-bad/10 rounded transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                      <textarea
                        value={turn.content}
                        onChange={(e) => updateTurn(idx, 'content', e.target.value)}
                        className="w-full px-3 py-2 bg-line border border-line-strong rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-iris"
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
            <div className="sticky bottom-0 bg-panel-2 border-t border-line px-6 py-4 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingId(null)
                  resetForm()
                }}
                className="px-4 py-2 text-ink bg-line hover:bg-line-strong rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={editingId ? handleUpdate : handleCreate}
                className="px-4 py-2 bg-iris text-ink rounded-lg hover:bg-flare flex items-center gap-2 transition-colors"
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
        <div className="fixed inset-0 bg-scrim/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-panel rounded-xl shadow-2xl w-full max-w-lg border border-panel-2">
            <div className="bg-panel-2 border-b border-line px-6 py-4 flex justify-between items-center rounded-t-xl">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-iris" />
                <h2 className="text-xl font-bold text-ink">AI 批量生成</h2>
              </div>
              <button
                onClick={() => {
                  if (!isPolling) {
                    setShowGeneratePanel(false)
                    setGenerateProgress(null)
                  }
                }}
                className="p-2 hover:bg-line rounded-lg text-ink-muted hover:text-ink transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-5">
              {/* 数量配置 */}
              <div>
                <label className="block text-sm font-medium text-ink mb-2">
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
                  className="w-full px-3 py-2 bg-panel-2 border border-line rounded-lg text-ink focus:outline-none focus:ring-2 focus:ring-iris disabled:opacity-50"
                />
              </div>

              {/* 分类选择 */}
              <div>
                <label className="block text-sm font-medium text-ink mb-2">
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
                          ? 'bg-iris/30 border-iris text-iris'
                          : 'bg-panel-2 border-line text-ink-muted hover:border-line-strong',
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
                <div className="bg-panel-2 rounded-lg p-4 space-y-3">
                  <div className="flex justify-between text-sm">
                    <span className="text-ink-muted">
                      {generateProgress.is_running ? '生成中...' : '生成完成'}
                    </span>
                    <span className="text-ink">
                      {generateProgress.completed} / {generateProgress.total}
                    </span>
                  </div>

                  {/* 进度条 */}
                  <div className="w-full bg-line rounded-full h-2.5">
                    <div
                      className="bg-gradient-to-r from-iris to-flare h-2.5 rounded-full transition-all duration-300"
                      style={{
                        width: `${generateProgress.total > 0 ? (generateProgress.completed / generateProgress.total) * 100 : 0}%`,
                      }}
                    />
                  </div>

                  {/* 统计 */}
                  <div className="grid grid-cols-3 gap-3 text-center">
                    <div>
                      <div className="text-lg font-bold text-ok">
                        {generateProgress.passed}
                      </div>
                      <div className="text-xs text-ink-subtle">通过校验</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-bad">
                        {generateProgress.failed}
                      </div>
                      <div className="text-xs text-ink-subtle">未通过</div>
                    </div>
                    <div>
                      <div className="text-lg font-bold text-ink-muted">
                        {generateProgress.total - generateProgress.completed}
                      </div>
                      <div className="text-xs text-ink-subtle">剩余</div>
                    </div>
                  </div>

                  {generateProgress.error_count > 0 && (
                    <div className="text-xs text-bad mt-1">
                      {generateProgress.errors[0]}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 底部按钮 */}
            <div className="bg-panel-2 border-t border-line px-6 py-4 flex justify-end gap-3 rounded-b-xl">
              {isPolling ? (
                <button
                  onClick={handleStopGenerate}
                  className="px-4 py-2 bg-bad/20 text-bad border border-bad/30 rounded-lg hover:bg-bad/30 flex items-center gap-2 transition-colors"
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
                    className="px-4 py-2 text-ink bg-line hover:bg-line-strong rounded-lg transition-colors"
                  >
                    丢弃全部
                  </button>
                  <button
                    onClick={handleEnterReview}
                    className="px-4 py-2 bg-gradient-to-r from-iris to-iris text-ink rounded-lg hover:from-iris hover:to-iris flex items-center gap-2 transition-all"
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
                    className="px-4 py-2 text-ink bg-line hover:bg-line-strong rounded-lg transition-colors"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleStartGenerate}
                    className="px-4 py-2 bg-gradient-to-r from-iris to-flare text-ink rounded-lg hover:from-iris hover:to-flare flex items-center gap-2 transition-all"
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
        <div className="fixed inset-0 bg-canvas z-50 flex flex-col">
          {/* 审核头部 */}
          <div className="bg-panel border-b border-panel-2 px-6 py-4 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-iris to-iris flex items-center justify-center">
                <Eye className="w-4 h-4 text-ink" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-ink">数据审核</h2>
                <p className="text-xs text-ink-muted">
                  逐条预览生成的对话, 批准或拒绝后入库
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-ok font-medium">{approvedCount} 条批准</span>
                <span className="text-ink-subtle">/</span>
                <span className="text-ink-muted">{reviewItems.length} 条总计</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setAllReviewApproval(true)}
                  className="px-3 py-1.5 text-xs bg-ok/10 text-ok border border-ok/30 rounded-lg hover:bg-ok/20 transition-colors"
                >
                  全选
                </button>
                <button
                  onClick={() => setAllReviewApproval(false)}
                  className="px-3 py-1.5 text-xs bg-panel-2 text-ink-muted border border-line rounded-lg hover:bg-line transition-colors"
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
                      ? 'border-ok/30 bg-panel'
                      : 'border-bad/30 bg-panel opacity-60'
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
                          ? 'bg-ok/20 text-ok hover:bg-ok/30'
                          : 'bg-bad/20 text-bad hover:bg-bad/30'
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
                        <span className="text-sm font-medium text-ink truncate">
                          #{idx + 1} {item.title}
                        </span>
                        <span
                          className={cn(
                            'px-2 py-0.5 text-xs rounded-full font-medium shrink-0',
                            item.category === 'savings_explain'
                              ? 'bg-iris/20 text-info'
                              : item.category === 'rebate_query'
                              ? 'bg-ok/20 text-ok'
                              : item.category === 'complaint'
                              ? 'bg-bad/20 text-bad'
                              : item.category === 'order_problem'
                              ? 'bg-warn/20 text-warn'
                              : 'bg-panel-2/20 text-ink-muted'
                          )}
                        >
                          {CATEGORIES.find((c) => c.id === item.category)?.name || item.category}
                        </span>
                        <span className="text-xs text-ink-subtle shrink-0">
                          {item.turn_count} 条消息
                        </span>
                      </div>
                      {/* 预览首句 */}
                      {expandedReviewIdx !== idx && item.conversation_json.length > 0 && (
                        <p className="text-xs text-ink-subtle mt-1 truncate">
                          {item.conversation_json[0].content.split('\n')[0]}
                        </p>
                      )}
                    </div>

                    {/* 展开/收起 */}
                    <div className="shrink-0 text-ink-subtle">
                      {expandedReviewIdx === idx ? (
                        <ChevronUp className="w-4 h-4" />
                      ) : (
                        <ChevronDown className="w-4 h-4" />
                      )}
                    </div>
                  </div>

                  {/* 展开的对话内容 */}
                  {expandedReviewIdx === idx && (
                    <div className="border-t border-panel-2 px-4 py-3">
                      {/* 编辑/预览切换按钮 */}
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs text-ink-subtle">
                          {item.edited && <span className="text-warn mr-2">* 已修改</span>}
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
                              ? 'bg-warn/20 text-warn border border-warn/30'
                              : 'bg-panel-2 text-ink-muted border border-line hover:border-line-strong'
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
                                ? 'bg-iris/10 text-info'
                                : 'bg-ok/10 text-ok'
                            )}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <div className="font-medium text-xs opacity-60">
                                {turn.role === 'user' ? '用户' : '助手'}
                              </div>
                              {editingReviewIdx === idx && item.conversation_json.length > 2 && (
                                <button
                                  onClick={() => deleteReviewTurn(idx, tIdx)}
                                  className="p-0.5 text-bad/60 hover:text-bad transition-colors"
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
                                className="w-full bg-panel-2/50 border border-line rounded px-2 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-iris resize-none"
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
          <div className="bg-panel border-t border-panel-2 px-6 py-4 flex items-center justify-between shrink-0">
            <button
              onClick={() => {
                setShowReviewPanel(false)
                setReviewItems([])
                setGenerateProgress(null)
              }}
              className="px-4 py-2 text-ink bg-panel-2 hover:bg-line rounded-lg transition-colors"
            >
              丢弃全部并关闭
            </button>
            <button
              onClick={handleSaveApproved}
              disabled={approvedCount === 0 || savingReview}
              className={cn(
                'px-5 py-2.5 rounded-lg flex items-center gap-2 font-medium transition-all',
                approvedCount > 0
                  ? 'bg-ok text-ink hover:bg-ok'
                  : 'bg-panel-2 text-ink-subtle cursor-not-allowed'
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
