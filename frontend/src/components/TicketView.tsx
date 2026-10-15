import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw, Plus, Search, X, Send, UserCog, Clock, CheckCircle2, AlertTriangle, LifeBuoy } from 'lucide-react'
import { cn, formatDateTime } from '../utils'
import { useToast } from '../contexts/ToastContext'
import {
  listTickets, getTicket, ticketStats, createTicket, updateTicketStatus, assignTicket, addTicketEvent,
  decideTicketAction,
  type TicketItem, type TicketDetail, type TicketListResponse, type TicketStats,
} from '../api'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  open: { label: '待处理', cls: 'text-amber-300 bg-amber-500/10 border-amber-500/30' },
  in_progress: { label: '处理中', cls: 'text-sky-300 bg-sky-500/10 border-sky-500/30' },
  resolved: { label: '已解决', cls: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30' },
  closed: { label: '已关闭', cls: 'text-gray-400 bg-gray-500/10 border-gray-500/30' },
}

const CATEGORY_OPTIONS = ['退款申请', '物流异常', '投诉建议', '商品问题', '订单查询', '其他']

function statusMeta(s: string) {
  return STATUS_META[s] ?? { label: s, cls: 'text-gray-400 bg-gray-500/10 border-gray-500/30' }
}

function priorityCls(p: number) {
  if (p >= 5) return 'text-rose-300 bg-rose-500/10 border-rose-500/30'
  if (p === 4) return 'text-amber-300 bg-amber-500/10 border-amber-500/30'
  if (p === 3) return 'text-sky-300 bg-sky-500/10 border-sky-500/30'
  return 'text-gray-400 bg-gray-500/10 border-gray-500/30'
}

function slaText(t: TicketItem) {
  if (!t.sla_due_at) return '—'
  const due = new Date(t.sla_due_at).getTime()
  const closed = t.status === 'resolved' || t.status === 'closed'
  if (closed) return formatDateTime(t.sla_due_at)
  const diffMin = Math.round((due - Date.now()) / 60000)
  if (diffMin < 0) return `已超时 ${Math.abs(diffMin)} 分钟`
  if (diffMin < 60) return `剩 ${diffMin} 分钟`
  if (diffMin < 1440) return `剩 ${Math.round(diffMin / 60)} 小时`
  return `剩 ${Math.round(diffMin / 1440)} 天`
}

interface TicketViewProps {
  /** 只看该会话的工单（从会话列表跳过来时传入），清除入口在工作台头部 */
  sessionFilter?: string | null
}

