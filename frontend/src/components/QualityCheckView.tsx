import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  ShieldCheck, BarChart3, AlertTriangle, Search, RefreshCw, Loader2, ChevronLeft,
  CheckCircle2, ClipboardList, Plus, Trash2, AlertCircle, ListChecks, RotateCcw, Lightbulb,
  ClipboardCheck,
} from 'lucide-react'
import {
  getQcStats, listInspections, getInspection, inspectSession, batchInspect,
  reviewInspection, seedDefaultQcConfig, getCurrentQcConfig, saveQcConfig, getSessions,
  getQcFeedback, QcStats, QcInspection, QcInspectionDetail, QcConfigSchema, QcFeedback,
} from '../api'
import { cn } from '../utils'
import { maskSessionId } from '../sessionDisplay'
import {
  StatCard as AuroraStatCard,
  ChartFrame,
  ScoreHistogram,
  CategoryBars,
} from './ui'

interface QualityCheckViewProps {
  onClose?: () => void
  /** 嵌入「数据质检中心」页签时：隐藏自身头部，交由外层容器提供标题与页签 */
  embedded?: boolean
}

type Tab = 'results' | 'config' | 'insights'

const FALLBACK_DIM_NAMES: Record<string, string> = {
  attitude: '服务态度', responsiveness: '响应时效', resolution: '问题解决',
  compliance: '合规规范', accuracy: '专业准确',
}

const SEVERITY_COLORS: Record<string, string> = {
  high: 'text-bad bg-bad/10 border-bad/20',
  medium: 'text-warn bg-warn/10 border-warn/20',
  low: 'text-info bg-iris/10 border-iris/20',
}

const SEVERITY_OPTIONS = [
  { value: 'high', label: '高（严重）' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]

const scoreColor = (s: number | null | undefined) => {
  if (s == null) return 'text-ink-muted'
  if (s >= 80) return 'text-ok'
  if (s >= 60) return 'text-warn'
  return 'text-bad'
}

const slugify = (s: string): string => {
  const t = s.trim().toLowerCase()
    .replace(/[^a-z0-9一-龥]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return t || ''
}

export default function QualityCheckView({ embedded = false }: QualityCheckViewProps) {
  const [tab, setTab] = useState<Tab>('results')
  const [stats, setStats] = useState<QcStats | null>(null)
  const [items, setItems] = useState<QcInspection[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<{ status?: string; min_score?: number; violation_type?: string }>({})
  const [sessionInput, setSessionInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<QcInspectionDetail | null>(null)
  const [dimNameMap, setDimNameMap] = useState<Record<string, string>>(FALLBACK_DIM_NAMES)
  const [feedback, setFeedback] = useState<QcFeedback | null>(null)

  const loadStats = useCallback(async () => {
    try { setStats(await getQcStats()) } catch { /* ignore */ }
  }, [])

  const loadFeedback = useCallback(async () => {
    try { setFeedback(await getQcFeedback()) } catch { /* ignore */ }
  }, [])

  // 用「当前质检配置」的维度名称补全分数展示（维度 key -> 中文名）
  const loadDimNames = useCallback(async () => {
    try {
      const res = await getCurrentQcConfig()
      const cfg = res.current?.config || res.default
      const map: Record<string, string> = { ...FALLBACK_DIM_NAMES }
      for (const d of (cfg.dimensions || [])) map[d.key] = d.name
      setDimNameMap(map)
    } catch { /* ignore */ }
  }, [])

  const loadInspections = useCallback(async (p = 1) => {
    setLoading(true)
    setError('')
    try {
      const res = await listInspections({
        page: p, page_size: 20,
        status: filters.status,
        min_score: filters.min_score,
        violation_type: filters.violation_type,
      })
      setItems(res.items)
      setTotal(res.total)
      setPage(p)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    loadStats()
    loadDimNames()
    loadInspections(1)
    loadFeedback()
  }, [loadStats, loadDimNames, loadInspections, loadFeedback])

  const handleInspect = async (sessionId: string) => {
    if (!sessionId.trim()) { setError('请输入会话 ID'); return }
    setLoading(true); setError('')
    try {
      const res = await inspectSession(sessionId.trim())
      setDetail(res)
      await loadStats()
      await loadInspections(1)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '质检失败（可能是 LLM 未配置或超时）')
    } finally { setLoading(false) }
  }

  const handleBatch = async () => {
    setLoading(true); setError('')
    try {
      const sessions = await getSessions({ page: 1, page_size: 30 })
      const ids = (sessions.items || []).map((s: any) => s.session_id).filter(Boolean)
      if (ids.length === 0) { setError('没有可用的会话'); return }
      const res = await batchInspect(ids)
      setError('')
      alert(`已提交批量质检 ${res.accepted} 个会话，请稍后刷新查看结果。`)
      await loadInspections(1)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '批量质检提交失败')
    } finally { setLoading(false) }
  }

  const handleOpenDetail = async (id: number) => {
    setLoading(true)
    try {
      const insp = await getInspection(id)
      setDetail(insp)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载详情失败')
    } finally { setLoading(false) }
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
      {/* Header（嵌入模式下隐藏，由外层页签提供） */}
      {!embedded && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-line">
          <h1 className="text-xl font-bold text-ink flex items-center gap-2">
            <ClipboardCheck size={24} className="text-iris" />
            质检评分
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { loadStats(); loadInspections(1) }}
              className="p-2 rounded-lg hover:bg-panel-2 text-ink-muted"
              title="刷新"
            >
              <RefreshCw size={18} />
            </button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="px-6 pt-4 flex gap-1">
        <TabButton active={tab === 'results'} onClick={() => setTab('results')} icon={BarChart3} label="质检结果" />
        <TabButton active={tab === 'config'} onClick={() => setTab('config')} icon={ListChecks} label="质检规则配置" />
        <TabButton active={tab === 'insights'} onClick={() => setTab('insights')} icon={Lightbulb} label="优化洞察" />
      </div>

      {error && (
        <div className="mx-6 mt-4 px-4 py-2 bg-bad/10 border border-bad/30 rounded-lg text-bad text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {tab === 'results' ? (
        <ResultsTab
          stats={stats}
          items={items}
          total={total}
          page={page}
          loading={loading}
          filters={filters}
          setFilters={setFilters}
          sessionInput={sessionInput}
          setSessionInput={setSessionInput}
          onInspect={handleInspect}
          onBatch={handleBatch}
          onOpenDetail={handleOpenDetail}
          onPage={(p: number) => loadInspections(p)}
          onRefresh={() => loadInspections(page)}
        />
      ) : tab === 'insights' ? (
        <InsightsTab feedback={feedback} onOpenDetail={handleOpenDetail} onRefresh={loadFeedback} />
      ) : (
        <ConfigFormTab onChanged={async () => { await loadDimNames(); await loadStats() }} />
      )}

      {/* Detail Drawer */}
      {detail && (
        <DetailDrawer
          inspection={detail}
          dimNameMap={dimNameMap}
          onClose={() => setDetail(null)}
          onReviewed={async (updated: QcInspectionDetail) => {
            setDetail(updated)
            await loadInspections(page)
            await loadStats()
          }}
        />
      )}
    </div>
  )
}

// ============ Tabs ============
export function TabButton({ active, onClick, icon: Icon, label }: any) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-4 py-2 rounded-t-lg text-sm font-medium transition-colors flex items-center gap-1.5',
        active ? 'bg-panel text-ink border-b-2 border-iris' : 'text-ink-subtle hover:text-ink'
      )}
    >
      <Icon size={16} /> {label}
    </button>
  )
}

