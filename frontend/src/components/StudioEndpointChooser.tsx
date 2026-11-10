// -*- coding: utf-8 -*-
/**
 * StudioEndpointChooser — 出图任务里的「运行时端点选择」控件
 *
 * 与「设置 → 模型信息」的区别：这里不是给服务永久改配置，而是**本次任务**用哪个端点。
 * 选中项只是被提前到候选链的链首，服务绑定的 fallback 链一个都不砍（后端 resolve_chain）。
 * 所以界面必须同时展示当前绑定链，让用户知道「选了 A，A 挂了还会试 B / C」。
 */
import { ChevronDown, Cpu, ExternalLink, Route } from 'lucide-react'
import { cn } from '../utils'
import type { ImageEndpointsResponse } from '../api'

interface StudioEndpointChooserProps {
  data: ImageEndpointsResponse | null
  /** 当前出图功能的 key，用来读它的绑定链 */
  service: string
  value: string
  onChange: (key: string) => void
  disabled?: boolean
  paramsText: string
  onParamsTextChange: (text: string) => void
  paramsOpen: boolean
  onToggleParams: () => void
  onOpenEndpoints?: () => void
  /** 规划页里用紧凑版：不重复长说明 */
  compact?: boolean
}

const PROTOCOL_SHORT: Record<string, string> = {
  webhook: '通用 HTTP',
  openai_images: 'OpenAI 图像',
  volc_ark: '火山方舟',
}

export default function StudioEndpointChooser({
  data,
  service,
  value,
  onChange,
  disabled,
  paramsText,
  onParamsTextChange,
  paramsOpen,
  onToggleParams,
  onOpenEndpoints,
  compact = false,
}: StudioEndpointChooserProps) {
  const realEndpoints = (data?.endpoints ?? []).filter(
    (endpoint) => endpoint.protocol !== 'mock' && endpoint.enabled,
  )
  const nameOf = (key: string) => data?.endpoints.find((endpoint) => endpoint.key === key)?.name ?? key

  const boundKeys: string[] = []
  for (const binding of [...(data?.bindings ?? [])]
    .filter((item) => item.service === service && item.enabled)
    .sort((a, b) => a.priority - b.priority)) {
    if (!boundKeys.includes(binding.endpoint_key)) boundKeys.push(binding.endpoint_key)
  }

  return (
    <section
      data-testid="task-endpoint-chooser"
      className={cn(
        'rounded-xl border border-iris/25 bg-iris/[0.045] px-3 py-2.5',
        compact && 'border-line/70 bg-panel-2/30',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Cpu size={13} className="text-iris" />
        <h4 className="text-[12px] font-medium text-ink">本次出图端点</h4>
        <span className="font-mono text-[9px] text-ink-subtle">运行时选择 · 不改服务绑定</span>
        {onOpenEndpoints && (
          <button
            type="button"
            data-testid="task-endpoint-goto"
            onClick={onOpenEndpoints}
            className="ml-auto inline-flex items-center gap-1 text-[10px] text-ink-subtle hover:text-flare transition-colors"
          >
            管理端点池 <ExternalLink size={10} />
          </button>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select
          data-testid="task-endpoint-select"
          aria-label="本次出图使用的端点"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-[220px] flex-1 h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink outline-none focus:border-flare/60 disabled:opacity-60"
        >
          <option value="auto">auto · 按服务绑定链自动分派</option>
          {realEndpoints.map((endpoint) => (
            <option key={endpoint.key} value={endpoint.key}>
              {endpoint.name}（{PROTOCOL_SHORT[endpoint.protocol] ?? endpoint.protocol}）
              {boundKeys.includes(endpoint.key) ? ' · 已绑定' : ' · 临时指定'}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="task-endpoint-params-toggle"
          onClick={onToggleParams}
          className="inline-flex items-center gap-1 h-8 rounded-lg border border-line px-2.5 text-[10px] text-ink-muted hover:text-ink transition-colors"
        >
          <ChevronDown size={10} className={cn('transition-transform', paramsOpen && 'rotate-180')} />
          额外参数
          {paramsText.trim() && <span className="w-1.5 h-1.5 rounded-full bg-flare" />}
        </button>
      </div>

      {!compact && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-ink-subtle">
          端点池里可配任意多个端点；这里选中的只是把本次任务提前到它，失败仍按下面这条链自动 fallback，
          全链失败才回落内置占位图。
        </p>
      )}

      <div data-testid="task-endpoint-chain" className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 font-mono text-[9px] text-ink-subtle">
          <Route size={10} /> 绑定链
        </span>
        {boundKeys.length === 0 ? (
          <span className="rounded-md border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[9px] text-warn">
            本功能未绑定真实端点
          </span>
        ) : (
          boundKeys.map((key, index) => (
            <span
              key={key}
              className={cn(
                'rounded-md border px-1.5 py-0.5 text-[9px]',
                value === key ? 'border-flare/50 bg-flare/10 text-flare' : 'border-line bg-panel/60 text-ink-muted',
              )}
              title={key}
            >
              <span className="font-mono opacity-70">{index + 1}</span> {nameOf(key)}
            </span>
          ))
        )}
        <span className="rounded-md border border-line bg-panel-2/60 px-1.5 py-0.5 text-[9px] text-ink-subtle">
          兜底 · 内置占位图
        </span>
      </div>

      {paramsOpen && (
        <label className="block mt-2">
          <span className="block font-mono text-[9px] text-ink-subtle mb-1">
            端点额外参数（JSON，与端点默认参数合并，本次优先；例：size / strength / seed）
          </span>
          <textarea
            data-testid="task-endpoint-params"
            value={paramsText}
            onChange={(event) => onParamsTextChange(event.target.value)}
            placeholder={'{\n  "strength": 0.7,\n  "seed": 42\n}'}
            className="w-full h-20 rounded-lg border border-line bg-panel px-2.5 py-2 font-mono text-[10px] text-ink outline-none focus:border-flare/60"
          />
        </label>
      )}
    </section>
  )
}
