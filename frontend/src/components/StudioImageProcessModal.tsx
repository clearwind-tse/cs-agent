// -*- coding: utf-8 -*-
/**
 * StudioImageProcessModal — 素材库里对「一张已有图」做一次即时 AI 处理
 *
 * 与 studio_tasks 的区别：不需要逐图规划、不需要人工确认闸门，选完动作和端点直接执行；
 * 但走的是**同一个图像网关**，端点池 / 服务绑定 / fallback / 结果来源标注全部复用。
 * 服务固定为 adhoc：绑定链由端点页维护，这里选的端点同样只是本次覆盖。
 */
import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Check, Cpu, Loader2, Route, Sparkles, X } from 'lucide-react'
import { cn } from '../utils'
import { useToast } from '../contexts/ToastContext'
import {
  getImageEndpoints,
  getImageOperations,
  getMediaAsset,
  listImageJobs,
  processImageAsset,
  type ImageEndpointsResponse,
  type ImageProcessJob,
  type MediaAsset,
} from '../api'

interface StudioImageProcessModalProps {
  asset: MediaAsset
  onClose: () => void
  /** 有新素材入库时刷新素材库列表 / 统计 / 目录树 */
  onCompleted: () => void
}

const TERMINAL = new Set(['done', 'failed'])

const STATUS_TEXT: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  done: '已完成',
  failed: '失败',
}

