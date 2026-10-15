import { useState, useEffect, useCallback } from 'react'
import {
  Target, Plus, Trash2, Loader2, RefreshCw, Play, AlertCircle, CheckCircle2,
  ChevronLeft, ChevronRight, X, AlertTriangle, TrendingUp,
} from 'lucide-react'
import {
  listCalibrationGroups, createCalibrationGroup, deleteCalibrationGroup,
  listCalibrationItems, deleteCalibrationItem,
  runCalibration, listCalibrationRuns, getCalibrationCompare, getCalibrationRun,
  getCurrentQcConfig, listQcConfigVersions,
  type CalibrationGroup, type CalibrationItem, type CalibrationRun,
  type CalibrationRunItem, type CalibrationCompareRow, type QcConfigVersionInfo,
} from '../api'
import QcCalibrationItemDialog from './QcCalibrationItemDialog'
import { cn, formatDateTime } from '../utils'
import { useToast } from '../contexts/ToastContext'
import { maskSessionId } from '../sessionDisplay'

const sc = (v: number | null | undefined, invert = false) => {
  if (v == null) return 'text-gray-400'
  const good = invert ? v <= 10 : v >= 80
  const mid = invert ? v <= 20 : v >= 60
  if (good) return 'text-green-400'
  if (mid) return 'text-yellow-400'
  return 'text-red-400'
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : (Math.round(v * 10 ** digits) / 10 ** digits).toFixed(digits)

/**
 * 校准对比：管理人工标注分组，用指定质检配置版本重跑质检并与冻真值对比。
 * 校准结果只存在校准表内，不影响主质检统计。
 */
export default function QcCalibrationView() {
  const { showSuccess, showError } = useToast()
  const [groups, setGroups] = useState<CalibrationGroup[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [items, setItems] = useState<CalibrationItem[]>([])
  const [versions, setVersions] = useState<QcConfigVersionInfo[]>([])
  const [compare, setCompare] = useState<CalibrationCompareRow[]>([])
  const [dimNames, setDimNames] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 运行详情
  const [activeRun, setActiveRun] = useState<CalibrationRun | null>(null)
  const [runItems, setRunItems] = useState<CalibrationRunItem[]>([])
  const [runPage, setRunPage] = useState(1)
  const [runTotal, setRunTotal] = useState(0)
  const [pollingRunId, setPollingRunId] = useState<number | null>(null)
  const [runVersionId, setRunVersionId] = useState<number | ''>('')
  const [running, setRunning] = useState(false)

  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [showAdd, setShowAdd] = useState(false)

  const loadGroups = useCallback(async () => {
    try {
      const res = await listCalibrationGroups()
      setGroups(res.items)
      setSelectedId((prev) => (prev != null && res.items.some((g) => g.id === prev) ? prev : res.items[0]?.id ?? null))
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载分组失败')
    }
  }, [])

  useEffect(() => {
    loadGroups()
    listQcConfigVersions().then((res) => setVersions(res.items)).catch(() => { /* ignore */ })
    getCurrentQcConfig()
      .then((res) => {
        const cfg = res.current?.config || res.default
        const map: Record<string, string> = {}
        for (const d of (cfg.dimensions || [])) map[d.key] = d.name
        setDimNames(map)
      })
      .catch(() => { /* ignore */ })
  }, [loadGroups])

  const loadGroupData = useCallback(async (groupId: number) => {
    setLoading(true)
    setError('')
    try {
      const [it, rs, cp] = await Promise.all([
        listCalibrationItems(groupId),
        listCalibrationRuns(groupId),
        getCalibrationCompare(groupId),
      ])
      setItems(it.items)
      setCompare(cp.items)
      const latest = rs.items[0]
      if (latest) {
        const detail = await getCalibrationRun(latest.id, 1, 20)
        setActiveRun(detail.run)
        setRunItems(detail.items)
        setRunTotal(detail.total)
        setRunPage(1)
        if (latest.status === 'pending' || latest.status === 'running') setPollingRunId(latest.id)
      } else {
        setActiveRun(null); setRunItems([]); setRunTotal(0)
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载校准数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedId != null) loadGroupData(selectedId)
  }, [selectedId, loadGroupData])

  // 轮询进行中的运行
  useEffect(() => {
    if (pollingRunId == null) return
    let cancelled = false
    const tick = async () => {
      try {
        const res = await getCalibrationRun(pollingRunId, 1, 20)
        if (cancelled) return
        setActiveRun(res.run)
        setRunItems(res.items)
        setRunTotal(res.total)
        setRunPage(1)
        if (res.run.status === 'done' || res.run.status === 'failed') {
          setPollingRunId(null)
          if (selectedId != null) {
            getCalibrationCompare(selectedId).then((c) => setCompare(c.items)).catch(() => { /* ignore */ })
          }
        }
      } catch {
        if (!cancelled) setPollingRunId(null)
      }
    }
    tick()
    const t = setInterval(tick, 2500)
    return () => { cancelled = true; clearInterval(t) }
  }, [pollingRunId, selectedId])

  const handleCreateGroup = async () => {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    try {
      const g = await createCalibrationGroup({ name })
      setNewName('')
      await loadGroups()
      setSelectedId(g.id)
      showSuccess('已创建分组')
    } catch (e: any) {
      showError(e?.response?.data?.detail || '创建分组失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteGroup = async (g: CalibrationGroup) => {
    if (!confirm(`删除分组「${g.name}」及其 ${g.item_count} 条标注、${g.run_count} 次运行记录？`)) return
    try {
      await deleteCalibrationGroup(g.id)
      await loadGroups()
      if (selectedId === g.id) setSelectedId(null)
      showSuccess('已删除分组')
    } catch (e: any) {
      showError(e?.response?.data?.detail || '删除失败')
    }
  }

  const handleDeleteItem = async (it: CalibrationItem) => {
    if (!confirm(`移除标注数据 ${maskSessionId(it.session_id)}？`)) return
    try {
      await deleteCalibrationItem(it.id)
      if (selectedId != null) await loadGroupData(selectedId)
      showSuccess('已移除')
    } catch (e: any) {
      showError(e?.response?.data?.detail || '删除失败')
    }
  }

  const handleRun = async () => {
    if (selectedId == null) return
    setRunning(true)
    setError('')
    try {
      const res = await runCalibration(selectedId, runVersionId === '' ? undefined : Number(runVersionId))
      setPollingRunId(res.run_id)
      showSuccess(`已提交校准运行（配置 v${res.config_version ?? '?'}）`)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '提交校准运行失败')
    } finally {
      setRunning(false)
    }
  }

  const handleRunPage = async (p: number) => {
    if (activeRun == null) return
    try {
      const res = await getCalibrationRun(activeRun.id, p, 20)
      setRunItems(res.items); setRunTotal(res.total); setRunPage(p)
    } catch { /* ignore */ }
  }

  const selectedGroup = groups.find((g) => g.id === selectedId) || null

  return (
    <div className="flex-1 flex bg-dark-900 overflow-hidden">
      {/* 左：分组 */}
      <div className="w-72 flex-shrink-0 border-r border-dark-600 flex flex-col">
        <div className="px-4 py-4 border-b border-dark-600">
          <h2 className="text-sm font-bold text-white flex items-center gap-2 mb-3">
            <Target size={16} className="text-accent-primary" /> 校准分组
          </h2>
          <div className="flex gap-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreateGroup() }}
              placeholder="新建分组名"
              className="flex-1 min-w-0 bg-dark-700 border border-dark-500 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none"
            />
            <button
              onClick={handleCreateGroup}
              disabled={creating || !newName.trim()}
              className="px-3 py-1.5 bg-accent-primary text-white rounded-lg hover:bg-accent-primary/80 disabled:opacity-50 text-sm flex items-center gap-1"
            >
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {groups.length === 0 && <p className="text-xs text-gray-500 p-3">暂无分组，先新建一个。</p>}
          {groups.map((g) => (
            <div
              key={g.id}
              onClick={() => setSelectedId(g.id)}
              className={cn(
                'group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer',
                selectedId === g.id ? 'bg-accent-primary/15 text-white' : 'text-gray-300 hover:bg-dark-700'
              )}
            >
              <div className="min-w-0">
                <p className="text-sm truncate">{g.name}</p>
                <p className="text-xs text-gray-500">{g.item_count} 条标注 · {g.run_count} 次运行</p>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteGroup(g) }}
                className="p-1 rounded text-gray-500 opacity-0 group-hover:opacity-100 hover:text-red-400"
                title="删除分组"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* 右：详情 */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {error && (
          <div className="mx-6 mt-4 px-4 py-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
            <AlertCircle size={16} /> {error}
          </div>
        )}
        {!selectedGroup ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <Target size={48} className="mb-4 opacity-30" />
            <p>选择或新建一个校准分组</p>
          </div>
        ) : (
          <div className="max-w-5xl mx-auto p-6 space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white">{selectedGroup.name}</h2>
                <p className="text-xs text-gray-500 mt-1">
                  用人工标注真值校准质检服务：重跑 AI 质检并与冻真值对比。校准结果不写入主质检列表。
                </p>
              </div>
              <button
                onClick={() => selectedId != null && loadGroupData(selectedId)}
                className="p-2 rounded-lg hover:bg-dark-700 text-gray-400"
                title="刷新"
              >
                <RefreshCw size={18} />
              </button>
            </div>

            {/* 操作条 */}
            <div className="bg-dark-800 rounded-xl border border-dark-600 p-4 flex flex-wrap items-center gap-3">
              <button
                onClick={() => setShowAdd(true)}
                className="px-4 py-2 bg-dark-700 text-gray-200 rounded-lg hover:bg-dark-600 text-sm flex items-center gap-1"
              >
                <Plus size={16} /> 添加标注数据
              </button>
              <div className="flex items-center gap-2 ml-auto">
                <span className="text-xs text-gray-500">配置版本</span>
                <select
                  value={runVersionId}
                  onChange={(e) => setRunVersionId(e.target.value === '' ? '' : Number(e.target.value))}
                  className="bg-dark-700 border border-dark-500 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none"
                >
                  <option value="">最新版本</option>
                  {versions.map((v) => (
                    <option key={v.id} value={v.id}>v{v.version}{v.is_current ? '（当前）' : ''}</option>
                  ))}
                </select>
                <button
                  onClick={handleRun}
                  disabled={running || pollingRunId != null || items.length === 0}
                  className="px-4 py-2 bg-accent-primary text-white rounded-lg hover:bg-accent-primary/80 disabled:opacity-50 text-sm flex items-center gap-1"
                >
                  {running || pollingRunId != null ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} 重跑校准
                </button>
              </div>
            </div>

            {/* 标注数据 */}
            <div className="bg-dark-800 rounded-xl border border-dark-600 p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">标注数据（{items.length}）</h3>
              {items.length === 0 ? (
                <p className="text-sm text-gray-500">暂无标注数据。可在此添加，或在「会话清洗与审核」列表中标记会话。</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-gray-500 border-b border-dark-600">
                        <th className="text-left py-2 pr-3">会话 ID</th>
                        <th className="text-right py-2 px-3">人工总分</th>
                        <th className="text-left py-2 px-3">各维度</th>
                        <th className="text-left py-2 px-3">加入时间</th>
                        <th className="py-2 pl-3"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it) => (
                        <tr key={it.id} className="border-b border-dark-700/60">
                          <td className="py-2 pr-3 text-gray-300 font-mono text-xs">{maskSessionId(it.session_id)}</td>
                          <td className={cn('py-2 px-3 text-right font-bold', sc(it.gold_total))}>{it.gold_total ?? '—'}</td>
                          <td className="py-2 px-3 text-xs text-gray-400">
                            {Object.entries(it.gold_scores || {}).map(([k, v]) => (
                              <span key={k} className="inline-block mr-2">{dimNames[k] || k}:{v}</span>
                            ))}
                            {Object.keys(it.gold_scores || {}).length === 0 && <span className="text-gray-600">—</span>}
                          </td>
                          <td className="py-2 px-3 text-xs text-gray-500">{it.created_at ? formatDateTime(it.created_at) : ''}</td>
                          <td className="py-2 pl-3 text-right">
                            <button onClick={() => handleDeleteItem(it)} className="p-1 rounded text-gray-500 hover:text-red-400" title="移除">
                              <X size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* 最近运行指标 */}
            {activeRun && (
              <div className="bg-dark-800 rounded-xl border border-dark-600 p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
                    <TrendingUp size={16} className="text-accent-primary" />
                    校准结果 · 配置 v{activeRun.config_version ?? '?'}
                    {activeRun.config_name ? `（${activeRun.config_name}）` : ''}
                  </h3>
                  <span className={cn(
                    'text-xs px-2 py-0.5 rounded-full',
                    activeRun.status === 'done' ? 'text-green-400 bg-green-500/10'
                      : activeRun.status === 'failed' ? 'text-red-400 bg-red-500/10'
                        : 'text-yellow-400 bg-yellow-500/10'
                  )}>
                    {activeRun.status === 'done' ? '已完成' : activeRun.status === 'failed' ? '失败' : `进行中 ${activeRun.done_count}/${activeRun.total}`}
                  </span>
                </div>

                {(activeRun.status === 'running' || activeRun.status === 'pending') && (
                  <div className="w-full bg-dark-600 rounded-full h-2">
                    <div
                      className="bg-accent-primary h-2 rounded-full transition-all"
                      style={{ width: `${activeRun.total > 0 ? (activeRun.done_count / activeRun.total) * 100 : 0}%` }}
                    />
                  </div>
                )}

                {activeRun.metrics && (
                  <>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <Metric label="总分 MAE（越低越准）" value={fmt(activeRun.metrics.mae_total)} cls={sc(activeRun.metrics.mae_total, true)} />
                      <Metric label="系统性偏差 bias" value={fmt(activeRun.metrics.bias)} cls={sc(activeRun.metrics.bias == null ? null : Math.abs(activeRun.metrics.bias), true)} />
                      <Metric label="及格一致率" value={activeRun.metrics.pass_agree_rate == null ? '—' : `${(activeRun.metrics.pass_agree_rate * 100).toFixed(0)}%`} />
                      <Metric label="维度均值差" value={fmt(activeRun.metrics.dim_mean_bias)} cls={sc(activeRun.metrics.dim_mean_bias == null ? null : Math.abs(activeRun.metrics.dim_mean_bias), true)} />
                    </div>

                    {(activeRun.metrics.dim_set_changed || activeRun.metrics.unscored_count > 0 || activeRun.metrics.missing_dim_count > 0) && (
                      <div className="px-3 py-2 bg-yellow-500/10 border border-yellow-500/20 rounded-lg text-xs text-yellow-300 space-y-1">
                        {activeRun.metrics.dim_set_changed && (
                          <p className="flex items-center gap-1"><AlertTriangle size={12} /> 人工标注维度与本次版本维度不一致（可能是配置改了维度），维度级指标仅供参考。</p>
                        )}
                        {activeRun.metrics.unscored_count > 0 && (
                          <p>有 {activeRun.metrics.unscored_count} 条 AI 未评分（LLM 不可用/超时/对话为空），已排除出指标。</p>
                        )}
                        {activeRun.metrics.missing_dim_count > 0 && (
                          <p>有 {activeRun.metrics.missing_dim_count} 条存在 LLM 漏答维度，对应维度已从维度偏差中剔除。</p>
                        )}
                      </div>
                    )}

                    {/* 维度偏差 */}
                    {Object.keys(activeRun.metrics.mae_by_dim).length > 0 && (
                      <div>
                        <h4 className="text-xs text-gray-400 mb-2">各维度平均绝对误差</h4>
                        <div className="space-y-1.5">
                          {Object.entries(activeRun.metrics.mae_by_dim).map(([k, v]) => (
                            <div key={k} className="flex items-center gap-3">
                              <span className="w-24 text-xs text-gray-400 truncate" title={dimNames[k] || k}>{dimNames[k] || k}</span>
                              <div className="flex-1 h-2 bg-dark-700 rounded-full overflow-hidden">
                                <div className={cn('h-full rounded-full', (v ?? 0) <= 10 ? 'bg-green-500' : (v ?? 0) <= 20 ? 'bg-yellow-500' : 'bg-red-500')} style={{ width: `${Math.min(100, (v ?? 0) * 3)}%` }} />
                              </div>
                              <span className={cn('w-12 text-right text-xs font-medium', sc(v, true))}>{fmt(v, 1)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}

                {activeRun.error && (
                  <p className="text-xs text-red-400">运行出错：{activeRun.error}</p>
                )}

                {/* 逐条对比 */}
                {activeRun.status === 'done' && runItems.length > 0 && (
                  <div className="overflow-x-auto">
                    <h4 className="text-xs text-gray-400 mb-2">逐条对比（AI vs 人工）</h4>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-gray-500 border-b border-dark-600">
                          <th className="text-left py-2 pr-3">会话 ID</th>
                          <th className="text-right py-2 px-3">AI</th>
                          <th className="text-right py-2 px-3">人工</th>
                          <th className="text-right py-2 px-3">差值</th>
                          <th className="text-center py-2 px-3">及格一致</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runItems.map((x) => (
                          <tr key={x.id} className="border-b border-dark-700/60">
                            <td className="py-2 pr-3 text-gray-300 font-mono text-xs">{maskSessionId(x.session_id)}</td>
                            <td className={cn('py-2 px-3 text-right', x.ai_scored ? sc(x.ai_total) : 'text-gray-500')}>
                              {x.ai_scored ? (x.ai_total ?? '—') : <span title={x.ai_error || ''}>未评分</span>}
                            </td>
                            <td className={cn('py-2 px-3 text-right', sc(x.gold_total))}>{x.gold_total ?? '—'}</td>
                            <td className={cn('py-2 px-3 text-right', x.delta_total == null ? 'text-gray-500' : x.delta_total > 0 ? 'text-green-400' : x.delta_total < 0 ? 'text-red-400' : 'text-gray-400')}>
                              {x.delta_total == null ? '—' : (x.delta_total > 0 ? '+' : '') + x.delta_total}
                            </td>
                            <td className="py-2 px-3 text-center">
                              {x.pass_agree == null ? <span className="text-gray-600">—</span>
                                : x.pass_agree ? <CheckCircle2 size={14} className="inline text-green-400" />
                                  : <X size={14} className="inline text-red-400" />}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="flex items-center justify-center gap-3 pt-3 text-sm text-gray-400">
                      <button disabled={runPage <= 1} onClick={() => handleRunPage(runPage - 1)} className="px-3 py-1 rounded hover:bg-dark-700 disabled:opacity-40 flex items-center gap-1">
                        <ChevronLeft size={14} /> 上一页
                      </button>
                      <span>第 {runPage} 页 / 共 {Math.max(1, Math.ceil(runTotal / 20))} 页（{runTotal}）</span>
                      <button disabled={runPage >= Math.ceil(runTotal / 20)} onClick={() => handleRunPage(runPage + 1)} className="px-3 py-1 rounded hover:bg-dark-700 disabled:opacity-40 flex items-center gap-1">
                        下一页 <ChevronRight size={14} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 跨版本对比 */}
            {compare.length > 0 && (
              <div className="bg-dark-800 rounded-xl border border-dark-600 p-4">
                <h3 className="text-sm font-medium text-gray-300 mb-3">跨版本对比（每个配置版本一次运行）</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-gray-500 border-b border-dark-600">
                        <th className="text-left py-2 pr-3">版本</th>
                        <th className="text-right py-2 px-2">样本</th>
                        <th className="text-right py-2 px-2">MAE</th>
                        <th className="text-right py-2 px-2">bias</th>
                        <th className="text-right py-2 px-2">及格一致</th>
                        <th className="text-right py-2 px-2">AI 维度均值</th>
                        <th className="text-right py-2 px-2">人工维度均值</th>
                        <th className="text-left py-2 pl-3">运行时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      {compare.map((c) => (
                        <tr key={c.run_id} className="border-b border-dark-700/60">
                          <td className="py-2 pr-3 text-gray-300">
                            v{c.config_version ?? '?'}
                            {c.dim_set_changed && <span className="ml-2 text-[10px] text-yellow-400">维度集变更</span>}
                          </td>
                          <td className="py-2 px-2 text-right text-gray-400">{c.item_count ?? '—'}</td>
                          <td className={cn('py-2 px-2 text-right font-medium', sc(c.mae_total, true))}>{fmt(c.mae_total)}</td>
                          <td className={cn('py-2 px-2 text-right', sc(c.bias == null ? null : Math.abs(c.bias), true))}>{fmt(c.bias)}</td>
                          <td className="py-2 px-2 text-right text-gray-300">{c.pass_agree_rate == null ? '—' : `${(c.pass_agree_rate * 100).toFixed(0)}%`}</td>
                          <td className="py-2 px-2 text-right text-gray-300">{fmt(c.ai_dim_mean, 1)}</td>
                          <td className="py-2 px-2 text-right text-gray-400">{fmt(c.gold_dim_mean, 1)}</td>
                          <td className="py-2 pl-3 text-xs text-gray-500">{c.created_at ? formatDateTime(c.created_at) : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-gray-500 mt-2">每版本单次运行，无方差估计；差值较小时建议多次运行再判断。</p>
              </div>
            )}

            {loading && (
              <div className="flex items-center justify-center py-8 text-gray-500">
                <Loader2 size={24} className="animate-spin mr-2" /> 加载中...
              </div>
            )}
          </div>
        )}
      </div>

      {showAdd && (
        <QcCalibrationItemDialog
          groups={groups}
          onClose={() => setShowAdd(false)}
          onCreated={() => { if (selectedId != null) loadGroupData(selectedId) }}
        />
      )}
    </div>
  )
}

function Metric({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-dark-700 rounded-lg p-3">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={cn('text-xl font-bold', cls || 'text-white')}>{value}</p>
    </div>
  )
}
