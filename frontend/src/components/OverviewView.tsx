// -*- coding: utf-8 -*-
/**
 * OverviewView — 全局数据看板
 *
 * 目标：把散落在「清洗与质检 / 工单 / 知识提炼 / 训练数据 / 会话记录」里的统计汇总到一页，
 * 按三条业务链路组织，并能直接下钻到对应模块。
 *
 * 数据契约：只调用现有 7 个统计端点，**不新增后端接口、不臆造字段**。
 * 用 Promise.allSettled 并发，任一数据源失败只让那一块降级为「暂不可用」，
 * 其余照常展示；登录失效仍由 api.ts 的 401 拦截器统一处理。
 *
 * 视觉约束：全部使用 ui/ 里的既有组件与语义色令牌，不引入新配色 / 字体 / 依赖。
 */
import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowUpRight,
  Database,
  GraduationCap,
  Layers,
  LifeBuoy,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import {
  getAdminStats,
  getExtractorStats,
  getKnowledgeStats,
  getQcStats,
  getSessions,
  getTrainingStatistics,
  ticketStats,
  type AdminStats,
  type ExtractorStats,
  type QcStats,
  type TicketStats,
  type TrainingStatistics,
} from '../api'
import { NAV_ITEM_BY_ID, type NavItem } from '../navigation'
import {
  Badge,
  Button,
  CategoryBars,
  ChartFrame,
  GlassCard,
  Progress,
  ScoreHistogram,
  Skeleton,
  StatCard,
  StatusDonut,
  toChartData,
} from './ui'

type KnowledgeStats = Awaited<ReturnType<typeof getKnowledgeStats>>

interface Snapshot {
  admin: AdminStats | null
  ticket: TicketStats | null
  qc: QcStats | null
  extractor: ExtractorStats | null
  knowledge: KnowledgeStats | null
  training: TrainingStatistics | null
  sessionTotal: number | null
}

const EMPTY_SNAPSHOT: Snapshot = {
  admin: null,
  ticket: null,
  qc: null,
  extractor: null,
  knowledge: null,
  training: null,
  sessionTotal: null,
}

const TICKET_STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  in_progress: '处理中',
  resolved: '已解决',
  closed: '已关闭',
}

const QC_SCORE_LABELS: Record<string, string> = {
  'low(<60)': '低分 <60',
  'mid(60-79)': '中分 60-79',
  'high(80+)': '高分 80+',
}

type ProgressTone = 'mint' | 'iris' | 'warn' | 'ok'

const DRILLS: Array<{
  id: string
  unit: string
  pick: (snapshot: Snapshot) => number | null
}> = [
  { id: 'agent-chat', unit: '在线会话', pick: () => null },
  { id: 'agent-ticket', unit: '工单', pick: (s) => s.ticket?.total ?? null },
  { id: 'chat-record', unit: '会话', pick: (s) => s.sessionTotal },
  { id: 'admin', unit: '质检记录', pick: (s) => s.qc?.total ?? null },
  { id: 'extractor', unit: '知识条目', pick: (s) => s.extractor?.total_articles ?? null },
  { id: 'training', unit: 'SFT 样本', pick: (s) => s.training?.sft_samples.total ?? null },
  { id: 'quiz', unit: 'AI 考核', pick: () => null },
  { id: 'custom', unit: '自定义对话', pick: () => null },
]

interface OverviewViewProps {
  onNavigate: (item: NavItem) => void
}

const formatNumber = (value: number | null | undefined): string =>
  value == null ? '—' : value.toLocaleString('zh-CN')

const ratio = (part: number | null | undefined, total: number | null | undefined): number | null => {
  if (part == null || total == null || total <= 0) return null
  return Math.round((part / total) * 100)
}

/** pass_rate 后端可能给 0–1，也可能给 0–100，统一成百分数 */
const asPercent = (value: number | null | undefined): number | null =>
  value == null ? null : Math.round((value <= 1 ? value * 100 : value) * 10) / 10