export default function StudioImageProcessModal({ asset, onClose, onCompleted }: StudioImageProcessModalProps) {
  const { showToast } = useToast()
  const [operations, setOperations] = useState<Array<{ key: string; label: string }>>([])
  const [endpointData, setEndpointData] = useState<ImageEndpointsResponse | null>(null)
  const [operation, setOperation] = useState('upscale')
  const [endpointKey, setEndpointKey] = useState('auto')
  const [prompt, setPrompt] = useState('')
  const [job, setJob] = useState<ImageProcessJob | null>(null)
  const [jobs, setJobs] = useState<ImageProcessJob[]>([])
  const [result, setResult] = useState<MediaAsset | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    void getImageOperations().then((response) => setOperations(response.items)).catch(() => setOperations([]))
    void getImageEndpoints().then(setEndpointData).catch(() => setEndpointData(null))
    void listImageJobs({ asset_id: asset.id, page_size: 6 })
      .then((response) => setJobs(response.items))
      .catch(() => setJobs([]))
  }, [asset.id])

  // 后台任务进程内执行，前端按 job id 轮询；终态时把结果图拉回来预览
  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return
    let cancelled = false
    const poll = async () => {
      try {
        const response = await listImageJobs({ asset_id: asset.id, page_size: 20 })
        const found = response.items.find((item) => item.id === job.id)
        if (cancelled) return
        setJobs(response.items.slice(0, 6))
        if (!found) return
        setJob(found)
        if (TERMINAL.has(found.status)) {
          onCompleted()
          if (found.status === 'done' && found.result_asset_id) {
            const { items } = await getMediaAsset(found.result_asset_id)
            if (!cancelled) setResult(items ?? null)
          }
        }
      } catch {
        // 单次失败不打断轮询
      }
    }
    const timer = window.setInterval(() => void poll(), 800)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [job?.id, job?.status, asset.id, onCompleted])

  const capableEndpoints = useMemo(
    () => (endpointData?.endpoints ?? []).filter(
      (endpoint) => endpoint.protocol !== 'mock' && endpoint.enabled && endpoint.capabilities.includes(operation),
    ),
    [endpointData, operation],
  )
  const allReal = useMemo(
    () => (endpointData?.endpoints ?? []).filter(
      (endpoint) => endpoint.protocol !== 'mock' && endpoint.enabled,
    ),
    [endpointData],
  )
  const nameOf = (key: string) => endpointData?.endpoints.find((ep) => ep.key === key)?.name ?? key

  const submit = async () => {
    setSubmitting(true)
    setError('')
    setResult(null)
    try {
      const response = await processImageAsset({
        asset_id: asset.id,
        operation,
        endpoint_key: endpointKey === 'auto' ? undefined : endpointKey,
        params: prompt.trim() ? { prompt: prompt.trim() } : {},
      })
      setJob(response.item)
      setJobs((previous) => [response.item, ...previous].slice(0, 6))
      showToast('已提交，后台正在处理这张图', 'success')
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || err?.message || '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const busy = submitting || (job != null && !TERMINAL.has(job.status))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/70 backdrop-blur-sm px-4"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`AI 处理 ${asset.original_name}`}
        data-testid="image-process-modal"
        className="w-full max-w-3xl max-h-[88vh] overflow-y-auto rounded-2xl border border-line bg-panel shadow-xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-center gap-2 border-b border-line bg-panel px-5 py-3">
          <Sparkles size={15} className="text-flare" />
          <div className="min-w-0">
            <h3 className="text-sm font-medium text-ink">AI 动态处理 · 单图即席</h3>
            <p className="text-[10px] text-ink-subtle truncate">{asset.original_name}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭" className="ml-auto text-ink-subtle hover:text-ink"><X size={16} /></button>
        </header>

        <div className="px-5 py-4 grid gap-4 sm:grid-cols-[220px_minmax(0,1fr)]">
          <div className="space-y-2">
            <div className="rounded-xl border border-line bg-canvas/50 overflow-hidden">
              <img src={asset.url} alt={asset.original_name} className="w-full aspect-square object-contain" />
            </div>
            <p className="font-mono text-[9px] text-ink-subtle break-all">源素材 #{asset.id}</p>
            {result && (
              <div className="rounded-xl border border-ok/30 bg-ok/[0.06] overflow-hidden">
                <img src={result.url} alt="处理结果" className="w-full aspect-square object-contain" />
                <p className="px-2 py-1 text-[10px] text-ok truncate">结果 #{result.id} · {result.original_name}</p>
              </div>
            )}
          </div>

          <div className="space-y-3">
            <div className="rounded-xl border border-iris/25 bg-iris/[0.05] px-3 py-2.5">
              <div className="flex items-center gap-1.5"><Cpu size={12} className="text-iris" /><h4 className="text-[11px] font-medium text-ink">动作 + 端点</h4></div>
              <p className="text-[10px] text-ink-subtle leading-relaxed mt-1">
                动作就是能力标签，网关只把这张图交给能做这件事的端点；这里选的端点只覆盖本次，失败仍按 adhoc 服务的绑定链 fallback。
              </p>
            </div>

            <label className="block">
              <span className="block font-mono text-[9px] text-ink-subtle uppercase tracking-wider mb-1">处理动作</span>
              <select
                data-testid="image-process-operation"
                value={operation}
                onChange={(event) => { setOperation(event.target.value); setEndpointKey('auto') }}
                className="w-full h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink outline-none focus:border-flare/60"
              >
                {operations.map((item) => (
                  <option key={item.key} value={item.key}>{item.label} · {item.key}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="block font-mono text-[9px] text-ink-subtle uppercase tracking-wider mb-1">
                本次端点 · 有 {capableEndpoints.length} 个端点声明了该能力
              </span>
              <select
                data-testid="image-process-endpoint"
                value={endpointKey}
                onChange={(event) => setEndpointKey(event.target.value)}
                className="w-full h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink outline-none focus:border-flare/60"
              >
                <option value="auto">auto · 按 adhoc 绑定链自动分派</option>
                {(capableEndpoints.length ? capableEndpoints : allReal).map((endpoint) => (
                  <option key={endpoint.key} value={endpoint.key}>
                    {endpoint.name}{endpoint.capabilities.includes(operation) ? '' : '（未声明该能力，仍可临时指定）'}
                  </option>
                ))}
              </select>
              {capableEndpoints.length === 0 && (
                <p className="mt-1 text-[10px] text-warn">
                  没有端点声明「{operations.find((item) => item.key === operation)?.label ?? operation}」能力；不选就只会回落占位图。
                </p>
              )}
            </label>

            <label className="block">
              <span className="block font-mono text-[9px] text-ink-subtle uppercase tracking-wider mb-1">补充要求 · 会拼进提示词</span>
              <input
                data-testid="image-process-prompt"
                value={prompt}
                maxLength={300}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="例：保留商品边缘，背景换成纯白"
                className="w-full h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink outline-none focus:border-flare/60"
              />
            </label>

            {error && (
              <p className="flex items-start gap-1.5 rounded-lg border border-bad/30 bg-bad/10 px-2.5 py-2 text-[10px] text-bad">
                <AlertCircle size={11} className="mt-0.5 flex-shrink-0" /> {error}
              </p>
            )}

            <button
              type="button"
              data-testid="image-process-submit"
              disabled={busy}
              onClick={() => void submit()}
              className="w-full h-9 inline-flex items-center justify-center gap-2 rounded-lg bg-flare text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-50"
            >
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              {busy ? '处理中…' : '开始处理，结果写回素材库'}
            </button>

            {job && (
              <div data-testid="image-process-status" className="rounded-xl border border-line bg-panel-2/30 px-3 py-2.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={cn(
                    'rounded-pill border px-2 py-0.5 text-[10px]',
                    job.status === 'done' ? 'border-ok/30 bg-ok/10 text-ok'
                      : job.status === 'failed' ? 'border-bad/30 bg-bad/10 text-bad'
                        : 'border-iris/30 bg-iris/10 text-iris',
                  )}>
                    {job.status === 'done' && <Check size={9} className="inline mr-1" />}
                    {STATUS_TEXT[job.status] ?? job.status}
                  </span>
                  <span className="font-mono text-[10px] text-ink">{job.job_no}</span>
                  <span className="font-mono text-[9px] text-ink-subtle">
                    {operations.find((item) => item.key === job.operation)?.label ?? job.operation}
                    {job.endpoint_key ? ` · 指定 ${nameOf(job.endpoint_key)}` : ' · 自动分派'}
                  </span>
                </div>
                {TERMINAL.has(job.status) && (
                  <p className="mt-1.5 flex items-start gap-1.5 font-mono text-[9px] text-ink-subtle">
                    <Route size={10} className="mt-0.5 flex-shrink-0" />
                    {job.status === 'done'
                      ? `实际命中 ${job.used_endpoint ? nameOf(job.used_endpoint) : '内置占位图'} · ${job.engine ?? 'mock'}${job.latency_ms ? ` · ${job.latency_ms}ms` : ''} · 结果已入库`
                      : job.error || '处理失败'}
                  </p>
                )}
              </div>
            )}

            {jobs.length > 0 && (
              <div>
                <p className="font-mono text-[9px] text-ink-subtle uppercase tracking-wider mb-1">这张图的处理记录</p>
                <div className="space-y-1 max-h-28 overflow-y-auto">
                  {jobs.map((item) => (
                    <div key={item.id} className="flex items-center gap-2 rounded-lg border border-line/60 px-2 py-1 text-[10px]">
                      <span className="font-mono text-ink-subtle">{item.job_no}</span>
                      <span className="text-ink-muted truncate">{operations.find((o) => o.key === item.operation)?.label ?? item.operation}</span>
                      <span className="ml-auto font-mono text-[9px] text-ink-subtle">{STATUS_TEXT[item.status] ?? item.status}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
