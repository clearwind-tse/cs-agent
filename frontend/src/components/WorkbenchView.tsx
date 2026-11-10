// -*- coding: utf-8 -*-
/**
 * WorkbenchView — 工作台
 *
 * 定位：登录后的行动起点，回答「今天先做哪件」。
 * 与「全局数据看板」分工：
 *   看板 = 有多少（跨链路统计、图表、下钻）
 *   工作台 = 要做什么（待办积压、真实条目、一键直达）
 *
 * 数据契约：只调用现有列表与统计端点，**不新增后端接口、不臆造字段**。
 * 积压数字取自各模块返回的 total，队列取前 5 条真实记录；
 * 任一数据源失败只让那一块降级，其余照常展示（Promise.allSettled）。
 *
 * 视觉约束：沿用 ui/ 既有组件与语义色令牌（glass / panel / line / ink / mint / iris / flare），
 * 不新增配色、字体与依赖。
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowUpRight,
  ClipboardCheck,
  Database,
  FileWarning,
  Inbox,
  LifeBuoy,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import {
  getAdminStats,
  getExtractorStats,
  getQcStats,
  getStagingConversations,
  getTrainingStatistics,
  listInspections,
  listTickets,
  ticketStats,
  type AdminStats,
  type ExtractorStats,
  type QcInspection,
  type QcStats,
  type StagingConversation,
  type TicketItem,
  type TicketListResponse,
  type TicketStats,
  type TrainingStatistics,
} from '../api'
import { NAV_ITEM_BY_ID, WORKSPACES, type NavItem } from '../navigation'
import { formatDateTime } from '../utils'
import { Badge, Button, GlassCard, Skeleton, StatCard } from './ui'

type StagingList = { total: number; items: StagingConversation[] }
type InspectionList = { total: number; items: QcInspection[] }

interface Snapshot {
  tickets: TicketListResponse | null
  ticketStats: TicketStats | null
  staging: StagingList | null
  admin: AdminStats | null
  qc: QcStats | null
  inspections: InspectionList | null
  extractor: ExtractorStats | null
  training: TrainingStatistics | null
}

const EMPTY: Snapshot = {
  tickets: null,
  ticketStats: null,
  staging: null,
  admin: null,
  qc: null,
  inspections: null,
  extractor: null,
  training: null,
}

const QUEUE_PREVIEW = 5

const formatNumber = (value: number | null | undefined): string =>
  value == null ? '—' : value.toLocaleString('zh-CN')

/** 后端 pass_rate 可能是 0–1 也可能是 0–100 */
const asPercent = (value: number | null | undefined): string => {
  if (value == null) return '—'
  const percent = value <= 1 ? value * 100 : value
  return `${Math.round(percent * 10) / 10}%`
}

/** 会话号只留尾部片段，避免长 agent-xxx id 挤掉分值徽标 */
const shortSession = (id: string | null | undefined): string => {
  if (!id) return '未知会话'
  return id.length > 14 ? `…${id.slice(-10)}` : id
}

const clip = (text: string | null | undefined, max = 42): string => {
  if (!text) return ''
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}

/** 工单优先级：数字越小越急，仅 1/2 需要视觉强调，避免满屏都是红点 */
const priorityTone = (priority: number): 'bad' | 'warn' | 'neutral' =>
  priority <= 1 ? 'bad' : priority === 2 ? 'warn' : 'neutral'

interface WorkbenchViewProps {
  onNavigate: (item: NavItem) => void
  /** 由 GlobalOverviewView 注入的视角切换 Tab */
  tabs?: ReactNode
}

