import { useState, useEffect } from 'react'
import { Plus, Edit2, Trash2, Save, X, Sparkles, CheckCircle2, Circle, Lightbulb, Play } from 'lucide-react'
import { cn } from '../utils'
import { useToast } from '../contexts/ToastContext'
import ConfirmDialog from './ConfirmDialog'
import {
  triggerExtraction,
  getArticles,
  updateArticle,
  deleteArticle,
  getExtractorStats,
  KnowledgeArticleData,
  ExtractorStats
} from '../api'

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

export default function ExtractorView() {
  const { showSuccess, showError, showInfo } = useToast()
  const [articles, setArticles] = useState<KnowledgeArticleData[]>([])
  const [stats, setStats] = useState<ExtractorStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [filterCategory, setFilterCategory] = useState<string>('')
  const [filterVerified, setFilterVerified] = useState<boolean | null>(null)
  
  // 提取弹窗状态
  const [showExtractDialog, setShowExtractDialog] = useState(false)
  const [extractSource, setExtractSource] = useState<string>('both')

  // 编辑弹窗状态
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [editingArticle, setEditingArticle] = useState<KnowledgeArticleData | null>(null)
  const [editForm, setEditForm] = useState<{
    scene: string
    scene_category: string
    customer_says: string
    recommended_response: string
    key_points: string[]
  }>({
    scene: '',
    scene_category: 'savings_explain',
    customer_says: '',
    recommended_response: '',
    key_points: []
  })

  // 确认对话框
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

  useEffect(() => {
    loadData()
  }, [filterCategory, filterVerified])

  const loadData = async () => {
    setLoading(true)
    try {
      const [articlesData, statsData] = await Promise.all([
        getArticles({
          category: filterCategory || undefined,
          verified: filterVerified !== null ? filterVerified : undefined,
          limit: 100 // 默认加载100条
        }),
        getExtractorStats()
      ])
      setArticles(articlesData)
      setStats(statsData)
    } catch (error: any) {
      console.error('加载知识提炼数据失败:', error)
      showError('加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  const handleTriggerExtraction = async () => {
    setShowExtractDialog(false)
    try {
      const res = await triggerExtraction(extractSource)
      showInfo(res.message || '知识提炼任务已启动')
      // 提炼是异步的，可以过一会儿手动刷新或轮询，这里为了简单只提示
    } catch (error: any) {
      console.error('触发提炼失败:', error)
      showError(error.response?.data?.detail || '触发提炼失败')
    }
  }

  const handleDelete = (id: number) => {
    setConfirmDialog({
      isOpen: true,
      title: '删除知识条目',
      message: '确定要删除这条提炼的知识吗？',
      onConfirm: async () => {
        try {
          await deleteArticle(id)
          showSuccess('删除成功')
          loadData()
        } catch (error) {
          console.error('删除失败:', error)
          showError('删除失败')
        }
        setConfirmDialog({ ...confirmDialog, isOpen: false })
      },
    })
  }

  const handleToggleVerify = async (article: KnowledgeArticleData) => {
    try {
      await updateArticle(article.id, { is_verified: !article.is_verified })
      showSuccess(article.is_verified ? '已取消验证' : '已标记为验证通过')
      loadData()
    } catch (error) {
      showError('修改状态失败')
    }
  }

  const openEditDialog = (article: KnowledgeArticleData) => {
    setEditingArticle(article)
    setEditForm({
      scene: article.scene || '',
      scene_category: article.scene_category || 'savings_explain',
      customer_says: article.customer_says || '',
      recommended_response: article.recommended_response || '',
      key_points: [...(article.key_points || [])]
    })
    setShowEditDialog(true)
  }

  const handleSaveEdit = async () => {
    if (!editingArticle) return
    if (!editForm.scene.trim()) {
      showError('场景描述不能为空')
      return
    }
    if (!editForm.recommended_response.trim()) {
      showError('推荐回复不能为空')
      return
    }

    try {
      await updateArticle(editingArticle.id, editForm)
      showSuccess('保存成功')
      setShowEditDialog(false)
      loadData()
    } catch (error) {
      showError('保存失败')
    }
  }

  const addKeyPoint = () => {
    setEditForm({
      ...editForm,
      key_points: [...editForm.key_points, '']
    })
  }

  const updateKeyPoint = (index: number, value: string) => {
    const newPoints = [...editForm.key_points]
    newPoints[index] = value
    setEditForm({ ...editForm, key_points: newPoints })
  }

  const removeKeyPoint = (index: number) => {
    const newPoints = editForm.key_points.filter((_, i) => i !== index)
    setEditForm({ ...editForm, key_points: newPoints })
  }

  return (
    <div className="h-full flex flex-col bg-dark-900">
      {/* 头部 */}
      <div className="bg-dark-800 border-b border-dark-700 p-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center">
            <Lightbulb className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">AI 知识提炼</h1>
        </div>
        <p className="text-gray-400 mt-2">使用大模型从历史对话中自动提炼可复用的销售经验和话术。</p>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="bg-dark-800 border-b border-dark-700 p-4">
          <div className="grid grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-accent-primary">{stats.total_articles}</div>
              <div className="text-sm text-gray-400">提取条目总数</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-400">{stats.verified_articles}</div>
              <div className="text-sm text-gray-400">已人工验证</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-400">{stats.unverified_articles}</div>
              <div className="text-sm text-gray-400">待验证</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-400">
                {(stats.avg_confidence * 100).toFixed(1)}%
              </div>
              <div className="text-sm text-gray-400">平均置信度</div>
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
          value={filterVerified === null ? '' : filterVerified.toString()}
          onChange={(e) =>
            setFilterVerified(e.target.value === '' ? null : e.target.value === 'true')
          }
          className="px-3 py-2 bg-dark-700 border border-dark-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-accent-primary"
        >
          <option value="">所有状态</option>
          <option value="true">已验证</option>
          <option value="false">未验证</option>
        </select>

        <div className="flex-1" />

        <button
          onClick={() => loadData()}
          className="px-4 py-2 border border-dark-600 text-gray-300 rounded-lg hover:bg-dark-700 transition-colors text-sm"
        >
          刷新
        </button>

        <button
          onClick={() => setShowExtractDialog(true)}
          className="px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 text-white rounded-lg hover:from-indigo-600 hover:to-purple-700 flex items-center gap-2 transition-all shadow-lg shadow-indigo-500/20"
        >
          <Sparkles className="w-4 h-4" />
          触发自动提炼
        </button>
      </div>

      {/* 知识列表 */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
        {loading ? (
          <div className="text-center py-20 text-gray-500">加载中...</div>
        ) : articles.length === 0 ? (
          <div className="text-center py-20 text-gray-500">
            <Lightbulb className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p>暂无提炼的知识条目，点击右上角"触发自动提炼"从历史数据中生成。</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
            {articles.map((article) => (
              <div
                key={article.id}
                className={cn(
                  "bg-dark-800 border rounded-xl p-5 flex flex-col transition-all hover:border-dark-500",
                  article.is_verified ? 'border-dark-600 shadow-md' : 'border-dark-700/50 opacity-80'
                )}
              >
                {/* 卡片头部 */}
                <div className="flex justify-between items-start mb-4">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "px-2.5 py-1 text-xs rounded-md font-medium flex items-center gap-1",
                        article.scene_category === 'savings_explain' ? 'bg-blue-500/20 text-blue-400'
                        : article.scene_category === 'rebate_query' ? 'bg-green-500/20 text-green-400'
                        : article.scene_category === 'complaint' ? 'bg-red-500/20 text-red-400'
                        : 'bg-gray-500/20 text-gray-400'
                      )}
                    >
                      {CATEGORIES.find((c) => c.id === article.scene_category)?.name || article.scene_category || '通用'}
                    </span>
                    <span 
                      className={cn(
                        "text-xs font-mono px-2 py-1 rounded-md bg-dark-700/50",
                        article.confidence > 0.8 ? "text-green-400" : article.confidence > 0.6 ? "text-yellow-400" : "text-gray-400"
                      )}
                      title="AI提炼置信度"
                    >
                      {(article.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleToggleVerify(article)}
                      className={cn(
                        "p-1.5 rounded-lg transition-colors flex items-center justify-center",
                        article.is_verified 
                          ? 'text-green-500 hover:bg-green-500/10' 
                          : 'text-gray-500 hover:text-green-400 hover:bg-dark-700'
                      )}
                      title={article.is_verified ? '已验证 - 点击取消' : '标为已验证'}
                    >
                      {article.is_verified ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                    </button>
                    <button
                      onClick={() => openEditDialog(article)}
                      className="p-1.5 text-blue-400 hover:bg-blue-500/10 rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(article.id)}
                      className="p-1.5 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* 卡片内容 */}
                <div className="flex-1 space-y-4">
                  <div>
                    <h3 className="text-white font-medium text-sm mb-1 leading-snug">
                      {article.scene}
                    </h3>
                  </div>

                  {article.customer_says && (
                    <div className="bg-dark-700/50 rounded-lg p-3 relative before:absolute before:left-0 before:top-3 before:bottom-3 before:w-1 before:bg-orange-500/50 before:rounded-r-md">
                      <div className="text-xs text-gray-500 mb-1 ml-1">客户:</div>
                      <p className="text-orange-100/80 text-sm ml-1">"{article.customer_says}"</p>
                    </div>
                  )}

                  <div className="bg-blue-900/10 rounded-lg p-3 border border-blue-500/10">
                    <div className="text-xs text-blue-400/80 mb-1">推荐话术:</div>
                    <p className="text-blue-100 text-sm whitespace-pre-wrap">{article.recommended_response}</p>
                  </div>

                  {article.key_points && Array.isArray(article.key_points) && article.key_points.length > 0 && (
                    <div>
                      <div className="text-xs text-gray-500 mb-2">提炼要点:</div>
                      <ul className="space-y-1.5">
                        {article.key_points.map((point, idx) => (
                          <li key={idx} className="text-xs text-gray-300 flex items-start gap-2">
                            <span className="text-indigo-400 mt-0.5">•</span>
                            <span>{point}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 触发提炼弹窗 */}
      {showExtractDialog && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <div className="bg-dark-800 rounded-xl shadow-2xl w-full max-w-md border border-dark-600 overflow-hidden">
            <div className="p-5 border-b border-dark-700 flex justify-between items-center bg-gradient-to-r from-dark-800 to-dark-750">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-indigo-400" />
                启动知识提炼任务
              </h2>
              <button 
                onClick={() => setShowExtractDialog(false)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6">
              <p className="text-gray-300 text-sm mb-6">
                系统将调用大模型，后台遍历所选的数据源，自动提取可复用的销售经验和应对策略。此操作可能需要较长时间。
              </p>
              
              <div className="space-y-3">
                <label className="block text-sm font-medium text-gray-400">选择数据来源：</label>
                
                <div 
                  className={cn("p-3 rounded-lg border cursor-pointer transition-colors flex gap-3", 
                    extractSource === 'labeled' ? "border-indigo-500 bg-indigo-500/10" : "border-dark-600 bg-dark-700/50 hover:bg-dark-700"
                  )}
                  onClick={() => setExtractSource('labeled')}
                >
                  <div className="mt-0.5"><div className={cn("w-4 h-4 rounded-full border-2 flex items-center justify-center", extractSource === 'labeled' ? "border-indigo-500" : "border-gray-500")}><div className={cn("w-2 h-2 rounded-full", extractSource === 'labeled' ? "bg-indigo-500" : "bg-transparent")}/></div></div>
                  <div>
                    <div className={cn("text-sm font-medium", extractSource === 'labeled' ? "text-indigo-300" : "text-gray-300")}>已审核数据 (Labeled)</div>
                    <div className="text-xs text-gray-500 mt-1">仅处理人工通过审核的高质量数据，提炼效果好（推荐）</div>
                  </div>
                </div>

                <div 
                  className={cn("p-3 rounded-lg border cursor-pointer transition-colors flex gap-3", 
                    extractSource === 'both' ? "border-indigo-500 bg-indigo-500/10" : "border-dark-600 bg-dark-700/50 hover:bg-dark-700"
                  )}
                  onClick={() => setExtractSource('both')}
                >
                   <div className="mt-0.5"><div className={cn("w-4 h-4 rounded-full border-2 flex items-center justify-center", extractSource === 'both' ? "border-indigo-500" : "border-gray-500")}><div className={cn("w-2 h-2 rounded-full", extractSource === 'both' ? "bg-indigo-500" : "bg-transparent")}/></div></div>
                  <div>
                    <div className={cn("text-sm font-medium", extractSource === 'both' ? "text-indigo-300" : "text-gray-300")}>所有可提炼数据</div>
                    <div className="text-xs text-gray-500 mt-1">包含已审核数据和 AI 切分的初始对话块。速度较慢，提炼条目多。</div>
                  </div>
                </div>
              </div>
            </div>

            <div className="p-5 border-t border-dark-700 bg-dark-850 flex justify-end gap-3">
              <button 
                onClick={() => setShowExtractDialog(false)}
                className="px-4 py-2 text-gray-400 hover:text-white transition-colors text-sm font-medium"
              >
                取消
              </button>
              <button 
                onClick={handleTriggerExtraction}
                className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg flex items-center gap-2 transition-colors text-sm font-medium shadow-md shadow-indigo-900/20"
              >
                <Play className="w-4 h-4" />
                开始后台提炼
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 编辑弹窗 */}
      {showEditDialog && editingArticle && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-dark-800 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden border border-dark-600 flex flex-col">
            <div className="p-5 border-b border-dark-700 flex justify-between items-center bg-dark-750">
              <h2 className="text-lg font-bold text-white">
                编辑知识条目 #{editingArticle.id}
              </h2>
              <button 
                onClick={() => setShowEditDialog(false)}
                className="text-gray-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto flex-1 space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">场景描述 *</label>
                <textarea
                  value={editForm.scene}
                  onChange={e => setEditForm({...editForm, scene: e.target.value})}
                  className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded-lg text-white focus:ring-2 focus:ring-accent-primary focus:border-transparent outline-none transition-all"
                  rows={2}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-2">分类 *</label>
                  <select
                    value={editForm.scene_category}
                    onChange={e => setEditForm({...editForm, scene_category: e.target.value})}
                    className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded-lg text-white outline-none"
                  >
                    {CATEGORIES.map((cat) => (
                      <option key={cat.id} value={cat.id}>{cat.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">客户原话 (可选)</label>
                <textarea
                  value={editForm.customer_says}
                  onChange={e => setEditForm({...editForm, customer_says: e.target.value})}
                  className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded-lg text-orange-200 focus:ring-2 focus:ring-orange-500/50 outline-none transition-all"
                  rows={2}
                  placeholder="客户典型的提问或异议..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">推荐回复话术 *</label>
                <textarea
                  value={editForm.recommended_response}
                  onChange={e => setEditForm({...editForm, recommended_response: e.target.value})}
                  className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded-lg text-blue-200 focus:ring-2 focus:ring-blue-500/50 outline-none transition-all"
                  rows={4}
                />
              </div>

              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-sm font-medium text-gray-400">提炼要点 (可选)</label>
                  <button onClick={addKeyPoint} className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
                    <Plus className="w-3 h-3" /> 添加要点
                  </button>
                </div>
                
                {editForm.key_points.length === 0 ? (
                  <div className="text-sm text-gray-500 italic p-3 bg-dark-900 rounded-lg border border-dark-700 text-center">
                    暂无要点
                  </div>
                ) : (
                  <div className="space-y-2">
                    {editForm.key_points.map((point, idx) => (
                      <div key={idx} className="flex gap-2">
                        <input
                          value={point}
                          onChange={e => updateKeyPoint(idx, e.target.value)}
                          className="flex-1 px-3 py-2 bg-dark-900 border border-dark-600 rounded-lg text-sm text-white focus:border-indigo-500 outline-none"
                          placeholder="输入要点内容..."
                        />
                        <button 
                          onClick={() => removeKeyPoint(idx)}
                          className="p-2 text-gray-500 hover:text-red-400 hover:bg-dark-700 rounded-lg"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="p-4 border-t border-dark-700 bg-dark-800 flex justify-end gap-3">
              <button 
                onClick={() => setShowEditDialog(false)}
                className="px-4 py-2 bg-dark-700 text-white rounded-lg hover:bg-dark-600 transition-colors text-sm"
              >
                取消
              </button>
              <button 
                onClick={handleSaveEdit}
                className="px-5 py-2 bg-accent-primary hover:bg-accent-secondary text-white rounded-lg flex items-center gap-2 transition-colors text-sm font-medium shadow-md shadow-accent-primary/20"
              >
                <Save className="w-4 h-4" />
                保存修改
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 确认弹窗 */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}
        confirmText="删除"
        cancelText="取消"
      />
    </div>
  )
}