export default function TicketView({ sessionFilter = null }: TicketViewProps = {}) {
  const { showSuccess, showError } = useToast()
  const [stats, setStats] = useState<TicketStats | null>(null)
  const [data, setData] = useState<TicketListResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 20

  const [detail, setDetail] = useState<TicketDetail | null>(null)
  const [, setDetailLoading] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const [note, setNote] = useState('')
  const [assignInput, setAssignInput] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({ summary: '', category: '', priority: 3, assigned_to: '' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, list] = await Promise.all([
        ticketStats(),
        listTickets({
          status: statusFilter || undefined,
          category: categoryFilter || undefined,
          keyword: keyword || undefined,
          session_id: sessionFilter || undefined,
          page,
          page_size: pageSize,
        }),
      ])
      setStats(s)
      setData(list)
    } catch (e: any) {
      showError(`加载工单失败: ${e?.response?.data?.detail ?? e.message}`)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, categoryFilter, keyword, sessionFilter, page])

  useEffect(() => { load() }, [load])

  // 换了过滤的会话，页码必须归零，否则会停在上一页的空结果上
  useEffect(() => { setPage(1) }, [sessionFilter])

  const openDetail = async (id: number) => {
    setDetailLoading(true)
    try {
      const d = await getTicket(id)
      setDetail(d)
      setAssignInput(d.assigned_to ?? '')
      setNote('')
    } catch (e: any) {
      showError(`加载详情失败: ${e?.response?.data?.detail ?? e.message}`)
    } finally {
      setDetailLoading(false)
    }
  }

  const refreshDetail = async (id: number) => { await openDetail(id); await load() }

  const changeStatus = async (s: string) => {
    if (!detail) return
    let resolution: string | undefined
    if (s === 'resolved' || s === 'closed') {
      resolution = window.prompt('请输入处理结论（可留空）') || undefined
    }
    try {
      await updateTicketStatus(detail.id, s, { resolution, operator: '人工坐席' })
      showSuccess(`状态已更新为 ${statusMeta(s).label}`)
      await refreshDetail(detail.id)
    } catch (e: any) {
      showError(`更新失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const doAssign = async () => {
    if (!detail || !assignInput.trim()) return
    try {
      await assignTicket(detail.id, assignInput.trim(), '人工坐席')
      showSuccess('已指派')
      await refreshDetail(detail.id)
    } catch (e: any) {
      showError(`指派失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  // 坐席确认 Agent 挂起的动作：批准 → 后端 Command(resume) 续跑；驳回 → 动作不执行
  const decide = async (decision: 'approve' | 'reject') => {
    if (!detail) return
    let message: string | undefined
    if (decision === 'reject') {
      message = window.prompt('驳回理由（会写进工单时间线）') || undefined
    }
    setDeciding(true)
    try {
      const r = await decideTicketAction(detail.id, decision, '人工坐席', message)
      if (r.status === 'executed') {
        showSuccess(r.rma_no ? `已批准并执行，受理号 ${r.rma_no}` : '已批准并执行')
      } else if (r.status === 'rejected') {
        showSuccess('已驳回，动作未执行')
      } else {
        showSuccess(r.message || '已处理（重复操作已忽略）')
      }
      await refreshDetail(detail.id)
    } catch (e: any) {
      showError(`操作失败: ${e?.response?.data?.detail ?? e.message}`)
    } finally {
      setDeciding(false)
    }
  }

  const doAddNote = async () => {
    if (!detail || !note.trim()) return
    try {
      await addTicketEvent(detail.id, note.trim(), 'comment', '人工坐席')
      setNote('')
      showSuccess('备注已添加')
      await refreshDetail(detail.id)
    } catch (e: any) {
      showError(`添加失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const doCreate = async () => {
    if (!createForm.summary.trim()) { showError('请填写问题摘要'); return }
    try {
      await createTicket({
        summary: createForm.summary.trim(),
        category: createForm.category || null,
        priority: createForm.priority || null,
        assigned_to: createForm.assigned_to || null,
        source: 'manual',
      })
      showSuccess('工单已创建')
      setCreateOpen(false)
      setCreateForm({ summary: '', category: '', priority: 3, assigned_to: '' })
      setPage(1)
      await load()
    } catch (e: any) {
      showError(`创建失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const statCards = useMemo(() => ([
    { label: '工单总数', value: stats?.total ?? 0, icon: LifeBuoy, cls: 'text-indigo-300' },
    { label: '待处理', value: stats?.open_total ?? 0, icon: Clock, cls: 'text-amber-300' },
    { label: '已解决', value: stats?.resolved_total ?? 0, icon: CheckCircle2, cls: 'text-emerald-300' },
    { label: 'SLA 超时', value: stats?.sla_breached ?? 0, icon: AlertTriangle, cls: 'text-rose-300' },
  ]), [stats])

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-7xl mx-auto w-full p-6 space-y-5">
        {/* 统计卡 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {statCards.map((c) => (
            <div key={c.label} className="bg-dark-700 rounded-lg p-4 border border-dark-600">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">{c.label}</span>
                <c.icon size={16} className={c.cls} />
              </div>
              <div className={cn('text-2xl font-semibold mt-2', c.cls)}>{c.value}</div>
            </div>
          ))}
        </div>

        {/* 工具栏 */}
        <div className="flex flex-wrap items-center gap-2">
          <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
            className="px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200">
            <option value="">全部状态</option>
            <option value="open">待处理</option>
            <option value="in_progress">处理中</option>
            <option value="resolved">已解决</option>
            <option value="closed">已关闭</option>
          </select>
          <select value={categoryFilter} onChange={(e) => { setCategoryFilter(e.target.value); setPage(1) }}
            className="px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200">
            <option value="">全部分类</option>
            {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input value={keyword} onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
              placeholder="搜工单号/摘要"
              className="pl-8 pr-3 py-2 w-56 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200 placeholder:text-gray-600" />
          </div>
          <button onClick={() => load()} disabled={loading}
            className="px-3 py-2 bg-dark-700 hover:bg-dark-600 border border-dark-500 rounded-lg text-sm text-gray-200 flex items-center gap-1.5 disabled:opacity-50">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> 刷新
          </button>
          <div className="flex-1" />
          <button onClick={() => setCreateOpen(true)}
            className="px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium flex items-center gap-1.5">
            <Plus size={14} /> 新建工单
          </button>
        </div>

        {/* 列表 */}
        <div className="bg-dark-700 rounded-lg border border-dark-600 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-dark-600 bg-dark-800/40">
                <th className="px-4 py-3 font-medium">工单号</th>
                <th className="px-4 py-3 font-medium">分类</th>
                <th className="px-4 py-3 font-medium">优先级</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">摘要</th>
                <th className="px-4 py-3 font-medium">SLA</th>
                <th className="px-4 py-3 font-medium">创建时间</th>
                <th className="px-4 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-10 text-center text-gray-500">暂无工单</td></tr>
              ) : data!.items.map((t) => (
                <tr key={t.id} className="border-b border-dark-600/50 hover:bg-dark-600/30">
                  <td className="px-4 py-3 font-mono text-gray-200">{t.ticket_no}</td>
                  <td className="px-4 py-3 text-gray-300">{t.category || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={cn('text-[11px] px-2 py-0.5 rounded border', priorityCls(t.priority))}>P{t.priority}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={cn('text-[11px] px-2 py-0.5 rounded border', statusMeta(t.status).cls)}>
                      {statusMeta(t.status).label}
                    </span>
                    {t.pending_action?.awaiting && (
                      <span className="ml-1 text-[11px] px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300">
                        待确认
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-400 max-w-[260px] truncate" title={t.summary ?? ''}>{t.summary || '—'}</td>
                  <td className={cn('px-4 py-3 text-xs', t.sla_breached ? 'text-rose-300' : 'text-gray-400')}>{slaText(t)}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{t.created_at ? formatDateTime(t.created_at) : '—'}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => openDetail(t.id)} className="text-indigo-300 hover:text-indigo-200 text-xs">查看</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>共 {data.total} 条</span>
            <div className="flex items-center gap-2">
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                className="px-2 py-1 border border-dark-500 rounded disabled:opacity-40">上一页</button>
              <span>{data.page} / {data.total_pages}</span>
              <button disabled={page >= data.total_pages} onClick={() => setPage((p) => p + 1)}
                className="px-2 py-1 border border-dark-500 rounded disabled:opacity-40">下一页</button>
            </div>
          </div>
        )}
      </div>

      {/* 详情抽屉 */}
      {detail && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDetail(null)} />
          <div className="relative w-full max-w-xl h-full bg-dark-800 border-l border-dark-600 shadow-2xl flex flex-col">
            <div className="flex items-center justify-between px-5 py-4 border-b border-dark-600">
              <div>
                <div className="text-sm font-mono text-gray-100">{detail.ticket_no}</div>
                <div className="text-xs text-gray-500 mt-0.5">{detail.category} · P{detail.priority} · {detail.source}</div>
              </div>
              <button onClick={() => setDetail(null)} className="text-gray-400 hover:text-white"><X size={18} /></button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {/* 概要 */}
              <div className="bg-dark-700 rounded-lg p-4 space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-gray-500">状态</span>
                  <span className={cn('text-[11px] px-2 py-0.5 rounded border', statusMeta(detail.status).cls)}>{statusMeta(detail.status).label}</span>
                </div>
                <div className="flex justify-between"><span className="text-gray-500">SLA</span>
                  <span className={detail.sla_breached ? 'text-rose-300' : 'text-gray-300'}>{slaText(detail)}</span>
                </div>
                <div className="flex justify-between"><span className="text-gray-500">指派</span><span className="text-gray-300">{detail.assigned_to || '未分配'}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">会话</span><span className="text-gray-400 font-mono text-xs">{detail.session_id || '—'}</span></div>
                <div className="pt-2 border-t border-dark-600 text-gray-300">{detail.summary}</div>
                {detail.resolution && <div className="text-xs text-emerald-300">结论：{detail.resolution}</div>}
              </div>

              {/* 待确认动作（HITL）：Agent 挂起，等坐席拍板后才会真正执行 */}
              {detail.pending_action?.awaiting && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/[0.07] p-4 space-y-3">
                  <div className="flex items-start gap-2">
                    <AlertTriangle size={16} className="text-amber-300 mt-0.5 shrink-0" />
                    <div className="flex-1">
                      <div className="text-sm font-medium text-amber-200">待确认动作</div>
                      <div className="text-xs text-amber-100/80 mt-0.5">{detail.pending_action.title}</div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                    <div className="flex justify-between"><span className="text-gray-500">动作</span>
                      <span className="text-gray-300 font-mono">{detail.pending_action.tool}</span></div>
                    <div className="flex justify-between"><span className="text-gray-500">金额</span>
                      <span className="text-gray-200">¥{detail.pending_action.amount ?? 0}</span></div>
                    <div className="flex justify-between"><span className="text-gray-500">订单</span>
                      <span className="text-gray-300 font-mono">{detail.pending_action.order_id || '—'}</span></div>
                    <div className="flex justify-between"><span className="text-gray-500">原因</span>
                      <span className="text-gray-300 truncate max-w-[130px]" title={detail.pending_action.reason ?? ''}>
                        {detail.pending_action.reason || '—'}</span></div>
                  </div>
                  <div className="text-[11px] text-gray-500">
                    发起于 {detail.pending_action.requested_at ? formatDateTime(detail.pending_action.requested_at) : '—'}
                    {detail.pending_action.thread_id && (
                      <span className="ml-2 font-mono text-gray-600">thread {detail.pending_action.thread_id}</span>
                    )}
                  </div>
                  <div className="text-[11px] text-gray-500">
                    批准后会继续执行这次工具调用并生成受理号；驳回则不执行，Agent 会把理由转述给客户。
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button
                      disabled={deciding}
                      onClick={() => decide('approve')}
                      className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded text-xs"
                    >
                      批准并执行
                    </button>
                    <button
                      disabled={deciding}
                      onClick={() => decide('reject')}
                      className="px-3 py-1.5 bg-dark-700 border border-dark-500 text-gray-300 hover:text-white disabled:opacity-50 rounded text-xs"
                    >
                      驳回
                    </button>
                  </div>
                </div>
              )}

              {/* 已决策记录 */}
              {detail.pending_action && !detail.pending_action.awaiting && detail.pending_action.decision && (
                <div className="rounded-lg border border-dark-600 bg-dark-700/60 p-3 text-xs text-gray-400">
                  <span className="text-gray-500">上次确认：</span>
                  {detail.pending_action.decision === 'approve' ? '已批准执行' : '已驳回'}
                  {detail.pending_action.decided_by && <span> · {detail.pending_action.decided_by}</span>}
                  {!!detail.pending_action.result?.rma_no && (
                    <span className="ml-1 text-emerald-300 font-mono">{String(detail.pending_action.result.rma_no)}</span>
                  )}
                </div>
              )}

              {/* 操作 */}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => changeStatus('in_progress')} className="px-3 py-1.5 bg-sky-600/80 hover:bg-sky-600 text-white rounded text-xs">开始处理</button>
                <button onClick={() => changeStatus('resolved')} className="px-3 py-1.5 bg-emerald-600/80 hover:bg-emerald-600 text-white rounded text-xs">标记已解决</button>
                <button onClick={() => changeStatus('closed')} className="px-3 py-1.5 bg-gray-600/80 hover:bg-gray-600 text-white rounded text-xs">关闭工单</button>
                <button onClick={() => changeStatus('open')} className="px-3 py-1.5 bg-dark-700 border border-dark-500 text-gray-300 rounded text-xs">重开</button>
              </div>

              {/* 指派 */}
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <UserCog size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <input value={assignInput} onChange={(e) => setAssignInput(e.target.value)} placeholder="指派给（坐席/团队）"
                    className="w-full pl-8 pr-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200 placeholder:text-gray-600" />
                </div>
                <button onClick={doAssign} className="px-3 py-2 bg-dark-700 hover:bg-dark-600 border border-dark-500 rounded-lg text-sm text-gray-200">指派</button>
              </div>

              {/* 时间线 */}
              <div>
                <div className="text-xs font-medium text-gray-400 mb-2">时间线</div>
                <div className="space-y-3">
                  {detail.events.map((ev) => (
                    <div key={ev.id} className="flex gap-3">
                      <div className="mt-1 w-2 h-2 rounded-full bg-indigo-400 shrink-0" />
                      <div className="flex-1">
                        <div className="text-xs text-gray-300">{ev.content}</div>
                        <div className="text-[11px] text-gray-600 mt-0.5">
                          {ev.operator || 'system'} · {ev.created_at ? formatDateTime(ev.created_at) : ''}
                          {ev.event_type !== 'comment' && <span className="ml-1 text-indigo-400/70">[{ev.event_type}]</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                  {detail.events.length === 0 && <div className="text-xs text-gray-600">暂无事件</div>}
                </div>
              </div>
            </div>

            {/* 备注输入 */}
            <div className="p-4 border-t border-dark-600">
              <div className="flex gap-2">
                <input value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') doAddNote() }}
                  placeholder="添加处理备注…"
                  className="flex-1 px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200 placeholder:text-gray-600" />
                <button onClick={doAddNote} className="px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm flex items-center gap-1">
                  <Send size={14} /> 发送
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 新建工单弹窗 */}
      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setCreateOpen(false)} />
          <div className="relative w-full max-w-md bg-dark-800 border border-dark-600 rounded-xl shadow-2xl p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">新建工单</h3>
              <button onClick={() => setCreateOpen(false)} className="text-gray-400 hover:text-white"><X size={16} /></button>
            </div>
            <textarea value={createForm.summary} onChange={(e) => setCreateForm({ ...createForm, summary: e.target.value })}
              placeholder="问题摘要（必填）" rows={3}
              className="w-full px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200 placeholder:text-gray-600" />
            <div className="grid grid-cols-2 gap-2">
              <select value={createForm.category} onChange={(e) => setCreateForm({ ...createForm, category: e.target.value })}
                className="px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200">
                <option value="">自动分类</option>
                {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={createForm.priority} onChange={(e) => setCreateForm({ ...createForm, priority: Number(e.target.value) })}
                className="px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200">
                {[5, 4, 3, 2, 1].map((p) => <option key={p} value={p}>P{p} {p >= 5 ? '紧急' : p === 4 ? '高' : p === 3 ? '中' : p === 2 ? '低' : '最低'}</option>)}
              </select>
            </div>
            <input value={createForm.assigned_to} onChange={(e) => setCreateForm({ ...createForm, assigned_to: e.target.value })}
              placeholder="指派给（可选）"
              className="w-full px-3 py-2 bg-dark-700 border border-dark-500 rounded-lg text-sm text-gray-200 placeholder:text-gray-600" />
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={() => setCreateOpen(false)} className="px-3 py-2 text-sm text-gray-400 hover:text-white">取消</button>
              <button onClick={doCreate} className="px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm">创建</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