export default function OverviewView({ onNavigate }: OverviewViewProps) {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY_SNAPSHOT)
  const [failedSources, setFailedSources] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    const [admin, ticket, qc, extractor, knowledge, training, sessions] = await Promise.allSettled([
      getAdminStats(),
      ticketStats(),
      getQcStats(),
      getExtractorStats(),
      getKnowledgeStats(),
      getTrainingStatistics(),
      getSessions({ page: 1, page_size: 1 }),
    ])

    const failed: string[] = []
    const pick = <T,>(result: PromiseSettledResult<T>, label: string): T | null => {
      if (result.status === 'fulfilled') return result.value
      failed.push(label)
      return null
    }

    setSnapshot({
      admin: pick(admin, '清洗与质检'),
      ticket: pick(ticket, '工单'),
      qc: pick(qc, '质检评分'),
      extractor: pick(extractor, '知识提炼'),
      knowledge: pick(knowledge, '知识切片'),
      training: pick(training, '训练数据'),
      sessionTotal: pick(sessions, '会话记录')?.total ?? null,
    })
    setFailedSources(failed)
    setUpdatedAt(new Date())
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const s = snapshot
  const firstLoad = loading && !updatedAt
  const passRate = asPercent(s.qc?.pass_rate)
  const hasAnyData = [
    s.admin?.raw_chats.total,
    s.ticket?.total,
    s.qc?.total,
    s.extractor?.total_articles,
    s.training?.sft_samples.total,
    s.sessionTotal,
  ].some((value) => typeof value === 'number' && value > 0)

  const kpis = [
    {
      label: '原始消息',
      value: formatNumber(s.admin?.raw_chats.total),
      hint: s.admin ? `待清洗 ${formatNumber(s.admin.raw_chats.pending)} · 已驳回 ${formatNumber(s.admin.raw_chats.rejected)}` : '数据源暂不可用',
      icon: <Database size={17} />,
      tone: 'iris' as const,
    },
    {
      label: '会话总数',
      value: formatNumber(s.sessionTotal),
      hint: s.admin ? `已预处理 ${formatNumber(s.admin.sessions.processed)} / ${formatNumber(s.admin.sessions.total)}` : '数据源暂不可用',
      icon: <Layers size={17} />,
      tone: 'mint' as const,
    },
    {
      label: '工单总数',
      value: formatNumber(s.ticket?.total),
      hint: s.ticket ? `待处理 ${formatNumber(s.ticket.open_total)} · SLA 超时 ${formatNumber(s.ticket.sla_breached)}` : '数据源暂不可用',
      icon: <LifeBuoy size={17} />,
      tone: 'flare' as const,
    },
    {
      label: '质检记录',
      value: formatNumber(s.qc?.total),
      hint: s.qc ? `合格线 ${formatNumber(s.qc.threshold)} 分` : '数据源暂不可用',
      icon: <ShieldCheck size={17} />,
      tone: 'iris' as const,
    },
    {
      label: '质检均分',
      value: s.qc?.avg_score != null ? s.qc.avg_score.toFixed(1) : '—',
      hint: passRate != null ? `合格率 ${passRate}%` : '暂无评分数据',
      icon: <Sparkles size={17} />,
      tone: 'mint' as const,
    },
    {
      label: '知识条目',
      value: formatNumber(s.extractor?.total_articles),
      hint: s.extractor
        ? `已核验 ${formatNumber(s.extractor.verified_articles)} · 切片 ${formatNumber(s.knowledge?.total_chunks)}`
        : '数据源暂不可用',
      icon: <Sparkles size={17} />,
      tone: 'iris' as const,
    },
    {
      label: 'SFT 样本',
      value: formatNumber(s.training?.sft_samples.total),
      hint: s.training ? `已批准 ${formatNumber(s.training.sft_samples.approved)}` : '数据源暂不可用',
      icon: <GraduationCap size={17} />,
      tone: 'mint' as const,
    },
    {
      label: 'DPO 偏好对',
      value: formatNumber(s.training?.dpo_pairs.total),
      hint: s.training ? `已标注 ${formatNumber(s.training.dpo_pairs.annotated)} · 待标注 ${formatNumber(s.training.dpo_pairs.pending)}` : '数据源暂不可用',
      icon: <GraduationCap size={17} />,
      tone: 'flare' as const,
    },
  ]

  const health: Array<{ label: string; value: number | null; tone: ProgressTone }> = [
    { label: '会话预处理', value: ratio(s.admin?.sessions.processed, s.admin?.sessions.total), tone: 'mint' },
    { label: '清洗审核通过', value: ratio(s.admin?.staging_conversations.approved, s.admin?.staging_conversations.total), tone: 'iris' },
    { label: '质检合格率', value: passRate, tone: 'ok' },
    { label: '知识核验率', value: ratio(s.extractor?.verified_articles, s.extractor?.total_articles), tone: 'warn' },
    { label: 'SFT 批准率', value: ratio(s.training?.sft_samples.approved, s.training?.sft_samples.total), tone: 'mint' },
    { label: 'DPO 标注率', value: ratio(s.training?.dpo_pairs.annotated, s.training?.dpo_pairs.total), tone: 'iris' },
  ]

  const qcScoreData = s.qc
    ? Object.entries(s.qc.score_distribution ?? {}).map(([name, value]) => ({
        name: QC_SCORE_LABELS[name] ?? name,
        value: Number(value) || 0,
      }))
    : []

  const rawMessageData = s.admin
    ? [
        { name: '待清洗', value: s.admin.raw_chats.pending },
        { name: '已通过', value: s.admin.raw_chats.approved },
        { name: '已驳回', value: s.admin.raw_chats.rejected },
      ]
    : []

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="px-4 md:px-6 pt-5 pb-4 border-b border-line/60 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
        <div className="min-w-0">
          <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-ink-subtle">Global Overview</p>
          <h1 className="font-display text-xl font-bold text-ink mt-1">全局数据看板</h1>
          <p className="text-[11px] text-ink-subtle mt-1">
            汇总 7 个现有统计接口 · 按在线服务 / 数据治理 / 模型优化分组 · 点击卡片下钻
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {failedSources.length > 0 && (
            <Badge tone="warn" size="sm" dot>
              {failedSources.length} 个数据源暂不可用
            </Badge>
          )}
          <span className="font-mono text-[10px] text-ink-subtle">
            {updatedAt ? `更新于 ${updatedAt.toLocaleTimeString('zh-CN', { hour12: false })}` : '加载中'}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={loading}
            icon={<RefreshCw size={13} className={loading ? 'animate-spin' : ''} />}
            onClick={() => void load()}
          >
            刷新
          </Button>
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-4 md:px-6 py-5">
        {firstLoad ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
              {Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} variant="stat" />)}
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} variant="card" />)}
            </div>
          </div>
        ) : (
          <div className="space-y-5 pb-6">
            {!hasAnyData && (
              <GlassCard className="p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle size={17} className="text-warn mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm text-ink">当前各数据源均为空或暂不可用</p>
                    <p className="text-[11px] text-ink-subtle mt-1">
                      可先在「清洗与质检」跑预处理、在「智能客服工作台」产生工单，再回来刷新看板。
                    </p>
                  </div>
                </div>
              </GlassCard>
            )}
            {failedSources.length > 0 && (
              <p className="font-mono text-[10px] text-ink-subtle">
                降级数据源：{failedSources.join(' / ')}
              </p>
            )}

            {/* KPI 总览 */}
            <motion.div
              initial="hidden"
              animate="show"
              variants={{ show: { transition: { staggerChildren: 0.045 } } }}
              className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3"
            >
              {kpis.map((kpi) => <StatCard key={kpi.label} {...kpi} />)}
            </motion.div>

            {/* 闭环健康度：所有比例都由同源统计字段算出，不编造趋势 */}
            <GlassCard className="p-5">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-ink">数据闭环健康度</h2>
                  <p className="text-[11px] text-ink-subtle mt-1">每个环节的完成占比，取自对应统计接口</p>
                </div>
                <Badge tone="neutral" size="sm">{health.filter((item) => item.value != null).length} / {health.length} 可用</Badge>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
                {health.map((item) => <HealthMetric key={item.label} {...item} />)}
              </div>
            </GlassCard>

            {/* 三条链路：第一行看状态与分布 */}
            <div className="grid gap-4 lg:grid-cols-3">
              <ChartFrame
                title="在线服务 · 工单状态"
                subtitle={s.ticket ? `共 ${formatNumber(s.ticket.total)} 张 · 待处理 ${formatNumber(s.ticket.open_total)}` : '工单统计'}
                aside={s.ticket ? <Badge tone={s.ticket.sla_breached > 0 ? 'warn' : 'ok'} size="sm">SLA 超时 {s.ticket.sla_breached}</Badge> : undefined}
              >
                {s.ticket ? (
                  <StatusDonut data={toChartData(s.ticket.by_status, TICKET_STATUS_LABELS)} height={170} centerLabel="工单" unit="张" />
                ) : <Unavailable label="工单数据" />}
              </ChartFrame>

              <ChartFrame
                title="数据治理 · 原始消息状态"
                subtitle={s.admin ? `${formatNumber(s.admin.raw_chats.total)} 条原始消息` : '清洗统计'}
                aside={s.knowledge ? <Badge tone="iris" size="sm">{formatNumber(s.knowledge.total_chunks)} 切片</Badge> : undefined}
              >
                {rawMessageData.length ? <CategoryBars data={rawMessageData} unit=" 条" /> : <Unavailable label="清洗数据" />}
              </ChartFrame>

              <ChartFrame
                title="模型优化 · 质检分数分布"
                subtitle={s.qc ? `均分 ${s.qc.avg_score?.toFixed(1) ?? '—'} · 合格线 ${formatNumber(s.qc.threshold)}` : '质检统计'}
                aside={passRate != null ? <Badge tone="ok" size="sm">合格率 {passRate}%</Badge> : undefined}
              >
                {qcScoreData.length ? <ScoreHistogram data={qcScoreData} height={190} unit=" 条" /> : <Unavailable label="质检数据" />}
              </ChartFrame>
            </div>

            {/* 第二行看分类构成，便于判断问题集中在哪类业务 */}
            <div className="grid gap-4 lg:grid-cols-3">
              <ChartFrame title="工单分类 TOP" subtitle="按业务分类聚合">
                <CategoryBars data={toChartData(s.ticket?.by_category)} unit=" 张" max={6} emptyHint="暂无工单分类数据" />
              </ChartFrame>
              <ChartFrame title="知识类别分布" subtitle={s.extractor ? `平均置信度 ${(s.extractor.avg_confidence * 100).toFixed(1)}%` : '知识提炼统计'}>
                <CategoryBars data={toChartData(s.extractor?.by_category)} unit=" 条" max={6} emptyHint="暂无知识类别数据" />
              </ChartFrame>
              <ChartFrame title="DPO 业务分类" subtitle={s.training ? `已标注 ${formatNumber(s.training.dpo_pairs.annotated)} / ${formatNumber(s.training.dpo_pairs.total)}` : '训练数据统计'}>
                <CategoryBars data={toChartData(s.training?.dpo_pairs.by_category)} unit=" 对" max={6} emptyHint="暂无偏好对数据" />
              </ChartFrame>
            </div>

            {/* 下钻：看板 → 具体模块，避免只展示不能行动 */}
            <section>
              <h2 className="text-sm font-semibold text-ink mb-3">模块下钻</h2>
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
                {DRILLS.map((drill) => {
                  const item = NAV_ITEM_BY_ID[drill.id]
                  if (!item) return null
                  const Icon = item.icon
                  const value = drill.pick(s)
                  return (
                    <button
                      key={drill.id}
                      type="button"
                      onClick={() => onNavigate(item)}
                      title={item.desc}
                      className="glass group rounded-card p-4 text-left transition-shadow hover:shadow-glow"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="w-8 h-8 rounded-lg bg-iris/15 text-iris flex items-center justify-center flex-shrink-0">
                          <Icon size={16} />
                        </span>
                        <ArrowUpRight size={15} className="text-ink-subtle group-hover:text-ink transition-colors" />
                      </div>
                      <p className="text-[13px] font-medium text-ink mt-3 truncate">{item.label}</p>
                      <p className="font-mono text-[11px] text-ink-subtle mt-1">
                        {value == null ? '进入模块' : `${formatNumber(value)} ${drill.unit}`}
                      </p>
                    </button>
                  )
                })}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

function HealthMetric({ label, value, tone }: { label: string; value: number | null; tone: ProgressTone }) {
  return (
    <div className="rounded-xl border border-line/60 bg-panel-2/30 p-3">
      {value == null ? (
        <>
          <p className="text-[11px] text-ink-muted">{label}</p>
          <p className="font-mono text-[11px] text-ink-subtle mt-3">暂不可用</p>
        </>
      ) : (
        <Progress value={value} label={label} showLabel tone={tone} />
      )}
    </div>
  )
}

function Unavailable({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <AlertTriangle size={18} className="text-warn" />
      <p className="text-xs text-ink-subtle">{label}暂不可用，其余模块不受影响</p>
    </div>
  )
}
