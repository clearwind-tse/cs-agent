import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { X, Loader2, RefreshCw, CheckCircle2, XCircle, Trash2, Inbox, Eye, EyeOff, ChevronLeft, ChevronRight, ShieldCheck, AlertTriangle, Tag, Filter, ClipboardCheck, Scale, Gauge } from 'lucide-react'
import { StatCard, ChartFrame, StatusDonut, CategoryBars } from './ui'
import { cn, formatDateTime } from '../utils'
import { useToast } from '../contexts/ToastContext'
import ConfirmDialog from './ConfirmDialog'
import QualityCheckView, { TabButton } from './QualityCheckView'
import QcCalibrationView from './QcCalibrationView'
import QcCalibrationItemDialog from './QcCalibrationItemDialog'
import { maskSessionId } from '../sessionDisplay'
import {
  getAdminStats,
  preprocessSessions,
  getStagingConversations,
  getStagingDetail,
  approveStaging,
  rejectStaging,
  batchActionStaging,
  cleanOldData,
  getCurrentQcConfig,
  listCalibrationGroups,
  type StagingConversation,
  type StagingQc,
  type CalibrationGroup,
  type AdminStats
} from '../api'

interface AdminViewProps {
  onClose: () => void
}

type AdminTab = 'cleaning' | 'qc' | 'calibration'

const qcScoreColor = (s: number | null | undefined) =>
  s == null ? 'text-ink-muted' : s >= 80 ? 'text-ok' : s >= 60 ? 'text-warn' : 'text-bad'

/* 分类 chip 统一走低饱和语义色：避免 9 个高饱和色块把审核区压得过于吵闹 */
const CATEGORY_OPTIONS = [
  { id: 'savings_explain', name: '省钱讲解', color: 'bg-ok/10 text-ok border-ok/25' },
  { id: 'rebate_query', name: '返利查询', color: 'bg-iris/10 text-info border-iris/25' },
  { id: 'coupon_issue', name: '优惠券问题', color: 'bg-warn/10 text-warn border-warn/25' },
  { id: 'order_problem', name: '订单问题', color: 'bg-iris/10 text-info border-iris/25' },
  { id: 'complaint', name: '投诉处理', color: 'bg-flare/10 text-bad border-flare/25' },
  { id: 'merchant', name: '到店霸王餐', color: 'bg-ok/10 text-ok border-ok/25' },
  { id: 'brand_promo', name: '品牌活动', color: 'bg-warn/10 text-warn border-warn/25' },
  { id: 'points_box', name: '积分盲盒', color: 'bg-flare/10 text-bad border-flare/25' },
  { id: 'onboarding', name: '新人引导', color: 'bg-iris/10 text-info border-iris/25' },
]