// ============ Results Tab ============
function ResultsTab(props: any) {
  const {
    stats, items, total, page, loading, filters, setFilters,
    sessionInput, setSessionInput,
    onInspect, onBatch, onOpenDetail, onPage, onRefresh,
  } = props

  return (
    <div className="flex-1 overflow-y-auto p-6 pt-4 space-y-5">
      {/* Stats */}
      {stats && (
        <motion.div
          initial="hidden"
          animate="show"
          transition={{ staggerChildren: 0.05 }}
          className="grid grid-cols-2 md:grid-cols-4 gap-3"
        >
          <AuroraStatCard label="质检总数" value={stats.total} hint="当前快照" icon={<ShieldCheck size={17} />} />
          <AuroraStatCard
            label="平均得分"
            value={<span className={scoreColor(stats.avg_score)}>{stats.avg_score != null ? stats.avg_score : '-'}</span>}
            hint={`及格线 ${stats.threshold}`}
            icon={<BarChart3 size={17} />}
          />
          <AuroraStatCard
            label="及格率"
            value={stats.pass_rate != null ? `${(stats.pass_rate * 100).toFixed(0)}%` : '-'}
            hint="达到及格线的占比"
            icon={<CheckCircle2 size={17} />}
            tone="mint"
          />
          <AuroraStatCard label="及格线" value={stats.threshold} hint="当前配置阈值" icon={<ClipboardCheck size={17} />} />
        </motion.div>
      )}

      {/* 分布图：来自 /api/qc/stats 当前快照 */}
      {stats && (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartFrame title="质检分数分布" subtitle="按分数段 · 当前快照">
            <ScoreHistogram
              data={Object.entries(stats.score_distribution ?? {}).map(([name, value]) => ({ name, value: Number(value) || 0 }))}
              unit=" 次"
            />
          </ChartFrame>
          <ChartFrame
            title="高频违规项 TOP"
            subtitle="按出现次数 · 当前快照"
            aside={<AlertTriangle size={16} className="text-warn" />}
          >
            <CategoryBars
              data={stats.top_violations.map((v: { type: string; count: number }) => ({ name: v.type, value: v.count }))}
              unit=" 次"
              emptyHint="暂无违规记录"
            />
          </ChartFrame>
        </div>
      )}

      {/* Trigger */}
      <div className="bg-panel rounded-xl border border-line p-4 space-y-3">
        <h3 className="text-sm font-medium text-ink flex items-center gap-2">
          <ClipboardList size={16} className="text-iris" /> 发起质检
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            value={sessionInput}
            onChange={(e) => setSessionInput(e.target.value)}
            placeholder="输入会话 ID（session_id）"
            className="flex-1 min-w-[200px] bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-sm text-ink placeholder-ink-subtle focus:outline-none"
          />
          <button
            onClick={() => onInspect(sessionInput)}
            disabled={loading}
            className="px-4 py-1.5 bg-iris text-ink rounded-lg hover:bg-iris/80 disabled:opacity-50 text-sm flex items-center gap-1"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} 质检该会话
          </button>
          <button
            onClick={onBatch}
            disabled={loading}
            className="px-4 py-1.5 bg-panel-2 text-ink rounded-lg hover:bg-line disabled:opacity-50 text-sm"
          >
            批量抽检最近会话
          </button>
        </div>
        <p className="text-xs text-ink-subtle">提示：批量抽检会对最近 30 个会话异步质检。质检将使用下方「质检规则配置」中设定的唯一一套标准。</p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap text-sm">
        <span className="text-ink-subtle">筛选：</span>
        <FilterSelect
          value={filters.status || ''}
          onChange={(v) => setFilters((f: any) => ({ ...f, status: v || undefined }))}
          options={[{ value: '', label: '全部状态' }, { value: 'pending', label: '待复核' }, { value: 'reviewed', label: '已复核' }]}
        />
        <FilterSelect
          value={filters.min_score ? String(filters.min_score) : ''}
          onChange={(v) => setFilters((f: any) => ({ ...f, min_score: v ? Number(v) : undefined }))}
          options={[{ value: '', label: '全部分数' }, { value: '60', label: '≥60' }, { value: '80', label: '≥80' }, { value: '40', label: '≥40' }]}
        />
        <button onClick={onRefresh} className="px-2 py-1 text-ink-muted hover:text-ink">应用</button>
      </div>

      {/* List */}
      {loading && items.length === 0 ? (
        <div className="flex items-center justify-center py-16 text-ink-subtle">
          <Loader2 size={32} className="animate-spin" />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-ink-subtle">
          <ShieldCheck size={48} className="mb-4 opacity-30" />
          <p>还没有质检记录，先发起一次质检吧</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((it: QcInspection) => (
            <div
              key={it.id}
              onClick={() => onOpenDetail(it.id)}
              className="bg-panel rounded-xl border border-line p-4 flex items-center justify-between hover:border-line-strong transition-colors cursor-pointer"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={cn('text-lg font-bold', scoreColor(it.overall_score))}>
                    {it.overall_score != null ? it.overall_score : (it.scored ? '-' : '未评分')}
                  </span>
                  {!it.scored && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-panel-2/10 text-ink-muted">LLM 未评分</span>
                  )}
                  <StatusBadge status={it.status} />
                  {it.agent_name && <span className="text-xs text-ink-subtle">客服：{it.agent_name}</span>}
                </div>
                <p className="text-sm text-ink-subtle truncate">
                  {maskSessionId(it.session_id)} · {it.config_name || '默认'}
                  {it.violations && it.violations.length > 0 && ` · 违规 ${it.violations.length} 项`}
                </p>
              </div>
              <ChevronLeft size={18} className="text-ink-subtle ml-3 rotate-180" />
            </div>
          ))}
          {/* Pagination */}
          <div className="flex items-center justify-center gap-3 pt-2 text-sm text-ink-muted">
            <button disabled={page <= 1} onClick={() => onPage(page - 1)} className="px-3 py-1 rounded hover:bg-panel-2 disabled:opacity-40">上一页</button>
            <span>第 {page} 页 / 共 {Math.max(1, Math.ceil(total / 20))} 页（{total}）</span>
            <button disabled={page >= Math.ceil(total / 20)} onClick={() => onPage(page + 1)} className="px-3 py-1 rounded hover:bg-panel-2 disabled:opacity-40">下一页</button>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'text-warn bg-warn/10',
    reviewed: 'text-ok bg-ok/10',
  }
  return (
    <span className={cn('text-xs px-2 py-0.5 rounded-full', map[status] || 'text-ink-muted bg-panel-2/10')}>
      {status === 'pending' ? '待复核' : status === 'reviewed' ? '已复核' : status}
    </span>
  )
}

