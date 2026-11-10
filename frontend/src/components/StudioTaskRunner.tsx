// -*- coding: utf-8 -*-
/**
 * StudioTaskRunner — 按功能专属契约渲染的两阶段出图工作台
 *
 * 重设计要点：五个出图功能不再共用「一堆图 + 张数 + 比例」这一张表单。
 * 每个功能由 studioKinds.ts 描述自己的素材角色与专属选项：
 *   SKU 替换 = 底图 / 新商品图两个角色 + 投影处理，
 *   服装组图 = 上装 / 下装 / 模特三个角色 + 姿势场景，
 *   精修     = 单张原图 + 按勾选项逐项出图。
 * 所以进入不同功能，看到的表单、摘要、规划卡片内容都不一样。
 *
 * 流程仍是三步：配置 → 确认规划（人工闸门）→ 后台执行与结果。
 *
 * 端点选择是「运行时」的：功能只绑定候选链，这里选的是**本次**用哪个端点，
 * 只把选中项提前到链首，后面的 fallback 一个都不砍。没配可用端点时成图回落占位图，
 * 功能头卡、规划卡、结果卡都必须如实写出这一点，不能让人把占位图当成真成图。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Cpu,
  Image as ImagesIcon,
  Info,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Route,
  Sparkles,
  X,
} from 'lucide-react'
import { cn } from '../utils'
import {
  cancelStudioTask,
  confirmStudioTask,
  createStudioTask,
  getImageEndpoints,
  getMediaCategories,
  getStudioEngine,
  getStudioTask,
  listStudioTasks,
  retryStudioTask,
  type ImageEndpointsResponse,
  type MediaCategoryTree,
  type StudioEngineInfo,
  type StudioTask,
  type StudioTaskKind,
} from '../api'
import { useToast } from '../contexts/ToastContext'
import { STUDIO_ITEMS } from '../navigation'
import { kindLabel } from '../mediaCategories'
import StudioAssetSlotPicker from './StudioAssetSlotPicker'
import StudioEndpointChooser from './StudioEndpointChooser'
import {
  STUDIO_KIND_CONFIGS,
  describeForm,
  flattenAssetIds,
  initialFormValues,
  validateForm,
  type StudioField,
  type StudioFieldValues,
  type StudioSlotValues,
} from '../studioKinds'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  queued: { label: '排队中', cls: 'text-ink-subtle border-line/70 bg-panel-2/50' },
  planning: { label: '规划中', cls: 'text-info border-iris/30 bg-iris/10' },
  planned: { label: '待确认', cls: 'text-warn border-warn/30 bg-warn/10' },
  generating: { label: '生成中', cls: 'text-info border-iris/30 bg-iris/10' },
  done: { label: '已完成', cls: 'text-ok border-ok/30 bg-ok/10' },
  failed: { label: '失败', cls: 'text-bad border-bad/30 bg-bad/10' },
  cancelled: { label: '已取消', cls: 'text-ink-subtle border-line/70 bg-panel-2/50' },
}

const STEPS = [
  { n: 1, label: '配置输入' },
  { n: 2, label: '确认规划' },
  { n: 3, label: '执行与结果' },
]

export default function StudioTaskRunner({
  kind,
  onOpenEndpoints,
}: {
  kind: StudioTaskKind
  onOpenEndpoints?: () => void
}) {
  const config = STUDIO_KIND_CONFIGS[kind]
  const navItem = STUDIO_ITEMS.find((item) => item.pane === kind)
  const KindIcon = navItem?.icon ?? Sparkles
  const { showToast } = useToast()

  const [engine, setEngine] = useState<StudioEngineInfo | null>(null)
  const [tree, setTree] = useState<MediaCategoryTree | null>(null)
  const [slots, setSlots] = useState<StudioSlotValues>(() => initialFormValues(config).slots)
  const [fields, setFields] = useState<StudioFieldValues>(() => initialFormValues(config).fields)
  const [count, setCount] = useState(config.defaultCount)
  const [ratio, setRatio] = useState('1:1')
  const [note, setNote] = useState('')
  const [commonOpen, setCommonOpen] = useState(false)

  const [task, setTask] = useState<StudioTask | null>(null)
  const [recent, setRecent] = useState<StudioTask[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null)

  // 运行时端点选择：本次覆盖，不改服务绑定；额外的端点参数也只作用于本次
  const [endpointData, setEndpointData] = useState<ImageEndpointsResponse | null>(null)
  const [endpointKey, setEndpointKey] = useState('auto')
  const [endpointParamsText, setEndpointParamsText] = useState('')
  const [paramsOpen, setParamsOpen] = useState(false)

  const loadRecent = useCallback(async () => {
    try {
      // 只列本功能的任务：切功能不该看到别的功能的任务记录
      const data = await listStudioTasks({ kind, page_size: 8 })
      setRecent(data.items)
    } catch {
      setRecent([])
    }
  }, [kind])

  useEffect(() => {
    void getStudioEngine().then(setEngine).catch(() => setEngine(null))
    void loadRecent()
    void getMediaCategories().then(setTree).catch(() => setTree(null))
    void getImageEndpoints().then(setEndpointData).catch(() => setEndpointData(null))
  }, [loadRecent])

  // 组件在 StudioWorkbench 里有 key={pane}，但契约仍显式重置一次，防止将来去掉 key 时串状态
  useEffect(() => {
    const initial = initialFormValues(config)
    setSlots(initial.slots)
    setFields(initial.fields)
    setCount(initial.count)
    setRatio('1:1')
    setNote('')
    setTask(null)
    setError(null)
    setCommonOpen(false)
    setEndpointKey('auto')
    setEndpointParamsText('')
    setParamsOpen(false)
  }, [config])

  // 轮询：只在执行中跑，终态自动停并刷新列表
  useEffect(() => {
    if (!task || task.status !== 'generating') return
    let cancelled = false
    const poll = async () => {
      try {
        const { item } = await getStudioTask(task.id)
        if (!cancelled) {
          setTask(item)
          if (item.status !== 'generating') void loadRecent()
        }
      } catch {
        // 单次失败不打断轮询
      }
    }
    const timer = window.setInterval(() => void poll(), 700)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [task?.id, task?.status, loadRecent])

  useEffect(() => {
    if (!preview) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [preview])

  const step = useMemo(() => {
    if (!task) return 1
    if (task.status === 'planned') return 2
    return 3
  }, [task])

  /** 弹窗确认后整槽位写回；上传引起目录计数变化时刷新目录树 */
  const setSlotIds = (slotKey: string, ids: number[]) => {
    setSlots((previous) => ({ ...previous, [slotKey]: ids }))
  }

  const refreshTree = () => {
    void getMediaCategories().then(setTree).catch(() => undefined)
  }

  const setField = (key: string, value: string | string[]) => {
    setFields((previous) => ({ ...previous, [key]: value }))
  }

  /** 端点额外参数是自由 JSON；解析失败就拦在前端，别生成一条注定报错的任务 */
  const parseEndpointParams = (): Record<string, unknown> | null => {
    if (!endpointParamsText.trim()) return {}
    try {
      const parsed = JSON.parse(endpointParamsText)
      if (typeof parsed !== 'object' || !parsed || Array.isArray(parsed)) {
        setError('端点参数必须是一个 JSON 对象')
        return null
      }
      return parsed as Record<string, unknown>
    } catch (err) {
      setError(`端点参数 JSON 解析失败：${err instanceof Error ? err.message : '格式错误'}`)
      return null
    }
  }

  const handleCreate = async () => {
    const invalid = validateForm(config, slots, fields)
    if (invalid) {
      setError(invalid)
      return
    }
    const params = parseEndpointParams()
    if (!params) return
    setBusy(true)
    setError(null)
    try {
      const { item } = await createStudioTask({
        kind,
        asset_ids: flattenAssetIds(slots),
        count,
        ratio,
        note: note.trim() || undefined,
        config: { slots, fields },
        endpoint_key: endpointKey === 'auto' ? undefined : endpointKey,
        endpoint_params: params,
      })
      setTask(item)
      void loadRecent()
      showToast(`已生成规划：${item.plan?.shots.length ?? 0} 张，待确认`, 'success')
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || err?.message || '创建任务失败')
    } finally {
      setBusy(false)
    }
  }

  /** 规划页里改端点：重新出一版规划，让每张镜头「将用哪个端点」立刻跟着变 */
  const handleReplan = async (nextKey: string) => {
    const params = parseEndpointParams()
    if (!params) return
    setEndpointKey(nextKey)
    setBusy(true)
    setError(null)
    try {
      const { item } = await createStudioTask({
        kind,
        asset_ids: flattenAssetIds(slots),
        count,
        ratio,
        note: note.trim() || undefined,
        config: { slots, fields },
        endpoint_key: nextKey === 'auto' ? undefined : nextKey,
        endpoint_params: params,
      })
      setTask(item)
      void loadRecent()
      showToast('已按新端点重新生成规划', 'success')
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || err?.message || '重新规划失败')
    } finally {
      setBusy(false)
    }
  }

  const handleConfirm = async () => {
    if (!task) return
    setBusy(true)
    setError(null)
    try {
      const { item } = await confirmStudioTask(task.id)
      setTask(item)
      void loadRecent()
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || err?.message || '确认失败')
    } finally {
      setBusy(false)
    }
  }

  const handleCancel = async () => {
    if (!task) return
    try {
      const { item } = await cancelStudioTask(task.id)
      setTask(item)
      void loadRecent()
      showToast('已取消，未出图', 'info')
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || '取消失败')
    }
  }

  const handleRetry = async () => {
    if (!task) return
    try {
      const { item } = await retryStudioTask(task.id)
      setTask(item)
      void loadRecent()
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || '重跑失败')
    }
  }

  const reset = () => {
    const initial = initialFormValues(config)
    setTask(null)
    setSlots(initial.slots)
    setFields(initial.fields)
    setCount(initial.count)
    setRatio('1:1')
    setNote('')
    setError(null)
    setCommonOpen(false)
    setEndpointKey('auto')
    setEndpointParamsText('')
    setParamsOpen(false)
  }

  const openRecent = async (id: number) => {
    try {
      const { item } = await getStudioTask(id)
      setTask(item)
      const saved = item.input.config
      const initial = initialFormValues(config)
      if (saved?.slots) {
        const restored: StudioSlotValues = {}
        for (const slot of config.slots) restored[slot.key] = saved.slots[slot.key] ?? []
        setSlots(restored)
      } else {
        // 兼容没有 config 的旧任务：把扁平 asset_ids 放进第一个必选位
        const first = config.slots.find((slot) => slot.required) ?? config.slots[0]
        if (first) initial.slots[first.key] = (item.input.asset_ids ?? []).slice(0, first.max)
        setSlots(initial.slots)
      }
      if (saved?.fields) {
        for (const field of config.fields) {
          const value = saved.fields[field.key]
          if (value !== undefined) initial.fields[field.key] = value
        }
      }
      setFields(initial.fields)
      setCount(item.input.count ?? config.defaultCount)
      setRatio(item.input.ratio ?? '1:1')
      setNote(item.input.note ?? '')
      setEndpointKey(item.input.endpoint_key || 'auto')
      setEndpointParamsText(
        item.input.endpoint_params && Object.keys(item.input.endpoint_params).length
          ? JSON.stringify(item.input.endpoint_params, null, 2)
          : '',
      )
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '任务加载失败', 'error')
    }
  }

  const resultAssets = task?.outputs?.assets ?? []
  const finished = task?.status === 'done'
  const running = task?.status === 'generating'
  const summaryLines = describeForm(config, slots, fields, count)

  const capabilityLabel = (key: string) =>
    endpointData?.capabilities.find((cap) => cap.key === key)?.label ?? key
  const endpointName = (key: string) =>
    endpointData?.endpoints.find((endpoint) => endpoint.key === key)?.name ?? key
  const routes = task?.outputs?.routes ?? []
  const realRoutes = routes.filter((route) => !route.is_mock)
  const gatewayUsed = (task?.outputs?.engine ?? '') === 'gateway' || realRoutes.length > 0

  return (
    <div className="px-5 py-4 space-y-3.5">
      {/* 功能头卡：每个功能的图标 / 配色 / 一句话定位 / 产出都不同 */}
      <section className={cn('rounded-card border bg-panel/50 px-4 py-3 flex items-start gap-3', config.accent.border)}>
        <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0', config.accent.bg, config.accent.text)}>
          <KindIcon size={19} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[14px] font-medium text-ink">{navItem?.label ?? kind}</h3>
            {engine && !engine.is_mock ? (
              <span className="inline-flex items-center gap-1 rounded-pill border border-ok/30 bg-ok/10 px-2 py-0.5 text-[9px] text-ok">
                <Cpu size={9} /> 图像网关 · {engine.endpoint_count ?? 0} 个端点
              </span>
            ) : (
              <span className="rounded-pill border border-warn/30 bg-warn/10 px-2 py-0.5 text-[9px] text-warn">
                占位图兜底 · 未配可用端点
              </span>
            )}
            {onOpenEndpoints && (
              <button
                type="button"
                data-testid="task-goto-endpoints"
                onClick={onOpenEndpoints}
                className="inline-flex items-center gap-1 text-[10px] text-ink-subtle hover:text-flare transition-colors"
              >
                <Cpu size={10} /> 端点池 <ArrowRight size={9} />
              </button>
            )}
          </div>
          <p className="text-[11px] leading-relaxed text-ink-muted mt-1">{config.tagline}</p>
          <p className="text-[10px] text-ink-subtle mt-1">
            产出：{config.outputHint} · 本次端点：{endpointKey === 'auto' ? '按绑定链自动分派' : endpointName(endpointKey)}
          </p>
        </div>
      </section>

      <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1fr)_248px] items-start">
        <div className="min-w-0 space-y-3.5">
          {/* 步骤条 */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {STEPS.map((item, index) => (
              <div key={item.n} className="flex items-center gap-1.5">
                {index > 0 && <ChevronRight size={12} className="text-ink-subtle" />}
                <span
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1 text-[10px]',
                    step === item.n
                      ? cn(config.accent.border, config.accent.bg, 'text-ink')
                      : step > item.n
                        ? 'border-ok/30 bg-ok/10 text-ok'
                        : 'border-line/60 text-ink-subtle',
                  )}
                >
                  {step > item.n ? <Check size={10} /> : <span className="font-mono">{item.n}</span>}
                  {item.label}
                </span>
              </div>
            ))}
          </div>

          {/* 步骤 1：功能专属配置 */}
          {step === 1 && (
            <section className="rounded-card border border-line/70 bg-panel/50 p-4 space-y-3.5">
              <div className="flex items-center gap-2">
                <ImagesIcon size={14} className={config.accent.text} />
                <h4 className="text-[12px] font-medium text-ink">按角色选素材</h4>
                <span className="ml-auto font-mono text-[10px] text-ink-subtle">点槽位在弹窗里选图 / 上传</span>
              </div>

              <div className="space-y-2.5">
                {config.slots.map((slot) => (
                  <StudioAssetSlotPicker
                    key={slot.key}
                    slot={slot}
                    tree={tree}
                    accent={config.accent}
                    picked={slots[slot.key] ?? []}
                    onSetPicked={(ids) => setSlotIds(slot.key, ids)}
                    onUploaded={refreshTree}
                  />
                ))}
              </div>

              {/* 功能专属选项：这一块是五个功能差异最大的地方 */}
              {config.fields.length > 0 && (
                <div className="border-t border-line/60 pt-3 space-y-3">
                  <div className="flex items-center gap-2">
                    <Sparkles size={13} className={config.accent.text} />
                    <h4 className="text-[12px] font-medium text-ink">本功能的设置</h4>
                  </div>
                  {config.fields.map((field) => (
                    <FieldControl
                      key={field.key}
                      field={field}
                      accent={config.accent}
                      value={fields[field.key]}
                      onChange={(value) => setField(field.key, value)}
                    />
                  ))}
                </div>
              )}

              {/* 运行时端点选择：功能只绑定候选链，本次用哪个在这里定 */}
              <StudioEndpointChooser
                data={endpointData}
                service={kind}
                value={endpointKey}
                onChange={setEndpointKey}
                paramsText={endpointParamsText}
                onParamsTextChange={setEndpointParamsText}
                paramsOpen={paramsOpen}
                onToggleParams={() => setParamsOpen((open) => !open)}
                onOpenEndpoints={onOpenEndpoints}
              />

              {/* 通用设置收起来，别让它盖住功能专属配置 */}
              <div className="border-t border-line/60 pt-2.5">
                <button
                  type="button"
                  onClick={() => setCommonOpen((open) => !open)}
                  className="flex items-center gap-1.5 text-[11px] text-ink-muted hover:text-ink transition-colors"
                >
                  <ChevronDown size={12} className={cn('transition-transform', commonOpen && 'rotate-180')} />
                  通用设置
                  <span className="font-mono text-[10px] text-ink-subtle">
                    {count} 张 · {ratio}{note.trim() ? ' · 有补充要求' : ''}
                  </span>
                </button>
                {commonOpen && (
                  <div className="mt-3 space-y-3 pl-1">
                    <div className="grid sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] text-ink-muted mb-1.5">{config.countLabel}</label>
                        <div className="flex flex-wrap gap-1.5">
                          {[1, 2, 3, 4, 6, 8].map((value) => (
                            <button
                              key={value}
                              type="button"
                              onClick={() => setCount(value)}
                              className={cn(
                                'rounded-lg border px-2.5 py-1 font-mono text-[11px]',
                                count === value
                                  ? cn(config.accent.border, config.accent.bg, 'text-ink')
                                  : 'border-line/70 text-ink-subtle hover:text-ink hover:border-line-strong',
                              )}
                            >
                              {value}
                            </button>
                          ))}
                        </div>
                        <p className="text-[9px] text-ink-subtle mt-1.5">{config.countHint}</p>
                      </div>
                      <div>
                        <label className="block text-[11px] text-ink-muted mb-1.5">尺寸比例</label>
                        <div className="flex flex-wrap gap-1.5">
                          {(engine?.ratios ?? ['1:1', '3:4', '4:3', '16:9']).map((value) => (
                            <button
                              key={value}
                              type="button"
                              onClick={() => setRatio(value)}
                              className={cn(
                                'rounded-lg border px-2.5 py-1 font-mono text-[11px]',
                                ratio === value
                                  ? cn(config.accent.border, config.accent.bg, 'text-ink')
                                  : 'border-line/70 text-ink-subtle hover:text-ink hover:border-line-strong',
                              )}
                            >
                              {value}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div>
                      <label htmlFor="studio-note" className="block text-[11px] text-ink-muted mb-1.5">
                        补充要求 <span className="text-ink-subtle">（拼进每张提示词）</span>
                      </label>
                      <input
                        id="studio-note"
                        value={note}
                        maxLength={200}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="例：突出礼盒质感，背景干净"
                        className="w-full rounded-xl border border-line/70 bg-panel/60 px-3 py-2 text-[12px] text-ink placeholder:text-ink-subtle focus:border-flare/50 focus:outline-none"
                      />
                    </div>
                  </div>
                )}
              </div>

              {error && <ErrorLine message={error} />}

              <div className="flex items-center gap-3 pt-1 border-t border-line/60">
                <button
                  type="button"
                  onClick={() => void handleCreate()}
                  disabled={busy}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-pill border px-4 py-1.5 text-[12px] text-ink transition-colors disabled:opacity-60',
                    config.accent.border,
                    config.accent.bg,
                  )}
                >
                  {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  生成规划 <ArrowRight size={12} />
                </button>
                <span className="text-[10px] text-ink-subtle">只生成规划，不会出图</span>
              </div>
            </section>
          )}

          {/* 步骤 2：逐图规划（内容由后端按功能生成，前端只渲染 meta） */}
          {step === 2 && task?.plan && (
            <section className="rounded-card border border-line/70 bg-panel/50 p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <ClipboardList size={14} className={config.accent.text} />
                <h4 className="text-[12px] font-medium text-ink">逐图规划</h4>
                <span className="font-mono text-[10px] text-ink-subtle">{task.task_no}</span>
                <span className="ml-auto rounded-pill border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] text-warn">
                  规则引擎 · 未接 LLM
                </span>
              </div>
              <p className="text-[11px] text-ink-muted">{task.plan.summary}</p>

              {/* 确认闸门上也能改端点：改了就重新出一版规划，卡片里的「将用端点」立刻同步 */}
              <StudioEndpointChooser
                data={endpointData}
                service={kind}
                value={endpointKey}
                onChange={(key) => void handleReplan(key)}
                disabled={busy}
                paramsText={endpointParamsText}
                onParamsTextChange={setEndpointParamsText}
                paramsOpen={paramsOpen}
                onToggleParams={() => setParamsOpen((open) => !open)}
                onOpenEndpoints={onOpenEndpoints}
                compact
              />
              {task.plan.endpoint_warning && (
                <p className="rounded-lg border border-warn/30 bg-warn/10 px-2.5 py-1.5 text-[10px] text-warn">
                  {task.plan.endpoint_warning}
                </p>
              )}
              <p className="font-mono text-[10px] text-ink-subtle">
                {task.plan.shots.length} 个镜头 · 已按能力标签预演端点分派 · 实际命中以执行后的路由记录为准
              </p>

              {task.plan.warnings.length > 0 && (
                <div className="rounded-xl border border-warn/30 bg-warn/10 px-3 py-2 space-y-1">
                  {task.plan.warnings.map((warning) => (
                    <p key={warning} className="flex items-start gap-1.5 text-[10px] text-warn">
                      <AlertTriangle size={10} className="mt-0.5 flex-shrink-0" /> {warning}
                    </p>
                  ))}
                </div>
              )}

              <div className="grid gap-2 sm:grid-cols-2">
                {task.plan.shots.map((shot) => (
                  <div key={shot.index} className="rounded-xl border border-line/60 bg-panel-2/35 px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className={cn('font-mono text-[10px]', config.accent.text)}>
                        {String(shot.index).padStart(2, '0')}
                      </span>
                      <span className="text-[12px] text-ink truncate" title={shot.title}>{shot.title}</span>
                      <span className="ml-auto font-mono text-[9px] text-ink-subtle flex-shrink-0">{shot.size}</span>
                    </div>
                    {/* 专属元信息是「这一功能」的规划证据，不能省 */}
                    {(shot.meta ?? []).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {shot.meta.map((meta) => (
                          <span
                            key={`${meta.label}-${meta.value}`}
                            title={`${meta.label}：${meta.value}`}
                            className="rounded-md border border-line/70 bg-panel/60 px-1.5 py-0.5 text-[9px] text-ink-muted max-w-[150px] truncate"
                          >
                            <span className="text-ink-subtle">{meta.label}</span> {meta.value}
                          </span>
                        ))}
                      </div>
                    )}
                    {/* 规划阶段就把「这一镜头要做什么动作、将交给哪个端点」摊开，确认前能改 */}
                    <div className="flex flex-wrap items-center gap-1 mt-1.5">
                      <span className="rounded-md border border-iris/30 bg-iris/10 px-1.5 py-0.5 text-[9px] text-iris">
                        {capabilityLabel(shot.capability ?? 'img2img')}
                      </span>
                      <span
                        data-testid={`shot-endpoint-${shot.index}`}
                        title={shot.endpoint_options?.map((option) => option.name).join(' → ') || undefined}
                        className={cn(
                          'rounded-md border px-1.5 py-0.5 text-[9px] max-w-[170px] truncate',
                          shot.endpoint_ready
                            ? 'border-ok/30 bg-ok/10 text-ok'
                            : 'border-warn/30 bg-warn/10 text-warn',
                        )}
                      >
                        → {shot.endpoint_name ?? '内置占位图（兜底）'}
                      </span>
                      {shot.endpoint_ready && (shot.endpoint_options?.length ?? 0) > 1 && (
                        <span className="font-mono text-[9px] text-ink-subtle">
                          +{shot.endpoint_options!.length - 1} 个备选
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-ink-muted mt-1.5 leading-relaxed line-clamp-2">{shot.composition}</p>
                    <p className="text-[10px] text-ink-subtle mt-1 leading-relaxed line-clamp-2" title={shot.prompt}>
                      {shot.prompt}
                    </p>
                  </div>
                ))}
              </div>

              {error && <ErrorLine message={error} />}

              <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-line/60">
                <button
                  type="button"
                  onClick={() => void handleConfirm()}
                  disabled={busy}
                  className="inline-flex items-center gap-2 rounded-pill border border-ok/45 bg-ok/10 px-4 py-1.5 text-[12px] text-ink hover:border-ok/70 transition-colors disabled:opacity-60"
                >
                  {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={12} />}
                  确认规划，开始出图
                </button>
                <button
                  type="button"
                  onClick={() => void handleCancel()}
                  className="rounded-pill border border-line/70 px-3 py-1.5 text-[11px] text-ink-muted hover:text-ink hover:border-line-strong transition-colors"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={reset}
                  className="inline-flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-[11px] text-ink-subtle hover:text-ink transition-colors"
                >
                  <RotateCcw size={11} /> 改配置重来
                </button>
                <span className="ml-auto text-[10px] text-ink-subtle">确认后才会执行后台任务（当前无额度计费）</span>
              </div>
            </section>
          )}

          {/* 步骤 3：执行与结果 */}
          {step === 3 && task && (
            <section className="rounded-card border border-line/70 bg-panel/50 p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn('rounded-pill border px-2 py-0.5 text-[10px]', STATUS_META[task.status]?.cls)}>
                  {STATUS_META[task.status]?.label ?? task.status}
                </span>
                <span className="font-mono text-[11px] text-ink">{task.task_no}</span>
                <span className="ml-auto font-mono text-[10px] text-ink-subtle">
                  {task.done_shots}/{task.total_shots} 张 · {task.progress}%
                </span>
              </div>

              <div className="h-1.5 rounded-pill bg-panel-2 overflow-hidden">
                <div
                  className={cn('h-full rounded-pill transition-all', running ? 'bg-iris' : finished ? 'bg-ok' : 'bg-bad')}
                  style={{ width: `${Math.max(task.progress, 2)}%` }}
                />
              </div>

              {running && (
                <p className="flex items-center gap-1.5 text-[11px] text-ink-muted">
                  <Loader2 size={11} className="animate-spin text-iris" /> 后台生成中，结果会自动进素材库
                </p>
              )}
              {task.error && <ErrorLine message={task.error} />}

              {/* 逐镜头实际路由：命中了哪个端点、试过哪些、为什么回落，不藏在后端日志里 */}
              {routes.length > 0 && (
                <div data-testid="task-routes" className="rounded-xl border border-line/60 bg-panel-2/30 px-3 py-2.5">
                  <div className="flex items-center gap-2 mb-2">
                    <Route size={12} className="text-iris" />
                    <h5 className="text-[11px] font-medium text-ink">实际路由</h5>
                    <span className="font-mono text-[9px] text-ink-subtle">
                      {realRoutes.length}/{routes.length} 命中真实端点
                    </span>
                    {task.outputs?.endpoint_key && (
                      <span className="ml-auto rounded-md border border-line bg-panel/60 px-1.5 py-0.5 font-mono text-[9px] text-ink-subtle">
                        本次指定 {task.outputs.endpoint_key}
                      </span>
                    )}
                  </div>
                  <div className="space-y-1">
                    {routes.map((route) => {
                      const failed = route.attempts.filter((attempt) => !attempt.ok)
                      return (
                        <div key={route.index} className="flex flex-wrap items-center gap-1.5 text-[10px]">
                          <span className="font-mono text-ink-subtle">{String(route.index).padStart(2, '0')}</span>
                          <span className="text-ink-subtle">{capabilityLabel(route.capability)}</span>
                          <span className="text-ink-subtle">→</span>
                          <span className={route.is_mock ? 'text-warn' : 'text-ok'}>{route.endpoint_name}</span>
                          <span className="font-mono text-[9px] text-ink-subtle">
                            {route.protocol}{route.latency_ms ? ` · ${route.latency_ms}ms` : ''}
                          </span>
                          {failed.length > 0 && (
                            <span className="rounded-md border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[9px] text-warn">
                              试过 {failed.length} 个失败端点后{failed.length > 0 ? '切换' : ''}
                            </span>
                          )}
                          {route.is_mock && (
                            <span className="rounded-md border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[9px] text-warn">
                              占位图兜底
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {resultAssets.length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
                  {resultAssets.map((asset) => (
                    <button
                      key={asset.media_id}
                      type="button"
                      onClick={() => setPreview({ url: asset.url, title: asset.shot_title })}
                      className="group rounded-xl border border-line/60 bg-panel-2/30 overflow-hidden hover:border-flare/40 transition-colors"
                    >
                      <img src={asset.url} alt={asset.shot_title} loading="lazy" className="w-full aspect-square object-cover" />
                      <p className="px-2 py-1.5 text-[10px] text-ink-muted truncate text-left">
                        {String(asset.index).padStart(2, '0')} · {asset.shot_title}
                      </p>
                      <p className="px-2 pb-1.5 font-mono text-[9px] text-ink-subtle truncate text-left">
                        {asset.is_mock === false ? asset.endpoint_name ?? '真实端点' : '占位图兜底'}
                      </p>
                    </button>
                  ))}
                </div>
              )}

              {finished && (
                <div className="rounded-xl border border-ok/25 bg-ok/10 px-3 py-2">
                  <p className="text-[11px] text-ink-muted">
                    已产出 {resultAssets.length} 张
                    {gatewayUsed
                      ? `图（${realRoutes.length}/${routes.length || resultAssets.length} 张来自真实端点）`
                      : '占位图（端点池里还没有可用真实端点）'}
                    并写入素材库（一级目录「{kindLabel(tree, 'result')}」），可在素材库里复用、继续单图处理或删除。
                  </p>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-line/60">
                <button
                  type="button"
                  onClick={reset}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-flare/40 bg-flare/10 px-3.5 py-1.5 text-[11px] text-ink hover:border-flare/70 transition-colors"
                >
                  <RotateCcw size={11} /> 新建任务
                </button>
                {task.status === 'failed' && (
                  <button
                    type="button"
                    onClick={() => void handleRetry()}
                    className="inline-flex items-center gap-1.5 rounded-pill border border-line/70 px-3 py-1.5 text-[11px] text-ink-muted hover:text-ink transition-colors"
                  >
                    <RefreshCw size={11} /> 重跑
                  </button>
                )}
                {task.status === 'cancelled' && <span className="text-[10px] text-ink-subtle">该任务未出图</span>}
              </div>
            </section>
          )}
        </div>

        {/* 右侧：本次配置实时摘要 + 本功能的最近任务 */}
        <aside className="space-y-3 lg:sticky lg:top-0">
          <div className="rounded-card border border-line/70 bg-panel/40 p-3">
            <div className="flex items-center gap-2 mb-2.5">
              <Info size={13} className={config.accent.text} />
              <h4 className="text-[12px] font-medium text-ink">本次配置</h4>
            </div>
            <div className="space-y-1.5">
              {summaryLines.map((line, index) => (
                <p key={`${line}-${index}`} className="text-[10px] text-ink-muted leading-relaxed break-words">
                  <span className={cn('inline-block w-1 h-1 rounded-full mr-1.5 align-middle', config.accent.dot)} />
                  {line}
                </p>
              ))}
              <p className="text-[10px] text-ink-muted leading-relaxed break-words pt-1.5 mt-1 border-t border-line/60">
                <Cpu size={9} className="inline mr-1 align-middle text-iris" />
                端点：{endpointKey === 'auto' ? '按绑定链自动分派' : endpointName(endpointKey)}
                {endpointParamsText.trim() && ' · 带额外参数'}
              </p>
            </div>
          </div>

          <div className="rounded-card border border-line/70 bg-panel/40 p-3">
            <div className="flex items-center gap-2 mb-2.5">
              <ClipboardList size={13} className="text-ink-subtle" />
              <h4 className="text-[12px] font-medium text-ink">最近任务</h4>
              <span className="ml-auto font-mono text-[10px] text-ink-subtle">{recent.length}</span>
            </div>
            {recent.length === 0 ? (
              <p className="text-[10px] text-ink-subtle leading-relaxed py-3 text-center">本功能还没有任务</p>
            ) : (
              <div className="space-y-1">
                {recent.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => void openRecent(item.id)}
                    className={cn(
                      'w-full text-left rounded-xl border px-2.5 py-2 transition-colors',
                      task?.id === item.id ? 'border-flare/40 bg-flare/10' : 'border-transparent hover:bg-panel-2/60',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] text-ink truncate">{item.task_no}</span>
                      <span className={cn('ml-auto rounded-pill border px-1.5 py-0.5 text-[9px] flex-shrink-0', STATUS_META[item.status]?.cls)}>
                        {STATUS_META[item.status]?.label ?? item.status}
                      </span>
                    </div>
                    <p className="font-mono text-[9px] text-ink-subtle mt-1">
                      {item.total_shots} 张 · {item.input.ratio} · {item.progress}%
                    </p>
                  </button>
                ))}
              </div>
            )}
            <p className="text-[9px] text-ink-subtle mt-2 pt-2 border-t border-line/60 leading-relaxed">
              只显示「{navItem?.label}」的任务
            </p>
          </div>
        </aside>
      </div>

      {preview && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 bg-scrim/70 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={() => setPreview(null)}
        >
          <div className="max-w-3xl w-full rounded-card border border-line bg-panel overflow-hidden" onClick={(event) => event.stopPropagation()}>
            <header className="h-11 px-4 flex items-center gap-2 border-b border-line">
              <span className="text-[12px] text-ink truncate">{preview.title}</span>
              <button
                type="button"
                onClick={() => setPreview(null)}
                aria-label="关闭预览"
                className="ml-auto p-1.5 rounded-lg text-ink-subtle hover:text-ink hover:bg-panel-2"
              >
                <X size={15} />
              </button>
            </header>
            <div className="bg-canvas/60 flex items-center justify-center max-h-[70vh]">
              <img src={preview.url} alt={preview.title} className="max-h-[70vh] w-auto object-contain" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** 按契约渲染一个专属选项：多选 chips / 单选 chips / 文本框 */
function FieldControl({
  field,
  accent,
  value,
  onChange,
}: {
  field: StudioField
  accent: { text: string; bg: string; border: string }
  value: string | string[] | undefined
  onChange: (value: string | string[]) => void
}) {
  if (field.type === 'text') {
    return (
      <div>
        <label className="block text-[11px] text-ink-muted mb-1.5">
          {field.label}
          {field.hint && <span className="text-ink-subtle"> · {field.hint}</span>}
        </label>
        <input
          value={typeof value === 'string' ? value : ''}
          maxLength={field.maxLength}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.placeholder}
          className="w-full rounded-xl border border-line/70 bg-panel/60 px-3 py-2 text-[12px] text-ink placeholder:text-ink-subtle focus:border-flare/50 focus:outline-none"
        />
      </div>
    )
  }

  const picked = Array.isArray(value) ? value : typeof value === 'string' && value ? [value] : []
  const isMulti = field.type === 'multi'
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="text-[11px] text-ink-muted">{field.label}</span>
        {isMulti && field.min ? <span className="text-[9px] text-bad">至少 {field.min} 项</span> : null}
        <span className="ml-auto text-[9px] text-ink-subtle">{field.hint}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {field.options.map((option) => {
          const active = picked.includes(option.value)
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => {
                if (!isMulti) {
                  onChange(option.value)
                  return
                }
                onChange(active ? picked.filter((item) => item !== option.value) : [...picked, option.value])
              }}
              className={cn(
                'inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] transition-colors',
                active
                  ? cn(accent.border, accent.bg, 'text-ink')
                  : 'border-line/70 text-ink-subtle hover:text-ink hover:border-line-strong',
              )}
            >
              {active && <Check size={10} />}
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function ErrorLine({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/10 px-3 py-2">
      <AlertTriangle size={12} className="text-bad flex-shrink-0 mt-0.5" />
      <p className="text-[11px] text-bad">{message}</p>
    </div>
  )
}