export default function WorkbenchView({ onNavigate, tabs }: WorkbenchViewProps) {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY)
  const [failed, setFailed] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const load = useCallback(async () => {
    setLoading(true)

    const [tickets, tStats, staging, admin, qc, extractor, training] = await Promise.allSettled([
      listTickets({ status: 'open', page: 1, page_size: QUEUE_PREVIEW }),
      ticketStats(),
      getStagingConversations({ status: 'pending', page: 1, page_size: QUEUE_PREVIEW }),
      getAdminStats(),
      getQcStats(),
      getExtractorStats(),
      getTrainingStatistics(),
    ])

    const failures: string[] = []
    const pick = <T,>(result: PromiseSettledResult<T>, label: string): T | null => {
      if (result.status === 'fulfilled') return result.value
      failures.push(label)
      return null
    }

    const qcStats = pick(qc, '质检统计')

    // 低分质检需要「合格线」才能筛，因此晚一步取：拿不到统计就不筛，直接标记降级
    let inspections: InspectionList | null = null
    if (qcStats) {
      try {
        inspections = await listInspections({
          max_score: qcStats.threshold,
          page: 1,
          page_size: QUEUE_PREVIEW,
        })
      } catch {
        failures.push('低分质检')
      }
    } else {
      failures.push('低分质检')
    }

    setSnapshot({
      tickets: pick(tickets, '待处理工单'),
      ticketStats: pick(tStats, '工单统计'),
      staging: pick(staging, '待审对话'),
      admin: pick(admin, '清洗统计'),
      qc: qcStats,
      inspections,
      extractor: pick(extractor, '知识提炼'),
      training: pick(training, '训练数据'),
    })
    setFailed(failures)
    setUpdatedAt(new Date())
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const s = snapshot
  const firstLoad = loading && !updatedAt

  const openTickets = s.tickets?.total ?? s.ticketStats?.open_total ?? null
  const pendingStaging = s.staging?.total ?? null
  const lowScoreCount = s.inspections?.total ?? null
  const unverified = s.extractor?.unverified_articles ?? null

  const summary = [
    {
      label: '待处理工单',
      value: formatNumber(openTickets),
      unit: '张',
      hint: s.ticketStats ? `SLA 超时 ${formatNumber(s.ticketStats.sla_breached)} 张` : '工单统计暂不可用',
      icon: <LifeBuoy size={17} />,
      tone: 'flare' as const,
      item: NAV_ITEM_BY_ID['agent-ticket'],
      alarm: (s.ticketStats?.sla_breached ?? 0) > 0,
    },
    {
      label: '待审对话',
      value: formatNumber(pendingStaging),
      unit: '条',
      hint: s.admin ? `另有原始消息待清洗 ${formatNumber(s.admin.raw_chats.pending)} 条` : '清洗统计暂不可用',
      icon: <Inbox size={17} />,
      tone: 'iris' as const,
      item: NAV_ITEM_BY_ID['admin'],
    },
    {
      label: '未达合格线质检',
      value: formatNumber(lowScoreCount),
      unit: '条',
      hint: s.qc ? `合格线 ${formatNumber(s.qc.threshold)} 分 · 合格率 ${asPercent(s.qc.pass_rate)}` : '质检统计暂不可用',
      icon: <FileWarning size={17} />,
      tone: 'mint' as const,
      item: NAV_ITEM_BY_ID['admin'],
    },
    {
      label: '待核验知识',
      value: formatNumber(unverified),
      unit: '条',
      hint: s.extractor ? `共 ${formatNumber(s.extractor.total_articles)} 条 · 平均置信度 ${asPercent(s.extractor.avg_confidence)}` : '知识提炼暂不可用',
      icon: <Sparkles size={17} />,
      tone: 'iris' as const,
      item: NAV_ITEM_BY_ID['extractor'],
    },
  ]

  /** 每条链路给一句实况，避免入口卡只有图标 */
  const workspaceFacts: Record<string, string> = {
    run:
      openTickets == null && pendingStaging == null
        ? '数据源暂不可用'
        : `待处理工单 ${formatNumber(openTickets)} · 待审对话 ${formatNumber(pendingStaging)}`,
    data:
      s.admin == null
        ? '数据源暂不可用'
        : `待清洗 ${formatNumber(s.admin.raw_chats.pending)} · 未达线质检 ${formatNumber(lowScoreCount)} · 待核验 ${formatNumber(unverified)}`,
    train:
      s.training == null
        ? '数据源暂不可用'
        : `SFT 待批 ${formatNumber(s.training.sft_samples.total - s.training.sft_samples.approved)} · DPO 待标注 ${formatNumber(s.training.dpo_pairs.pending)}`,
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="px-4 md:px-6 pt-5 pb-4 border-b border-line/60 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
        <div className="min-w-0">
          <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-ink-subtle">Global Overview</p>
          <div className="flex flex-wrap items-center gap-3 mt-1">
            <h1 className="font-display text-xl font-bold text-ink">全局总览</h1>
            {tabs}
          </div>
          <p className="text-[11px] text-ink-subtle mt-1">
            待办视角 · 三类积压各取最新 {QUEUE_PREVIEW} 条，点条目直接进模块处理
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {failed.length > 0 && (
            <Badge tone="warn" size="sm" dot>
              {failed.length} 个数据源暂不可用
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
            <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
              {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} variant="stat" />)}
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} variant="card" />)}
            </div>
          </div>
        ) : (
          <div className="space-y-5 pb-6">
            {failed.length > 0 && (
              <p className="font-mono text-[10px] text-ink-subtle">降级数据源：{failed.join(' / ')}</p>
            )}

            {/* 积压摘要：数字本身就是入口 */}
            <motion.div
              initial="hidden"
              animate="show"
              variants={{ show: { transition: { staggerChildren: 0.045 } } }}
              className="grid grid-cols-2 xl:grid-cols-4 gap-3"
            >
              {summary.map((entry) => (
                <button
                  key={entry.label}
                  type="button"
                  onClick={() => entry.item && onNavigate(entry.item)}
                  title={entry.item ? `前往「${entry.item.label}」处理` : entry.label}
                  className="group text-left"
                >
                  <StatCard
                    label={entry.label}
                    value={
                      <span className="flex items-baseline gap-1">
                        {entry.value}
                        <span className="font-sans text-sm font-medium text-ink-subtle">{entry.unit}</span>
                      </span>
                    }
                    hint={entry.hint}
                    icon={entry.icon}
                    tone={entry.alarm ? 'flare' : entry.tone}
                    className="h-full transition-shadow group-hover:shadow-glow"
                  />
                </button>
              ))}
            </motion.div>

            {/* 待办队列：三条最需要人介入的队列，各取前 5 条真实记录 */}
            <section>
              <div className="flex flex-wrap items-end justify-between gap-2 mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink flex items-center gap-2">
                    <ListChecks size={15} className="text-mint" />
                    待办队列
                  </h2>
                  <p className="text-[11px] text-ink-subtle mt-1">
                    只列最需要人介入的三类 · 每类取最新 {QUEUE_PREVIEW} 条 · 点条目或「查看全部」进入模块
                  </p>
                </div>
                <Badge tone="neutral" size="sm">
                  {[openTickets, pendingStaging, lowScoreCount].filter((value) => (value ?? 0) > 0).length} / 3 类有待办
                </Badge>
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <QueuePanel
                  title="待处理工单"
                  subtitle="自动建单后等待坐席处理"
                  icon={<LifeBuoy size={15} />}
                  tone="flare"
                  count={openTickets}
                  unit="张"
                  failed={failed.includes('待处理工单')}
                  emptyText="没有待处理工单"
                  onOpenAll={() => onNavigate(NAV_ITEM_BY_ID['agent-ticket'])}
                >
                  {(s.tickets?.items ?? []).map((ticket) => (
                    <TicketRow
                      key={ticket.id}
                      ticket={ticket}
                      onOpen={() => onNavigate(NAV_ITEM_BY_ID['agent-ticket'])}
                    />
                  ))}
                </QueuePanel>

                <QueuePanel
                  title="待审对话"
                  subtitle="清洗结果等待人工通过或驳回"
                  icon={<ClipboardCheck size={15} />}
                  tone="iris"
                  count={pendingStaging}
                  unit="条"
                  failed={failed.includes('待审对话')}
                  emptyText="没有待审对话"
                  onOpenAll={() => onNavigate(NAV_ITEM_BY_ID['admin'])}
                >
                  {(s.staging?.items ?? []).map((item) => (
                    <StagingRow
                      key={item.id}
                      item={item}
                      onOpen={() => onNavigate(NAV_ITEM_BY_ID['admin'])}
                    />
                  ))}
                </QueuePanel>

                <QueuePanel
                  title="未达合格线质检"
                  subtitle={s.qc ? `分数 ≤ ${s.qc.threshold} 分，建议人工复核` : '需要质检统计才能筛'}
                  icon={<ShieldCheck size={15} />}
                  tone="mint"
                  count={lowScoreCount}
                  unit="条"
                  failed={failed.includes('低分质检')}
                  emptyText="没有低于合格线的记录"
                  onOpenAll={() => onNavigate(NAV_ITEM_BY_ID['admin'])}
                >
                  {(s.inspections?.items ?? []).map((inspection) => (
                    <InspectionRow
                      key={inspection.id}
                      inspection={inspection}
                      threshold={s.qc?.threshold ?? null}
                      onOpen={() => onNavigate(NAV_ITEM_BY_ID['admin'])}
                    />
                  ))}
                </QueuePanel>
              </div>
            </section>

            {/* 链路直达：由 IA 真源生成，新增视图自动出现在这里 */}
            <section>
              <div className="mb-3">
                <h2 className="text-sm font-semibold text-ink flex items-center gap-2">
                  <Database size={15} className="text-iris" />
                  按链路直达
                </h2>
                <p className="text-[11px] text-ink-subtle mt-1">
                  分组与顺序取自 navigation.ts，和左上角导航完全一致，不另立一套入口
                </p>
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                {WORKSPACES.map((workspace) => {
                  const Icon = workspace.icon
                  return (
                    <GlassCard key={workspace.id} className="p-4">
                      <div className="flex items-start gap-3">
                        <span className="w-9 h-9 rounded-xl bg-panel-3/70 text-ink-muted flex items-center justify-center flex-shrink-0">
                          <Icon size={16} />
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[13px] font-medium text-ink">
                            <span className="font-mono text-[10px] text-ink-subtle mr-1.5">{workspace.index}</span>
                            {workspace.label}
                          </p>
                          <p className="text-[10px] text-ink-subtle leading-relaxed mt-0.5">{workspace.desc}</p>
                        </div>
                      </div>

                      <p className="font-mono text-[10px] text-ink-subtle mt-3 truncate">
                        {workspaceFacts[workspace.id]}
                      </p>

                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {workspace.items.map((item) => {
                          const ItemIcon = item.icon
                          return (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => onNavigate(item)}
                              title={item.desc}
                              className="inline-flex items-center gap-1.5 rounded-pill border border-line/70 bg-panel-2/40 px-2.5 py-1 text-[11px] text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
                            >
                              <ItemIcon size={12} />
                              {item.label}
                            </button>
                          )
                        })}
                      </div>
                    </GlassCard>
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

/* ------------------------------------------------------------------ */
/* 队列容器：标题 / 计数 / 降级 / 空态统一处理                          */
/* ------------------------------------------------------------------ */

function QueuePanel({
  title,
  subtitle,
  icon,
  tone,
  count,
  unit,
  failed,
  emptyText,
  onOpenAll,
  children,
}: {
  title: string
  subtitle: string
  icon: ReactNode
  tone: 'mint' | 'iris' | 'flare'
  count: number | null
  unit: string
  failed: boolean
  emptyText: string
  onOpenAll: () => void
  children: ReactNode
}) {
  const items = Array.isArray(children) ? children : [children]
  const hasItems = items.filter(Boolean).length > 0

  return (
    <GlassCard className="p-0 overflow-hidden flex flex-col">
      <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-3 border-b border-line/50">
        <span className="mt-0.5 text-ink-muted flex-shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-ink flex items-center gap-2">
            {title}
            <Badge tone={tone} size="sm">
              {failed ? '降级' : `${formatNumber(count)} ${unit}`}
            </Badge>
          </p>
          <p className="text-[10px] text-ink-subtle mt-0.5 truncate">{subtitle}</p>
        </div>
      </div>

      <div className="flex-1 min-h-[132px] px-2 py-1.5">
        {failed ? (
          <div className="h-full flex flex-col items-center justify-center gap-1.5 py-6 text-center">
            <AlertTriangle size={16} className="text-warn" />
            <p className="text-[11px] text-ink-subtle">该数据源暂不可用，其余队列不受影响</p>
          </div>
        ) : hasItems ? (
          <ul className="divide-y divide-line/40">{children}</ul>
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-1.5 py-6 text-center">
            <ShieldCheck size={16} className="text-ok" />
            <p className="text-[11px] text-ink-subtle">{emptyText}</p>
          </div>
        )}
      </div>

      <div className="px-4 py-2 border-t border-line/50">
        <button
          type="button"
          onClick={onOpenAll}
          className="w-full flex items-center justify-between text-[11px] text-ink-muted transition-colors hover:text-ink"
        >
          查看全部
          <ArrowUpRight size={13} />
        </button>
      </div>
    </GlassCard>
  )
}

function RowShell({
  onClick,
  head,
  body,
  meta,
}: {
  onClick: () => void
  head: ReactNode
  body: ReactNode
  meta: ReactNode
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left px-2 py-2 rounded-lg transition-colors hover:bg-panel-2/60"
      >
        <div className="flex items-center gap-2">{head}</div>
        <p className="text-[11.5px] text-ink mt-1 leading-snug line-clamp-1">{body}</p>
        <div className="flex items-center gap-2 mt-1 font-mono text-[10px] text-ink-subtle">{meta}</div>
      </button>
    </li>
  )
}

function TicketRow({ ticket, onOpen }: { ticket: TicketItem; onOpen: () => void }) {
  return (
    <RowShell
      onClick={onOpen}
      head={
        <>
          <span className="font-mono text-[11px] text-ink">{ticket.ticket_no}</span>
          <Badge tone={priorityTone(ticket.priority)} size="sm">
            P{ticket.priority}
          </Badge>
          {ticket.pending_action?.awaiting && (
            <Badge tone="warn" size="sm" dot>
              待审批
            </Badge>
          )}
          {ticket.sla_breached && (
            <Badge tone="bad" size="sm">
              SLA 超时
            </Badge>
          )}
        </>
      }
      body={clip(ticket.summary) || '无摘要'}
      meta={
        <>
          <span>{ticket.category ?? '未分类'}</span>
          <span className="text-line-strong">·</span>
          <span>{formatDateTime(ticket.created_at) || '时间未知'}</span>
        </>
      }
    />
  )
}

function StagingRow({ item, onOpen }: { item: StagingConversation; onOpen: () => void }) {
  const score = item.auto_quality_score
  return (
    <RowShell
      onClick={onOpen}
      head={
        <>
          <span className="font-mono text-[11px] text-ink truncate max-w-[9rem]" title={item.session_id}>
            {shortSession(item.session_id)}
          </span>
          {score != null && (
            <Badge tone={score >= 80 ? 'ok' : score >= 60 ? 'warn' : 'bad'} size="sm">
              {Math.round(score)} 分
            </Badge>
          )}
        </>
      }
      body={clip(item.auto_question || item.cleaned_text) || '无清洗结果'}
      meta={
        <>
          <span>{item.human_category ?? item.auto_category ?? '未分类'}</span>
          <span className="text-line-strong">·</span>
          <span>{formatDateTime(item.created_at) || formatDateTime(item.start_time) || '时间未知'}</span>
        </>
      }
    />
  )
}

function InspectionRow({
  inspection,
  threshold,
  onOpen,
}: {
  inspection: QcInspection
  threshold: number | null
  onOpen: () => void
}) {
  const score = inspection.overall_score
  const violations = inspection.violations?.length ?? 0
  return (
    <RowShell
      onClick={onOpen}
      head={
        <>
          <span className="font-mono text-[11px] text-ink">
            {score == null ? '—' : Math.round(score)} 分
          </span>
          {threshold != null && score != null && (
            <Badge tone={score < threshold ? 'bad' : 'ok'} size="sm">
              线 {threshold}
            </Badge>
          )}
          {violations > 0 && (
            <Badge tone="warn" size="sm">
              违规 {violations}
            </Badge>
          )}
        </>
      }
      body={
        inspection.agent_name
          ? `坐席 ${inspection.agent_name} · ${shortSession(inspection.session_id)}`
          : shortSession(inspection.session_id)
      }
      meta={
        <>
          <span>{inspection.config_name ?? '默认质检配置'}</span>
          <span className="text-line-strong">·</span>
          <span>{formatDateTime(inspection.created_at) || '时间未知'}</span>
        </>
      }
    />
  )
}