export default function AdminView({ onClose }: AdminViewProps) {
  const { showSuccess, showError } = useToast()
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [conversations, setConversations] = useState<StagingConversation[]>([])
  const [loading, setLoading] = useState(false)
  const [preprocessing, setPreprocessing] = useState(false)
  const [selectedStatus, setSelectedStatus] = useState<'pending' | 'approved' | 'rejected' | 'all'>('all')  // 默认显示全部
  const [selectedConversations, setSelectedConversations] = useState<Set<number>>(new Set())
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)  // 分页总数
  const [totalItems, setTotalItems] = useState(0)  // 总条目数
  const [selectedDetail, setSelectedDetail] = useState<number | null>(null)
  const [showOriginal, setShowOriginal] = useState(false)
  const [error, setError] = useState<string | null>(null)
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

  const [processAllProgress, setProcessAllProgress] = useState<{ current: number; total: number } | null>(null)

  // 质检配置：用于把维度 key 映射为中文名、并取及格线（清洗界面展示会话质检结果用）
  const [qcDimNames, setQcDimNames] = useState<Record<string, string>>({})
  const [qcThreshold, setQcThreshold] = useState<number>(60)
  useEffect(() => {
    getCurrentQcConfig()
      .then((res) => {
        const cfg = (res?.current?.config || res?.default || {}) as any
        const names: Record<string, string> = {}
        for (const d of (cfg.dimensions || [])) names[d.key] = d.name
        setQcDimNames(names)
        setQcThreshold(Number(cfg.pass_threshold) || 60)
      })
      .catch(() => { /* 质检配置拉取失败时回退为按 key 展示 */ })
  }, [])

  // 顶层页签：会话清洗与审核 / 质检评分 / 校准对比（三者同源，合并为数据质检中心）
  const [tab, setTab] = useState<AdminTab>('cleaning')
  // 「标记为标注数据」弹窗：记录被标记的会话 + 可选的校准分组
  const [markTarget, setMarkTarget] = useState<StagingConversation | null>(null)
  const [calGroups, setCalGroups] = useState<CalibrationGroup[]>([])
  useEffect(() => {
    if (!markTarget) return
    listCalibrationGroups().then((res) => setCalGroups(res.items)).catch(() => setCalGroups([]))
  }, [markTarget])

  const loadStats = useCallback(async () => {
    setError(null)
    try {
      const data = await getAdminStats()
      if (!data.sessions) {
        data.sessions = { total: 0, processed: 0, unprocessed: 0 }
      }
      setStats(data)
    } catch (error: any) {
      console.error('Failed to load admin stats:', error)
      const errorMsg = error.response?.data?.detail || error.message || '加载统计信息失败，请检查后端服务'
      setError(errorMsg)
      setStats({
        raw_chats: { total: 0, pending: 0, approved: 0, rejected: 0 },
        sessions: { total: 0, processed: 0, unprocessed: 0 },
        staging_conversations: { total: 0, pending: 0, approved: 0, rejected: 0 }
      })
    }
  }, [])

  const loadConversations = useCallback(async (page: number = 1) => {
    setLoading(true)
    try {
      const pageSize = 20
      const data = await getStagingConversations({
        status: selectedStatus,  // 直接传递状态值，包括 'all'
        page: page,
        page_size: pageSize,
      })
      setConversations(data.items)
      setCurrentPage(page)
      setTotalItems(data.total)
      setTotalPages(Math.ceil(data.total / pageSize))
    } catch (error) {
      console.error('Failed to load conversations:', error)
    } finally {
      setLoading(false)
    }
  }, [selectedStatus])  // 只依赖 selectedStatus

  useEffect(() => {
    loadStats()
    loadConversations(1)  // 总是从第1页开始
  }, [loadStats, selectedStatus])  // 移除 loadConversations 依赖，避免循环

  const handleCleanOldData = async () => {
    if (!confirm('将清理所有2025年10月以前和群聊的暂存区数据。是否继续？')) {
      return
    }

    setPreprocessing(true)
    try {
      const result = await cleanOldData()
      showSuccess(result.message)
      await loadStats()
      await loadConversations(1)
    } catch (error: any) {
      console.error('Failed to clean old data:', error)
      showError('清理失败：' + (error.response?.data?.detail || error.message))
    } finally {
      setPreprocessing(false)
    }
  }

  const handlePreprocess = async () => {
    setPreprocessing(true)
    setError(null)

    try {
      const result = await preprocessSessions({
        window_seconds: 300,
        limit: 50
      })

      await loadStats()

      if (result.processed === 0) {
        showSuccess('所有会话均已处理完毕，无新数据可处理。', 5000)
      } else {
        const message = `处理了 ${result.processed} 个会话，创建了 ${result.total_created} 个对话块`
        if (result.has_more) {
          showSuccess(`${message}。还有 ${result.total - result.processed} 个会话待处理。`, 5000)
        } else {
          showSuccess(`${message}。所有会话已处理完成！`, 5000)
        }
      }

      setSelectedStatus('pending')
      await loadConversations(1)
    } catch (error: any) {
      console.error('Failed to preprocess:', error)
      const errorMsg = error.response?.data?.detail || error.message || '预处理失败'
      setError(errorMsg)
      showError('预处理失败：' + errorMsg)
    } finally {
      setPreprocessing(false)
    }
  }

  const handleProcessAll = async () => {
    setPreprocessing(true)
    setError(null)
    const initialTotal = stats?.sessions.unprocessed || 0
    setProcessAllProgress({ current: 0, total: initialTotal })

    try {
      let totalProcessed = 0
      let totalCreated = 0
      let hasMore = true

      while (hasMore) {
        const result = await preprocessSessions({
          window_seconds: 300,
          limit: 50,
        })

        totalProcessed += result.processed
        totalCreated += result.total_created
        hasMore = result.has_more && result.processed > 0

        setProcessAllProgress({
          current: totalProcessed,
          total: initialTotal
        })
      }

      await loadStats()
      showSuccess(`全部处理完成！共处理 ${totalProcessed} 个会话，创建 ${totalCreated} 个对话块`, 5000)
      setSelectedStatus('pending')
      await loadConversations(1)
    } catch (error: any) {
      console.error('Failed to process all:', error)
      const errorMsg = error.response?.data?.detail || error.message || '处理失败'
      setError(errorMsg)
      showError('处理失败：' + errorMsg)
      await loadStats()
    } finally {
      setPreprocessing(false)
      setProcessAllProgress(null)
    }
  }

  const handleApprove = async (id: number, category?: string) => {
    try {
      await approveStaging(id, category)
      await loadStats()
      await loadConversations(1)
      showSuccess('审核通过')
    } catch (error) {
      console.error('Failed to approve:', error)
      showError('审核失败')
    }
  }

  const handleReject = async (id: number) => {
    try {
      await rejectStaging(id)
      await loadStats()
      await loadConversations(1)
      showSuccess('已拒绝')
    } catch (error) {
      console.error('Failed to reject:', error)
      showError('拒绝失败')
    }
  }

  const handleBatchAction = async (action: 'approve' | 'reject' | 'delete', category?: string) => {
    if (selectedConversations.size === 0) return
    setLoading(true)
    try {
      await batchActionStaging({
        staging_ids: Array.from(selectedConversations),
        action,
        category,
      })
      setSelectedConversations(new Set())
      await loadStats()
      await loadConversations(1)
      showSuccess('批量操作成功')
    } catch (error) {
      console.error('Failed to perform batch action:', error)
      showError('批量操作失败')
    } finally {
      setLoading(false)
    }
  }

  const handleToggleSelect = (id: number) => {
    setSelectedConversations(prev => {
      const newSet = new Set(prev)
      if (newSet.has(id)) {
        newSet.delete(id)
      } else {
        newSet.add(id)
      }
      return newSet
    })
  }

  const handleViewDetail = async (id: number) => {
    if (selectedDetail === id) {
      setSelectedDetail(null)
      return
    }
    setSelectedDetail(id)
  }

  return (
    <div className="flex-1 flex flex-col animate-fade-in h-full min-h-0">
      {/* Header */}
      <header className="h-16 px-6 flex items-center justify-between border-b border-line bg-panel/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-iris to-flare flex items-center justify-center">
            <Gauge size={20} className="text-ink" />
          </div>
          <div>
            <h2 className="font-medium text-ink">数据质检中心</h2>
            <p className="text-xs text-ink-subtle">会话清洗 · 质检评分 · 校准对比</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-line text-ink-muted hover:text-ink transition-colors"
        >
          <X size={18} />
        </button>
      </header>

      {/* 顶层页签：清洗与质检同源合并，校准独立一页 */}
      <div className="px-6 pt-3 flex gap-1 border-b border-line flex-shrink-0 overflow-x-auto">
        <TabButton active={tab === 'cleaning'} onClick={() => setTab('cleaning')} icon={Filter} label="会话清洗与审核" />
        <TabButton active={tab === 'qc'} onClick={() => setTab('qc')} icon={ClipboardCheck} label="质检评分" />
        <TabButton active={tab === 'calibration'} onClick={() => setTab('calibration')} icon={Scale} label="校准对比" />
      </div>

      {tab === 'qc' ? (
        <QualityCheckView embedded />
      ) : tab === 'calibration' ? (
        <QcCalibrationView />
      ) : (
      /* Main Content：会话清洗与审核 */
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col">
        <div className="max-w-7xl mx-auto w-full p-6">
          {/* Stats and Preprocess */}
          <div className="chart-panel p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold text-ink">数据概览</h3>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleCleanOldData}
                  disabled={preprocessing}
                  className="px-4 py-2 bg-bad hover:bg-bad text-ink rounded-lg text-sm font-medium transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                  title="清理2025年10月以前和群聊的旧数据"
                >
                  {preprocessing ? (
                    <Loader2 size={16} className="animate-spin mr-2" />
                  ) : (
                    <Trash2 size={16} className="mr-2" />
                  )}
                  清理旧数据
                </button>
                <button
                  onClick={handlePreprocess}
                  disabled={preprocessing}
                  className="px-4 py-2 bg-line-strong hover:bg-ink-subtle text-ink rounded-lg text-sm font-medium transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {preprocessing && !processAllProgress ? (
                    <Loader2 size={16} className="animate-spin mr-2" />
                  ) : (
                    <RefreshCw size={16} className="mr-2" />
                  )}
                  处理下一批
                </button>
                <button
                  onClick={handleProcessAll}
                  disabled={preprocessing}
                  className="px-5 py-2 bg-iris hover:bg-flare text-ink rounded-lg text-base font-medium transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {processAllProgress ? (
                    <Loader2 size={18} className="animate-spin mr-2" />
                  ) : (
                    <RefreshCw size={18} className="mr-2" />
                  )}
                  一键处理全部
                </button>
              </div>
            </div>

            {/* 处理进度条 */}
            {processAllProgress && (
              <div className="mb-4">
                <div className="flex items-center justify-between text-sm text-ink-muted mb-1">
                  <span>正在处理全部会话...</span>
                  <span>{processAllProgress.current} / {processAllProgress.total} 个会话</span>
                </div>
                <div className="w-full bg-line rounded-full h-2.5">
                  <div
                    className="bg-iris h-2.5 rounded-full transition-all duration-300"
                    style={{ width: `${processAllProgress.total > 0 ? (processAllProgress.current / processAllProgress.total) * 100 : 0}%` }}
                  />
                </div>
              </div>
            )}

            {error ? (
              <div className="bg-bad/30 border border-bad text-bad p-4 rounded-lg">
                <p className="text-sm font-medium mb-1">加载失败</p>
                <p className="text-xs">{error}</p>
                <button
                  onClick={loadStats}
                  className="mt-2 px-3 py-1 bg-bad hover:bg-bad text-ink rounded text-sm"
                >
                  重试
                </button>
              </div>
            ) : stats ? (
              <>
                {/* 会话处理进度（主要指标） */}
                <div className="mb-4">
                  <div className="flex items-center justify-between text-sm text-ink-muted mb-2">
                    <span>会话处理进度</span>
                    <span>{stats.sessions.processed} / {stats.sessions.total} 个会话已处理</span>
                  </div>
                  <div className="w-full bg-line rounded-full h-3">
                    <div
                      className="bg-gradient-to-r from-iris to-mint h-3 rounded-full transition-all duration-500"
                      style={{ width: `${stats.sessions.total > 0 ? (stats.sessions.processed / stats.sessions.total) * 100 : 0}%` }}
                    />
                  </div>
                  {stats.sessions.unprocessed > 0 && (
                    <p className="text-xs text-warn mt-1">
                      还有 {stats.sessions.unprocessed} 个会话未处理，点击"一键处理全部"自动完成
                    </p>
                  )}
                </div>

                <motion.div
                  initial="hidden"
                  animate="show"
                  transition={{ staggerChildren: 0.05 }}
                  className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5"
                >
                  <StatCard
                    label="总会话"
                    value={stats.sessions.total}
                    hint={`原始消息 ${stats.raw_chats.total.toLocaleString()} 条`}
                    icon={<Gauge size={17} />}
                    tone="iris"
                  />
                  <StatCard
                    label="未处理会话"
                    value={stats.sessions.unprocessed}
                    hint="等待分块处理"
                    icon={<AlertTriangle size={17} />}
                    tone="flare"
                  />
                  <StatCard
                    label="暂存区对话"
                    value={stats.staging_conversations.total}
                    hint={`待审核 ${stats.staging_conversations.pending}`}
                    icon={<Inbox size={17} />}
                    tone="iris"
                  />
                  <StatCard
                    label="已通过"
                    value={stats.staging_conversations.approved}
                    hint="审核通过"
                    icon={<CheckCircle2 size={17} />}
                    tone="mint"
                  />
                  <StatCard
                    label="已拒绝"
                    value={stats.staging_conversations.rejected}
                    hint="审核拒绝"
                    icon={<XCircle size={17} />}
                    tone="flare"
                  />
                </motion.div>

                {/* 数据分布：全部来自当前 /api/admin/stats 快照，不编造时间序列 */}
                <div className="mt-5 grid gap-4 lg:grid-cols-2">
                  <ChartFrame title="暂存区审核分布" subtitle="当前快照 · 单位：条">
                    <StatusDonut
                      data={[
                        { name: '待审核', value: stats.staging_conversations.pending },
                        { name: '已通过', value: stats.staging_conversations.approved },
                        { name: '已拒绝', value: stats.staging_conversations.rejected },
                      ]}
                      centerLabel="暂存对话"
                    />
                  </ChartFrame>
                  <ChartFrame title="原始消息状态构成" subtitle="当前快照 · 单位：条">
                    <CategoryBars
                      data={[
                        { name: '待处理', value: stats.raw_chats.pending },
                        { name: '已通过', value: stats.raw_chats.approved },
                        { name: '已拒绝', value: stats.raw_chats.rejected },
                      ]}
                      unit=" 条"
                    />
                  </ChartFrame>
                </div>
              </>
            ) : (
              <p className="text-ink-subtle">加载统计中...</p>
            )}
          </div>

          {/* Filters and Batch Actions */}
          <div className="chart-panel p-4 mb-6 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-ink-muted text-sm">状态:</label>
              <select
                value={selectedStatus}
                onChange={(e) => setSelectedStatus(e.target.value as any)}
                className="bg-line border border-line-strong text-ink text-sm rounded-lg focus:ring-iris focus:border-iris p-2"
              >
                <option value="pending">待审核</option>
                <option value="approved">已通过</option>
                <option value="rejected">已拒绝</option>
                <option value="all">全部</option>
              </select>
            </div>

            {selectedConversations.size > 0 && (
              <div className="flex items-center gap-2 ml-auto">
                <span className="text-ink-muted text-sm">{selectedConversations.size} 项已选择:</span>
                <button
                  onClick={() => handleBatchAction('approve')}
                  className="px-3 py-1.5 bg-ok hover:bg-ok text-ink rounded-lg text-sm flex items-center gap-1"
                >
                  <CheckCircle2 size={16} /> 批量通过
                </button>
                <button
                  onClick={() => handleBatchAction('reject')}
                  className="px-3 py-1.5 bg-bad hover:bg-bad text-ink rounded-lg text-sm flex items-center gap-1"
                >
                  <XCircle size={16} /> 批量拒绝
                </button>
                <button
                  onClick={() => handleBatchAction('delete')}
                  className="px-3 py-1.5 bg-bad hover:bg-bad text-ink rounded-lg text-sm flex items-center gap-1"
                >
                  <Trash2 size={16} /> 批量删除
                </button>
              </div>
            )}
          </div>

          {/* Conversations List */}
          {conversations.length === 0 && !loading ? (
            <div className="p-8 text-center text-ink-subtle">
              <Inbox size={32} className="mx-auto mb-2 opacity-50" />
              <p className="text-sm">暂无暂存区对话。请先点击 "处理下一批会话"。</p>
            </div>
          ) : (
            <div className="space-y-4">
              {conversations.map((conv) => (
                <StagingItem
                  key={conv.id}
                  conversation={conv}
                  isSelected={selectedConversations.has(conv.id)}
                  isExpanded={selectedDetail === conv.id}
                  showOriginal={showOriginal}
                  qcDimNames={qcDimNames}
                  qcThreshold={qcThreshold}
                  onMarkCalibration={() => setMarkTarget(conv)}
                  onToggleSelect={() => handleToggleSelect(conv.id)}
                  onViewDetail={() => handleViewDetail(conv.id)}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  onToggleOriginal={() => setShowOriginal(!showOriginal)}
                />
              ))}

              {/* 分页控件 */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 py-4 border-t border-line">
                  <button
                    onClick={() => loadConversations(currentPage - 1)}
                    disabled={currentPage <= 1 || loading}
                    className="px-4 py-2 bg-line hover:bg-line-strong text-ink rounded-lg text-sm flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft size={16} /> 上一页
                  </button>
                  <span className="text-ink-muted text-sm">
                    第 {currentPage} / {totalPages} 页 (共 {totalItems} 条)
                  </span>
                  <button
                    onClick={() => loadConversations(currentPage + 1)}
                    disabled={currentPage >= totalPages || loading}
                    className="px-4 py-2 bg-line hover:bg-line-strong text-ink rounded-lg text-sm flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    下一页 <ChevronRight size={16} />
                  </button>
                </div>
              )}

              {loading && (
                <div className="p-4 text-center">
                  <Loader2 size={24} className="animate-spin text-iris mx-auto" />
                  <p className="text-ink-subtle text-sm mt-2">加载中...</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      )}

      {/* 标记为标注数据（供质检校准） */}
      {markTarget && (
        <QcCalibrationItemDialog
          groups={calGroups}
          defaultSessionId={markTarget.session_id}
          defaultStartTime={markTarget.start_time}
          defaultEndTime={markTarget.end_time}
          onClose={() => setMarkTarget(null)}
          onCreated={() => setMarkTarget(null)}
        />
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

interface StagingItemProps {
  conversation: StagingConversation
  isSelected: boolean
  isExpanded: boolean
  showOriginal: boolean
  qcDimNames: Record<string, string>
  qcThreshold: number
  onMarkCalibration: () => void
  onToggleSelect: () => void
  onViewDetail: () => void
  onApprove: (id: number, category?: string) => void
  onReject: (id: number) => void
  onToggleOriginal: () => void
}

function StagingItem({
  conversation,
  isSelected,
  isExpanded,
  showOriginal,
  qcDimNames,
  qcThreshold,
  onMarkCalibration,
  onToggleSelect,
  onViewDetail,
  onApprove,
  onReject,
  onToggleOriginal,
}: StagingItemProps) {
  const getCategoryColor = (category?: string) => {
    const option = CATEGORY_OPTIONS.find(opt => opt.id === category)
    return option ? option.color : 'bg-panel-2'
  }

  return (
    <div className={cn(
      "bg-panel-2 p-5 rounded-lg shadow-md border",
      isSelected ? "border-iris" : "border-line",
      conversation.status === 'approved' && 'border-ok/50',
      conversation.status === 'rejected' && 'border-bad/50',
    )}>
      <div className="flex items-start mb-4">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggleSelect}
          className="h-5 w-5 text-iris rounded border-line focus:ring-iris bg-line-strong mr-3 mt-1"
        />
        <div className="flex-1">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-ink-muted">会话: {maskSessionId(conversation.session_id)}</span>
              {conversation.auto_quality_score !== null && (
                <span className="px-2 py-0.5 text-xs rounded-full bg-iris/30 text-info">
                  AI 评分: {conversation.auto_quality_score?.toFixed(1)}
                </span>
              )}
              {conversation.auto_category && (
                <span className={cn("px-2 py-0.5 text-xs rounded-full", getCategoryColor(conversation.auto_category))}>
                  {CATEGORY_OPTIONS.find(c => c.id === conversation.auto_category)?.name || conversation.auto_category}
                </span>
              )}
              {conversation.status === 'pending' && <span className="px-2 py-0.5 text-xs rounded-full bg-warn/30 text-warn">待审核</span>}
              {conversation.status === 'approved' && <span className="px-2 py-0.5 text-xs rounded-full bg-ok/30 text-ok">已通过</span>}
              {conversation.status === 'rejected' && <span className="px-2 py-0.5 text-xs rounded-full bg-bad/30 text-bad">已拒绝</span>}
            </div>
            <span className="text-xs text-ink-subtle">
              {conversation.start_time
                ? formatDateTime(conversation.start_time)  // 时间戳是秒级
                : conversation.created_at
                  ? formatDateTime(conversation.created_at)
                  : ''}
            </span>
          </div>

          {/* AI 质检简报（若该会话已质检） */}
          {conversation.qc && (
            <QcBrief qc={conversation.qc} dimNames={qcDimNames} threshold={qcThreshold} />
          )}

          {/* 对话内容 */}
          <div className="mb-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <button
                  onClick={onToggleOriginal}
                  className="text-xs text-ink-muted hover:text-ink flex items-center gap-1"
                >
                  {showOriginal ? <EyeOff size={14} /> : <Eye size={14} />}
                  {showOriginal ? '显示清洗后' : '显示原始'}
                </button>
                {conversation.start_time && conversation.end_time && (
                  <span className="text-xs text-ink-subtle">
                    时间: {formatDateTime(conversation.start_time)} - {formatDateTime(conversation.end_time)}
                  </span>
                )}
              </div>
            </div>
            <p className="text-ink whitespace-pre-wrap text-sm bg-line p-3 rounded">
              {showOriginal ? conversation.original_text : (conversation.cleaned_text || conversation.original_text)}
            </p>
          </div>

          {/* Q&A 预览 */}
          {(conversation.auto_question || conversation.human_question) && (
            <div className="mb-3 bg-line p-3 rounded text-sm">
              <p className="text-ink-muted mb-1">Q: {conversation.human_question || conversation.auto_question}</p>
              {(conversation.auto_answer || conversation.human_answer) && (
                <p className="text-ink">A: {conversation.human_answer || conversation.auto_answer}</p>
              )}
            </div>
          )}

          {/* 展开详情 */}
          {isExpanded && (
            <StagingDetail stagingId={conversation.id} />
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2 mt-4 justify-end">
        <button
          onClick={onViewDetail}
          className="px-4 py-2 bg-line hover:bg-line-strong text-ink rounded-lg text-sm flex items-center gap-1"
        >
          <Eye size={16} /> {isExpanded ? '收起' : '查看详情'}
        </button>
        {CATEGORY_OPTIONS.map(cat => (
          <button
            key={cat.id}
            onClick={() => onApprove(conversation.id, cat.id)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs transition-all hover:brightness-125",
              cat.color,
              conversation.human_category === cat.id && conversation.status === 'approved' ? 'ring-2 ring-offset-2 ring-offset-panel-2 ring-ink' : ''
            )}
          >
            {cat.name}
          </button>
        ))}
        <button
          onClick={onMarkCalibration}
          className="px-4 py-2 bg-line hover:bg-line-strong text-ink rounded-lg text-sm flex items-center gap-1"
          title="把该会话标为质检校准的标注数据"
        >
          <Tag size={16} /> 标记为标注数据
        </button>
        <button
          onClick={() => onReject(conversation.id)}
          className="px-4 py-2 bg-bad hover:bg-bad text-ink rounded-lg text-sm flex items-center gap-1"
        >
          <XCircle size={16} /> 拒绝
        </button>
      </div>
    </div>
  )
}

/** 会话列表内的 AI 质检简报：总分徽标（对照阈值）+ 维度速览 + 违规 chips */
function QcBrief({ qc, dimNames, threshold }: {
  qc: StagingQc
  dimNames: Record<string, string>
  threshold: number
}) {
  const scores = qc.scores || {}
  return (
    <div className="mb-3 rounded-lg border border-line bg-canvas/50 p-3">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <ShieldCheck size={14} className="text-iris" />
        <span className="text-xs text-ink-muted">AI 质检</span>
        <span className={cn('text-sm font-bold', qcScoreColor(qc.overall_score))}>
          {qc.scored ? (qc.overall_score ?? '-') : '未评分'}
        </span>
        {qc.scored && qc.overall_score != null && (
          qc.overall_score >= threshold
            ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-ok/10 text-ok">及格</span>
            : <span className="text-[10px] px-1.5 py-0.5 rounded bg-bad/10 text-bad">不及格</span>
        )}
        {qc.agent_name && <span className="text-xs text-ink-subtle">客服：{qc.agent_name}</span>}
        {qc.config_name && <span className="text-xs text-ink-subtle">{qc.config_name}</span>}
      </div>

      {Object.keys(scores).length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-1">
          {Object.entries(scores).map(([k, v]) => (
            <span key={k} className="text-[10px] text-ink-muted bg-panel-2 rounded px-1.5 py-0.5">
              {dimNames[k] || k}: <span className={qcScoreColor(v)}>{v}</span>
            </span>
          ))}
        </div>
      )}

      {qc.violations && qc.violations.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {qc.violations.map((v, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-bad/10 text-bad border border-bad/20 flex items-center gap-1">
              <AlertTriangle size={10} /> {v.type}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function StagingDetail({ stagingId }: { stagingId: number }) {
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getStagingDetail(stagingId).then(data => {
      setDetail(data)
      setLoading(false)
    }).catch(err => {
      console.error('Failed to load detail:', err)
      setLoading(false)
    })
  }, [stagingId])

  if (loading) {
    return <div className="p-4 text-center"><Loader2 size={20} className="animate-spin mx-auto" /></div>
  }

  if (!detail) {
    return <div className="p-4 text-ink-subtle text-sm">加载失败</div>
  }

  return (
    <div className="mt-4 p-4 bg-line rounded-lg">
      <h4 className="text-sm font-medium text-ink mb-3">原始消息对照</h4>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {detail.original_messages?.map((msg: any, idx: number) => (
          <div key={idx} className="text-xs bg-panel-2 p-2 rounded">
            <div className="flex items-center justify-between mb-1">
              <span className="text-ink-muted">{msg.sender_name || (msg.is_sender ? '我' : '对方')}:</span>
              {msg.timestamp && (
                <span className="text-ink-subtle">
                  {formatDateTime(msg.timestamp)}
                </span>
              )}
            </div>
            <span className="text-ink">{msg.content}</span>
            {msg.clean_content && msg.clean_content !== msg.content && (
              <div className="text-ink-subtle mt-1">清洗后: {msg.clean_content}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