function FilterSelect({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-sm text-ink"
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ============ Detail Drawer ============
function DetailDrawer({ inspection, dimNameMap, onClose, onReviewed }: any) {
  const [humanScore, setHumanScore] = useState<number | ''>('')
  const [humanNotes, setHumanNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const scores: Record<string, number> = inspection.scores || {}
  const isReviewed = inspection.status === 'reviewed'

  const handleReview = async () => {
    setSaving(true); setErr('')
    try {
      const updated = await reviewInspection(inspection.id, {
        human_override_score: humanScore === '' ? undefined : Number(humanScore),
        human_notes: humanNotes || undefined,
      })
      onReviewed(updated)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '复核提交失败')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-scrim/50" onClick={onClose}>
      <div
        className="w-full max-w-2xl h-full bg-canvas border-l border-line overflow-y-auto p-6 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink flex items-center gap-2">
            <ShieldCheck size={20} className="text-iris" /> 质检详情 #{inspection.id}
          </h2>
          <button onClick={onClose} className="p-2 rounded-lg hover:bg-panel-2 text-ink-muted">✕</button>
        </div>

        <div className="flex items-center gap-4">
          <div className="bg-panel rounded-xl border border-line p-5 text-center flex-1">
            <p className="text-xs text-ink-subtle mb-1">AI 初评分</p>
            <p className={cn('text-4xl font-bold', scoreColor(inspection.overall_score))}>
              {inspection.overall_score != null ? inspection.overall_score : (inspection.scored ? '-' : '未评分')}
            </p>
          </div>
          <div className="bg-panel rounded-xl border border-line p-5 text-center flex-1">
            <p className="text-xs text-ink-subtle mb-1">人工复核分（终评）</p>
            <p className={cn('text-4xl font-bold', scoreColor(inspection.human_override_score))}>
              {inspection.human_override_score != null ? inspection.human_override_score : '-'}
            </p>
          </div>
        </div>
        <p className="text-xs text-ink-subtle -mt-3">AI 初评仅供参考，最终质量判定以人工复核为准。</p>

        {/* Dimension bars */}
        <div className="bg-panel rounded-xl border border-line p-4 space-y-2">
          <h3 className="text-sm font-medium text-ink mb-1">维度评分</h3>
          {Object.entries(scores).map(([k, v]) => (
            <div key={k} className="flex items-center gap-3">
              <span className="w-20 text-xs text-ink-muted">{dimNameMap[k] || k}</span>
              <div className="flex-1 h-2 bg-panel-2 rounded-full overflow-hidden">
                <div className={cn('h-full rounded-full', v >= 80 ? 'bg-ok' : v >= 60 ? 'bg-warn' : 'bg-bad')} style={{ width: `${v}%` }} />
              </div>
              <span className={cn('w-10 text-right text-xs font-medium', scoreColor(v))}>{v}</span>
            </div>
          ))}
          {Object.keys(scores).length === 0 && <p className="text-sm text-ink-subtle">无维度评分</p>}
        </div>

        {/* Violations */}
        {inspection.violations && inspection.violations.length > 0 && (
          <div className="bg-panel rounded-xl border border-line p-4 space-y-3">
            <h3 className="text-sm font-medium text-ink flex items-center gap-2">
              <AlertTriangle size={16} className="text-bad" /> 违规项（{inspection.violations.length}）
            </h3>
            {inspection.violations.map((v: any, i: number) => (
              <div key={i} className={cn('rounded-lg p-3 border', SEVERITY_COLORS[v.severity] || 'border-line')}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium">{v.type}</span>
                  {v.severity && <span className="text-xs opacity-70">· {v.severity}</span>}
                </div>
                {v.evidence && <p className="text-xs text-ink-muted mb-1">证据："{v.evidence}"</p>}
                {v.suggestion && <p className="text-xs text-ink">建议：{v.suggestion}</p>}
              </div>
            ))}
          </div>
        )}

        {/* Conversation snapshot */}
        {inspection.conversation_snapshot && (
          <div className="bg-panel rounded-xl border border-line p-4">
            <h3 className="text-sm font-medium text-ink mb-2">对话快照（已脱敏）</h3>
            <div className="space-y-1 max-h-64 overflow-y-auto text-sm">
              {inspection.conversation_snapshot.map((m: any, i: number) => (
                <p key={i} className={m.role === 'assistant' ? 'text-iris/90' : 'text-ink'}>
                  <span className="font-medium">{m.speaker || (m.role === 'assistant' ? '客服' : '客户')}：</span>
                  {m.content}
                </p>
              ))}
            </div>
          </div>
        )}

        {/* Summary & suggestions */}
        {inspection.summary && (
          <div className="bg-panel rounded-xl border border-line p-4">
            <h3 className="text-sm font-medium text-ink mb-1">总体评价</h3>
            <p className="text-sm text-ink whitespace-pre-wrap">{inspection.summary}</p>
          </div>
        )}
        {inspection.suggestions && (
          <div className="bg-panel rounded-xl border border-line p-4">
            <h3 className="text-sm font-medium text-ink mb-1">改进建议</h3>
            <p className="text-sm text-ink whitespace-pre-wrap">{inspection.suggestions}</p>
          </div>
        )}

        {/* Human review */}
        {!isReviewed ? (
          <div className="bg-panel rounded-xl border border-line p-4 space-y-3">
            <h3 className="text-sm font-medium text-ink flex items-center gap-2">
              <CheckCircle2 size={16} className="text-warn" /> 人工复核
            </h3>
            <div>
              <label className="text-xs text-ink-muted mb-1 block">复核总分 (0-100，留空则用 AI 分)</label>
              <input
                type="number" min={0} max={100}
                value={humanScore}
                onChange={(e) => setHumanScore(e.target.value === '' ? '' : Number(e.target.value))}
                className="w-32 bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-ink focus:outline-none"
              />
            </div>
            <div>
              <label className="text-xs text-ink-muted mb-1 block">复核备注</label>
              <textarea
                value={humanNotes}
                onChange={(e) => setHumanNotes(e.target.value)}
                rows={2}
                className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-2 text-ink text-sm focus:outline-none resize-none"
              />
            </div>
            {err && <p className="text-bad text-xs">{err}</p>}
            <button
              onClick={handleReview}
              disabled={saving}
              className="px-4 py-2 bg-warn text-canvas rounded-lg hover:bg-warn disabled:opacity-50 text-sm font-medium flex items-center gap-1"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} 提交复核
            </button>
          </div>
        ) : (
          <div className="bg-panel rounded-xl border border-warn/20 p-4">
            <h3 className="text-sm font-medium text-ink mb-1 flex items-center gap-2">
              <CheckCircle2 size={16} className="text-ok" /> 已复核
            </h3>
            <p className="text-xs text-ink-subtle">复核人：{inspection.reviewer || '未知'} · {inspection.reviewed_at || ''}</p>
            {inspection.human_notes && <p className="text-sm text-ink mt-1 whitespace-pre-wrap">{inspection.human_notes}</p>}
          </div>
        )}
      </div>
    </div>
  )
}

// ============ Insights Tab（数据回流 / 反向优化） ============
function InsightsTab({ feedback, onOpenDetail, onRefresh }: {
  feedback: QcFeedback | null
  onOpenDetail: (id: number) => void
  onRefresh: () => void
}) {
  if (!feedback) {
    return (
      <div className="flex-1 flex items-center justify-center text-ink-subtle">
        <Loader2 size={32} className="animate-spin" />
      </div>
    )
  }
  if (feedback.total === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-ink-subtle">
        <Lightbulb size={48} className="mb-4 opacity-30" />
        <p>暂无质检数据，无法生成优化洞察。先去做几次质检吧。</p>
      </div>
    )
  }

  const opt = feedback.optimization || {}
  const optCards: { title: string; items: string[]; cls: string }[] = [
    { title: '培训素材', items: opt.training_materials || [], cls: 'border-iris/30 text-info' },
    { title: '客服话术', items: opt.scripts || [], cls: 'border-ok/30 text-ok' },
    { title: '知识库切片', items: opt.knowledge_slices || [], cls: 'border-iris/30 text-iris' },
    { title: '内容生产方向', items: opt.content_direction || [], cls: 'border-warn/30 text-warn' },
  ]
  const maxDim = Math.max(1, ...feedback.weak_dimensions.map((d) => d.avg))

  return (
    <div className="flex-1 overflow-y-auto p-6 pt-4 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-ink flex items-center gap-2">
            <Lightbulb size={20} className="text-iris" /> 优化洞察（数据回流）
          </h2>
          <p className="text-xs text-ink-subtle mt-1">
            聚合错题场景、低分维度、主管复核与高频问题，反向指导培训素材 / 话术 / 知识库 / 内容方向。
          </p>
        </div>
        <button onClick={onRefresh} className="p-2 rounded-lg hover:bg-panel-2 text-ink-muted" title="刷新">
          <RefreshCw size={18} />
        </button>
      </div>

      {/* 低分维度 */}
      <div className="bg-panel rounded-xl border border-line p-4 space-y-2">
        <h3 className="text-sm font-medium text-ink mb-1 flex items-center gap-2">
          <BarChart3 size={16} className="text-iris" /> 低分维度（越靠上越薄弱）
        </h3>
        {feedback.weak_dimensions.length === 0 && <p className="text-sm text-ink-subtle">暂无维度评分数据</p>}
        {feedback.weak_dimensions.map((d) => (
          <div key={d.key} className="flex items-center gap-3">
            <span className="w-24 text-xs text-ink-muted">{d.name}</span>
            <div className="flex-1 h-2.5 bg-panel-2 rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full', d.avg >= 80 ? 'bg-ok' : d.avg >= 60 ? 'bg-warn' : 'bg-bad')}
                style={{ width: `${(d.avg / maxDim) * 100}%` }}
              />
            </div>
            <span className={cn('w-12 text-right text-xs font-medium', scoreColor(d.avg))}>{d.avg}</span>
          </div>
        ))}
      </div>

      {/* 高频违规 + 培训问题 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-panel rounded-xl border border-line p-4">
          <h3 className="text-sm font-medium text-ink mb-3 flex items-center gap-2">
            <AlertTriangle size={16} className="text-warn" /> 高频违规 TOP
          </h3>
          <div className="flex flex-wrap gap-2">
            {feedback.top_violations.map((v) => (
              <span key={v.type} className="px-2.5 py-1 rounded-full bg-bad/10 text-bad text-xs border border-bad/20">
                {v.type} · {v.count}
              </span>
            ))}
            {feedback.top_violations.length === 0 && <p className="text-sm text-ink-subtle">无违规记录</p>}
          </div>
        </div>
        <div className="bg-panel rounded-xl border border-line p-4">
          <h3 className="text-sm font-medium text-ink mb-3 flex items-center gap-2">
            <ClipboardList size={16} className="text-iris" /> 高频培训问题
          </h3>
          <ul className="space-y-1.5 text-sm text-ink list-disc list-inside">
            {feedback.training_topics.map((t, i) => <li key={i}>{t}</li>)}
            {feedback.training_topics.length === 0 && <p className="text-ink-subtle">暂无可提炼的培训问题</p>}
          </ul>
        </div>
      </div>

      {/* 错题场景 */}
      <div className="bg-panel rounded-xl border border-line p-4 space-y-2">
        <h3 className="text-sm font-medium text-ink mb-1">错题场景（低分 / 含违规的会话，点击查看详情）</h3>
        {feedback.wrong_cases.length === 0 && <p className="text-sm text-ink-subtle">暂无错题场景</p>}
        {feedback.wrong_cases.map((c) => (
          <div
            key={c.inspection_id}
            onClick={() => onOpenDetail(c.inspection_id)}
            className="flex items-center justify-between p-2.5 rounded-lg bg-canvas/40 hover:bg-panel-2 cursor-pointer"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className={cn('text-sm font-bold', scoreColor(c.overall_score))}>
                  {c.overall_score != null ? c.overall_score : '未评分'}
                </span>
                {c.weak_dimension && <span className="text-xs text-ink-subtle">最弱：{c.weak_dimension}</span>}
                {c.agent_name && <span className="text-xs text-ink-subtle">客服：{c.agent_name}</span>}
              </div>
              <p className="text-xs text-ink-subtle truncate">{maskSessionId(c.session_id)}</p>
            </div>
            <div className="flex gap-1 shrink-0 ml-3">
              {c.violations.map((v) => (
                <span key={v} className="px-2 py-0.5 rounded-full bg-bad/10 text-bad text-[10px] border border-bad/20">{v}</span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* 主管复核修正 */}
      {feedback.supervisor_corrections.length > 0 && (
        <div className="bg-panel rounded-xl border border-line p-4 space-y-2">
          <h3 className="text-sm font-medium text-ink mb-1">主管复核修正（AI 分 → 人工终评分）</h3>
          {feedback.supervisor_corrections.map((c) => (
            <div key={c.inspection_id} className="p-2.5 rounded-lg bg-canvas/40 space-y-1">
              <div className="flex items-center gap-2 text-sm">
                <span className={cn('font-bold', scoreColor(c.ai_score))}>AI {c.ai_score ?? '-'}</span>
                <ChevronLeft size={14} className="rotate-180 text-ink-subtle" />
                <span className={cn('font-bold', scoreColor(c.human_score))}>人工 {c.human_score}</span>
                {c.delta != null && (
                  <span className={cn('text-xs', c.delta < 0 ? 'text-bad' : c.delta > 0 ? 'text-ok' : 'text-ink-muted')}>
                    ({c.delta > 0 ? '+' : ''}{c.delta})
                  </span>
                )}
                <span className="text-xs text-ink-subtle ml-auto">{maskSessionId(c.session_id)}</span>
              </div>
              {c.human_notes && <p className="text-xs text-ink-muted">复核备注：{c.human_notes}</p>}
            </div>
          ))}
        </div>
      )}

      {/* 反向优化建议 */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-ink flex items-center gap-2">
          <Lightbulb size={16} className="text-warn" /> 反向优化建议
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {optCards.map((card) => (
            <div key={card.title} className={cn('bg-panel rounded-xl border p-4', card.cls)}>
              <h4 className="text-sm font-semibold mb-2">{card.title}</h4>
              <ul className="space-y-1 text-xs list-disc list-inside">
                {card.items.map((it, i) => <li key={i}>{it}</li>)}
                {card.items.length === 0 && <li className="text-ink-subtle list-none">暂无建议</li>}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ============ Config Form Tab（可视化配置，无需 JSON） ============
interface DimRow { name: string; weight: number; description: string }
interface ViolRow { name: string; severity: string; description: string }

function ConfigFormTab({ onChanged }: { onChanged: () => void }) {
  const [name, setName] = useState('通用客服标准')
  const [persona, setPersona] = useState('')
  const [model, setModel] = useState('deepseek-chat')
  const [threshold, setThreshold] = useState(60)
  const [dims, setDims] = useState<DimRow[]>([])
  const [viols, setViols] = useState<ViolRow[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr(''); setMsg('')
    try {
      const res = await getCurrentQcConfig()
      const cfg = res.current?.config || res.default
      setName(cfg.name || '通用客服标准')
      setPersona(cfg.business_persona || '')
      setModel(cfg.model || 'deepseek-chat')
      setThreshold(typeof cfg.pass_threshold === 'number' ? cfg.pass_threshold : 60)
      setDims((cfg.dimensions || []).map((d: any) => ({
        name: d.name || '',
        weight: Math.round((d.weight || 0) * 100),
        description: d.description || '',
      })))
      setViols((cfg.violations || []).map((v: any) => ({
        name: v.name || '',
        severity: v.severity || 'medium',
        description: v.description || '',
      })))
    } catch {
      setErr('加载质检配置失败')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const totalWeight = dims.reduce((s, d) => s + (Number(d.weight) || 0), 0)

  const save = async () => {
    setSaving(true); setErr(''); setMsg('')
    const payload: QcConfigSchema = {
      name: name.trim() || '通用客服标准',
      business_persona: persona.trim(),
      model,
      pass_threshold: Number(threshold),
      timeout_seconds: 60,
      max_retries: 1,
      language: 'zh',
      dimensions: dims
        .map((d, i) => ({
          key: slugify(d.name) || `dim_${i}`,
          name: d.name.trim(),
          weight: (Number(d.weight) || 0) / 100,
          description: d.description.trim(),
          scale: 100,
        }))
        .filter((d) => d.name),
      violations: viols
        .map((v, i) => ({
          key: slugify(v.name) || `vio_${i}`,
          name: v.name.trim(),
          severity: v.severity,
          description: v.description.trim(),
        }))
        .filter((v) => v.name),
    }
    try {
      await saveQcConfig(payload)
      setMsg('已保存质检规则')
      await onChanged()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '保存失败')
    } finally { setSaving(false) }
  }

  const handleSeed = async () => {
    setSaving(true); setErr(''); setMsg('')
    try {
      await seedDefaultQcConfig()
      setMsg('已恢复默认规则')
      await load()
      await onChanged()
    } catch { setErr('恢复默认失败') }
    finally { setSaving(false) }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-ink-subtle">
        <Loader2 size={32} className="animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 pt-4 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-ink flex items-center gap-2">
            <ListChecks size={20} className="text-iris" /> 质检规则配置
          </h2>
          <p className="text-xs text-ink-subtle mt-1">系统中只维护这一套标准，所有质检都会使用它。无需编写 JSON，直接填表即可。</p>
        </div>
        <button
          onClick={handleSeed}
          disabled={saving}
          className="px-3 py-1.5 bg-panel-2 text-ink rounded-lg hover:bg-line text-sm flex items-center gap-1 disabled:opacity-50"
        >
          <RotateCcw size={14} /> 恢复默认
        </button>
      </div>

      {err && (
        <div className="px-4 py-2 bg-bad/10 border border-bad/30 rounded-lg text-bad text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {err}
        </div>
      )}
      {msg && (
        <div className="px-4 py-2 bg-ok/10 border border-ok/30 rounded-lg text-ok text-sm flex items-center gap-2">
          <CheckCircle2 size={16} /> {msg}
        </div>
      )}

      {/* 基本信息 */}
      <div className="bg-panel rounded-xl border border-line p-4 space-y-4">
        <div className="px-3 py-2 rounded-lg bg-iris/10 border border-iris/20 text-xs text-info">
          AI 评分为「初评」工具，仅作参考；最终质量判定以人工复核为准。维度、权重、违规项、人设、及格线均可在此调整（评分模型与规则名称已按系统默认，无需填写）。
        </div>
        <div>
          <label className="text-sm text-ink-muted mb-1 block">业务人设（描述客服所属的业务场景，越具体越准）</label>
          <textarea
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            rows={2}
            placeholder="例如：你是示例商城的客服，负责解答用户关于霸王餐、返利提现、优惠券、积分兑换的咨询。"
            className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-2 text-ink text-sm focus:outline-none resize-none"
          />
        </div>
        <div className="w-40">
          <label className="text-sm text-ink-muted mb-1 block">及格线（0-100）</label>
          <input
            type="number" min={0} max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-ink text-sm focus:outline-none"
          />
        </div>
      </div>

      {/* 维度 */}
      <div className="bg-panel rounded-xl border border-line p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink">评分维度</h3>
          <button
            onClick={() => setDims((p) => [...p, { name: '', weight: 20, description: '' }])}
            className="px-3 py-1.5 bg-iris text-ink rounded-lg hover:bg-iris/80 text-sm flex items-center gap-1"
          >
            <Plus size={14} /> 添加维度
          </button>
        </div>
        <div className="space-y-2">
          {dims.map((d, i) => (
            <div key={i} className="flex items-start gap-2 bg-canvas/40 rounded-lg p-3">
              <div className="flex-1 grid grid-cols-1 md:grid-cols-12 gap-2">
                <input
                  value={d.name}
                  onChange={(e) => setDims((p) => p.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                  placeholder="维度名称，如 服务态度"
                  className="md:col-span-3 bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-ink text-sm focus:outline-none"
                />
                <div className="md:col-span-2 flex items-center gap-2">
                  <input
                    type="number" min={0} max={100}
                    value={d.weight}
                    onChange={(e) => setDims((p) => p.map((x, j) => j === i ? { ...x, weight: Number(e.target.value) } : x))}
                    className="w-full bg-panel-2 border border-line-strong rounded-lg px-2 py-1.5 text-ink text-sm focus:outline-none"
                  />
                  <span className="text-xs text-ink-subtle">%</span>
                </div>
                <input
                  value={d.description}
                  onChange={(e) => setDims((p) => p.map((x, j) => j === i ? { ...x, description: e.target.value } : x))}
                  placeholder="评判要点（会喂给 AI，越具体越好）"
                  className="md:col-span-7 bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-ink text-sm focus:outline-none"
                />
              </div>
              <button
                onClick={() => setDims((p) => p.filter((_, j) => j !== i))}
                className="p-1.5 rounded-lg hover:bg-line text-ink-subtle hover:text-bad"
                title="删除"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {dims.length === 0 && <p className="text-sm text-ink-subtle">暂无维度，点击「添加维度」。</p>}
        </div>
        <p className={cn('text-xs', Math.round(totalWeight) === 100 ? 'text-ink-subtle' : 'text-warn')}>
          权重合计：{Math.round(totalWeight)}%（建议合计为 100%）
        </p>
      </div>

      {/* 违规项 */}
      <div className="bg-panel rounded-xl border border-line p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink">违规项</h3>
          <button
            onClick={() => setViols((p) => [...p, { name: '', severity: 'medium', description: '' }])}
            className="px-3 py-1.5 bg-iris text-ink rounded-lg hover:bg-iris/80 text-sm flex items-center gap-1"
          >
            <Plus size={14} /> 添加违规项
          </button>
        </div>
        <div className="space-y-2">
          {viols.map((v, i) => (
            <div key={i} className="flex items-start gap-2 bg-canvas/40 rounded-lg p-3">
              <div className="flex-1 grid grid-cols-1 md:grid-cols-12 gap-2">
                <input
                  value={v.name}
                  onChange={(e) => setViols((p) => p.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                  placeholder="违规名称，如 隐私泄露"
                  className="md:col-span-3 bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-ink text-sm focus:outline-none"
                />
                <select
                  value={v.severity}
                  onChange={(e) => setViols((p) => p.map((x, j) => j === i ? { ...x, severity: e.target.value } : x))}
                  className="md:col-span-2 bg-panel-2 border border-line-strong rounded-lg px-2 py-1.5 text-ink text-sm focus:outline-none"
                >
                  {SEVERITY_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
                <input
                  value={v.description}
                  onChange={(e) => setViols((p) => p.map((x, j) => j === i ? { ...x, description: e.target.value } : x))}
                  placeholder="说明（会喂给 AI 识别）"
                  className="md:col-span-7 bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-ink text-sm focus:outline-none"
                />
              </div>
              <button
                onClick={() => setViols((p) => p.filter((_, j) => j !== i))}
                className="p-1.5 rounded-lg hover:bg-line text-ink-subtle hover:text-bad"
                title="删除"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {viols.length === 0 && <p className="text-sm text-ink-subtle">暂无违规项，点击「添加违规项」。</p>}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="px-5 py-2 bg-iris text-ink rounded-lg hover:bg-iris/80 disabled:opacity-50 text-sm font-medium flex items-center gap-1"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} 保存配置
        </button>
        <button
          onClick={load}
          disabled={saving}
          className="px-4 py-2 bg-panel-2 text-ink rounded-lg hover:bg-line disabled:opacity-50 text-sm"
        >
          取消修改
        </button>
      </div>
    </div>
  )
}
