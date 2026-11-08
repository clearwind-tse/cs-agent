import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Edit2, Trash2, Save, X, Sparkles, CheckCircle2, Circle, Lightbulb, Play } from 'lucide-react'
import { StatCard, ChartFrame, StatusDonut, CategoryBars, toChartData } from './ui'
import { cn } from '../utils'
import { useToast } from '../contexts/ToastContext'
import ConfirmDialog from './ConfirmDialog'
import TimeRangeFilter from './TimeRangeFilter'
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
  const [startTime, setStartTime] = useState<number | null>(null)
  const [endTime, setEndTime] = useState<number | null>(null)
  
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
  }, [filterCategory, filterVerified, startTime, endTime])

  const loadData = async () => {
    setLoading(true)
    try {
      const [articlesData, statsData] = await Promise.all([
        getArticles({
          category: filterCategory || undefined,
          verified: filterVerified !== null ? filterVerified : undefined,
          start_time: startTime ?? undefined,
          end_time: endTime ?? undefined,
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
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="bg-panel/50 border-b border-line p-6 backdrop-blur-xl">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-iris to-iris flex items-center justify-center">
            <Lightbulb className="w-5 h-5 text-ink" />
          </div>
          <h1 className="text-3xl font-bold text-ink">AI 知识提炼</h1>
        </div>
        <p className="text-ink-muted mt-2">使用大模型从历史对话中自动提炼可复用的销售经验和话术。</p>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="px-6 pb-2">
          <motion.div
            initial="hidden"
            animate="show"
            transition={{ staggerChildren: 0.05 }}
            className="grid grid-cols-2 gap-4 lg:grid-cols-4"
          >
            <StatCard
              label="提取条目总数"
              value={stats.total_articles}
              hint="知识库当前条目"
              icon={<Lightbulb size={17} />}
              tone="iris"
            />
            <StatCard
              label="已人工验证"
              value={stats.verified_articles}
              hint="人工确认可用"
              icon={<CheckCircle2 size={17} />}
              tone="mint"
            />
            <StatCard
              label="待验证"
              value={stats.unverified_articles}
              hint="等待人工确认"
              icon={<Circle size={17} />}
              tone="flare"
            />
            <StatCard
              label="平均置信度"
              value={`${(stats.avg_confidence * 100).toFixed(1)}%`}
              hint="模型自评均值"
              icon={<Sparkles size={17} />}
              tone="iris"
            />
          </motion.div>

          {/* 分布图：来自 /api/extractor/stats 当前快照 */}
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <ChartFrame title="知识类别分布" subtitle="按提炼条目数 · 当前快照">
              <CategoryBars
                data={toChartData(
                  stats.by_category,
                  Object.fromEntries(CATEGORIES.map((c) => [c.id, c.name])),
                )}
                unit=" 条"
              />
            </ChartFrame>
            <ChartFrame title="人工核验进度" subtitle="已验证 / 待验证 · 当前快照">
              <StatusDonut
                data={[
                  { name: '已验证', value: stats.verified_articles },
                  { name: '待验证', value: stats.unverified_articles },
                ]}
                centerLabel="知识条目"
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
          value={filterVerified === null ? '' : filterVerified.toString()}
          onChange={(e) =>
            setFilterVerified(e.target.value === '' ? null : e.target.value === 'true')
          }
          className="px-3 py-2 bg-panel-2 border border-line rounded-lg text-sm text-ink focus:outline-none focus:ring-2 focus:ring-iris"
        >
          <option value="">所有状态</option>
          <option value="true">已验证</option>
          <option value="false">未验证</option>
        </select>

        <TimeRangeFilter
          startTime={startTime}
          endTime={endTime}
          onChange={(s, e) => { setStartTime(s ?? null); setEndTime(e ?? null) }}
        />

        <div className="flex-1" />

        <button
          onClick={() => loadData()}
          className="px-4 py-2 border border-line text-ink rounded-lg hover:bg-panel-2 transition-colors text-sm"
        >
          刷新
        </button>

        <button
          onClick={() => setShowExtractDialog(true)}
          className="px-4 py-2 bg-gradient-to-r from-iris to-iris text-ink rounded-lg hover:from-iris hover:to-iris flex items-center gap-2 transition-all shadow-lg shadow-indigo-500/20"
        >
          <Sparkles className="w-4 h-4" />
          触发自动提炼
        </button>
      </div>

      {/* 知识列表 */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
        {loading ? (
          <div className="text-center py-20 text-ink-subtle">加载中...</div>
        ) : articles.length === 0 ? (
          <div className="text-center py-20 text-ink-subtle">
            <Lightbulb className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p>暂无提炼的知识条目，点击右上角"触发自动提炼"从历史数据中生成。</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
            {articles.map((article) => (
              <div
                key={article.id}
                className={cn(
                  "bg-panel border rounded-xl p-5 flex flex-col transition-all hover:border-line-strong",
                  article.is_verified ? 'border-line shadow-md' : 'border-panel-2/50 opacity-80'
                )}
              >
                {/* 卡片头部 */}
                <div className="flex justify-between items-start mb-4">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "px-2.5 py-1 text-xs rounded-md font-medium flex items-center gap-1",
                        article.scene_category === 'savings_explain' ? 'bg-iris/20 text-info'
                        : article.scene_category === 'rebate_query' ? 'bg-ok/20 text-ok'
                        : article.scene_category === 'complaint' ? 'bg-bad/20 text-bad'
                        : 'bg-panel-2/20 text-ink-muted'
                      )}
                    >
                      {CATEGORIES.find((c) => c.id === article.scene_category)?.name || article.scene_category || '通用'}
                    </span>
                    <span 
                      className={cn(
                        "text-xs font-mono px-2 py-1 rounded-md bg-panel-2/50",
                        article.confidence > 0.8 ? "text-ok" : article.confidence > 0.6 ? "text-warn" : "text-ink-muted"
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
                          ? 'text-ok hover:bg-ok/10' 
                          : 'text-ink-subtle hover:text-ok hover:bg-panel-2'
                      )}
                      title={article.is_verified ? '已验证 - 点击取消' : '标为已验证'}
                    >
                      {article.is_verified ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                    </button>
                    <button
                      onClick={() => openEditDialog(article)}
                      className="p-1.5 text-info hover:bg-iris/10 rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(article.id)}
                      className="p-1.5 text-bad hover:bg-bad/10 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* 卡片内容 */}
                <div className="flex-1 space-y-4">
                  <div>
                    <h3 className="text-ink font-medium text-sm mb-1 leading-snug">
                      {article.scene}
                    </h3>
                  </div>

                  {article.customer_says && (
                    <div className="bg-panel-2/50 rounded-lg p-3 relative before:absolute before:left-0 before:top-3 before:bottom-3 before:w-1 before:bg-warn/50 before:rounded-r-md">
                      <div className="text-xs text-ink-subtle mb-1 ml-1">客户:</div>
                      <p className="text-warn/80 text-sm ml-1">"{article.customer_says}"</p>
                    </div>
                  )}

                  <div className="bg-iris/10 rounded-lg p-3 border border-iris/10">
                    <div className="text-xs text-info/80 mb-1">推荐话术:</div>
                    <p className="text-info text-sm whitespace-pre-wrap">{article.recommended_response}</p>
                  </div>

                  {article.key_points && Array.isArray(article.key_points) && article.key_points.length > 0 && (
                    <div>
                      <div className="text-xs text-ink-subtle mb-2">提炼要点:</div>
                      <ul className="space-y-1.5">
                        {article.key_points.map((point, idx) => (
                          <li key={idx} className="text-xs text-ink flex items-start gap-2">
                            <span className="text-iris mt-0.5">•</span>
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
        <div className="fixed inset-0 bg-scrim/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="bg-panel rounded-xl shadow-2xl w-full max-w-md border border-line overflow-hidden">
            <div className="p-5 border-b border-panel-2 flex justify-between items-center bg-gradient-to-r from-panel to-panel-2">
              <h2 className="text-lg font-bold text-ink flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-iris" />
                启动知识提炼任务
              </h2>
              <button 
                onClick={() => setShowExtractDialog(false)}
                className="text-ink-muted hover:text-ink"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6">
              <p className="text-ink text-sm mb-6">
                系统将调用大模型，后台遍历所选的数据源，自动提取可复用的销售经验和应对策略。此操作可能需要较长时间。
              </p>
              
              <div className="space-y-3">
                <label className="block text-sm font-medium text-ink-muted">选择数据来源：</label>
                
                <div 
                  className={cn("p-3 rounded-lg border cursor-pointer transition-colors flex gap-3", 
                    extractSource === 'labeled' ? "border-iris bg-iris/10" : "border-line bg-panel-2/50 hover:bg-panel-2"
                  )}
                  onClick={() => setExtractSource('labeled')}
                >
                  <div className="mt-0.5"><div className={cn("w-4 h-4 rounded-full border-2 flex items-center justify-center", extractSource === 'labeled' ? "border-iris" : "border-line")}><div className={cn("w-2 h-2 rounded-full", extractSource === 'labeled' ? "bg-iris" : "bg-transparent")}/></div></div>
                  <div>
                    <div className={cn("text-sm font-medium", extractSource === 'labeled' ? "text-iris" : "text-ink")}>已审核数据 (Labeled)</div>
                    <div className="text-xs text-ink-subtle mt-1">仅处理人工通过审核的高质量数据，提炼效果好（推荐）</div>
                  </div>
                </div>

                <div 
                  className={cn("p-3 rounded-lg border cursor-pointer transition-colors flex gap-3", 
                    extractSource === 'both' ? "border-iris bg-iris/10" : "border-line bg-panel-2/50 hover:bg-panel-2"
                  )}
                  onClick={() => setExtractSource('both')}
                >
                   <div className="mt-0.5"><div className={cn("w-4 h-4 rounded-full border-2 flex items-center justify-center", extractSource === 'both' ? "border-iris" : "border-line")}><div className={cn("w-2 h-2 rounded-full", extractSource === 'both' ? "bg-iris" : "bg-transparent")}/></div></div>
                  <div>
                    <div className={cn("text-sm font-medium", extractSource === 'both' ? "text-iris" : "text-ink")}>所有可提炼数据</div>
                    <div className="text-xs text-ink-subtle mt-1">包含已审核数据和 AI 切分的初始对话块。速度较慢，提炼条目多。</div>
                  </div>
                </div>
              </div>
            </div>

            <div className="p-5 border-t border-panel-2 bg-panel-3 flex justify-end gap-3">
              <button 
                onClick={() => setShowExtractDialog(false)}
                className="px-4 py-2 text-ink-muted hover:text-ink transition-colors text-sm font-medium"
              >
                取消
              </button>
              <button 
                onClick={handleTriggerExtraction}
                className="px-5 py-2 bg-iris hover:bg-iris text-ink rounded-lg flex items-center gap-2 transition-colors text-sm font-medium shadow-md shadow-indigo-900/20"
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
        <div className="fixed inset-0 bg-scrim/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-panel rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden border border-line flex flex-col">
            <div className="p-5 border-b border-panel-2 flex justify-between items-center bg-panel-2">
              <h2 className="text-lg font-bold text-ink">
                编辑知识条目 #{editingArticle.id}
              </h2>
              <button 
                onClick={() => setShowEditDialog(false)}
                className="text-ink-muted hover:text-ink"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto flex-1 space-y-5">
              <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">场景描述 *</label>
                <textarea
                  value={editForm.scene}
                  onChange={e => setEditForm({...editForm, scene: e.target.value})}
                  className="w-full px-3 py-2 bg-canvas border border-line rounded-lg text-ink focus:ring-2 focus:ring-iris focus:border-transparent outline-none transition-all"
                  rows={2}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-ink-muted mb-2">分类 *</label>
                  <select
                    value={editForm.scene_category}
                    onChange={e => setEditForm({...editForm, scene_category: e.target.value})}
                    className="w-full px-3 py-2 bg-canvas border border-line rounded-lg text-ink outline-none"
                  >
                    {CATEGORIES.map((cat) => (
                      <option key={cat.id} value={cat.id}>{cat.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">客户原话 (可选)</label>
                <textarea
                  value={editForm.customer_says}
                  onChange={e => setEditForm({...editForm, customer_says: e.target.value})}
                  className="w-full px-3 py-2 bg-canvas border border-line rounded-lg text-warn focus:ring-2 focus:ring-warn/50 outline-none transition-all"
                  rows={2}
                  placeholder="客户典型的提问或异议..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">推荐回复话术 *</label>
                <textarea
                  value={editForm.recommended_response}
                  onChange={e => setEditForm({...editForm, recommended_response: e.target.value})}
                  className="w-full px-3 py-2 bg-canvas border border-line rounded-lg text-info focus:ring-2 focus:ring-iris/50 outline-none transition-all"
                  rows={4}
                />
              </div>

              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-sm font-medium text-ink-muted">提炼要点 (可选)</label>
                  <button onClick={addKeyPoint} className="text-xs text-iris hover:text-iris flex items-center gap-1">
                    <Plus className="w-3 h-3" /> 添加要点
                  </button>
                </div>
                
                {editForm.key_points.length === 0 ? (
                  <div className="text-sm text-ink-subtle italic p-3 bg-canvas rounded-lg border border-panel-2 text-center">
                    暂无要点
                  </div>
                ) : (
                  <div className="space-y-2">
                    {editForm.key_points.map((point, idx) => (
                      <div key={idx} className="flex gap-2">
                        <input
                          value={point}
                          onChange={e => updateKeyPoint(idx, e.target.value)}
                          className="flex-1 px-3 py-2 bg-canvas border border-line rounded-lg text-sm text-ink focus:border-iris outline-none"
                          placeholder="输入要点内容..."
                        />
                        <button 
                          onClick={() => removeKeyPoint(idx)}
                          className="p-2 text-ink-subtle hover:text-bad hover:bg-panel-2 rounded-lg"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="p-4 border-t border-panel-2 bg-panel flex justify-end gap-3">
              <button 
                onClick={() => setShowEditDialog(false)}
                className="px-4 py-2 bg-panel-2 text-ink rounded-lg hover:bg-line transition-colors text-sm"
              >
                取消
              </button>
              <button 
                onClick={handleSaveEdit}
                className="px-5 py-2 bg-iris hover:bg-flare text-ink rounded-lg flex items-center gap-2 transition-colors text-sm font-medium shadow-md shadow-glow"
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
