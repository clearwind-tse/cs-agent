// -*- coding: utf-8 -*-
/**
 * StudioWorkbench — 「04 AI 创作」工作区容器
 *
 * IA 原则：这些功能是**并列的出图目标**，不是要依次走完的步骤。
 * 所以切换条按「创作工作台 / 出图能力 / 后期编排 / 素材底座 / 图像端点」五组排，
 * 跨功能不设上一步 / 下一步；真正的步骤只存在于单次任务内部，由任务工作台展示。
 *
 * 落地顺序是刻意「先结构、后能力」：素材库、两阶段任务链路、图像端点网关都是真实接口。
 * 成图是否真出图取决于端点池里有没有配可用端点：没有就回落占位图，页头如实标注，
 * 不让使用者把占位图当成模型产出；画布仍只列能力契约。
 */
import { useEffect, useState } from 'react'
import { ArrowRight, Check, Info, Wand2 } from 'lucide-react'
import { cn } from '../utils'
import { STUDIO_GROUPS, STUDIO_ITEMS } from '../navigation'
import type { StudioPane } from '../appRoutes'
import { STUDIO_ROADMAP, STUDIO_SPEC_BY_PANE } from '../studioSpec'
import StudioAssets from './StudioAssets'
import StudioEndpoints from './StudioEndpoints'
import StudioPaneView from './StudioPaneView'
import StudioTaskRunner from './StudioTaskRunner'
import { getStudioEngine, type StudioEngineInfo, type StudioTaskKind } from '../api'

interface StudioWorkbenchProps {
  pane: StudioPane
  onPaneChange: (pane: StudioPane) => void
}

/** 这五个功能共用「规划 → 确认 → 执行」框架，但各自的输入表单与规划内容完全不同 */
const TASK_PANES: readonly StudioTaskKind[] = ['set', 'style', 'sku', 'outfit', 'retouch']
const isTaskPane = (pane: StudioPane): pane is StudioTaskKind =>
  TASK_PANES.includes(pane as StudioTaskKind)

/** 页头状态标：四种状态都写实话 —— 已接后端 / 网关已就位 / 占位图兜底 / 纯契约页 */
function StudioSkeletonNotice({
  tone,
  endpointCount,
  className,
}: {
  tone: 'ok' | 'endpoints' | 'gateway' | 'mock' | 'skeleton'
  endpointCount?: number
  className?: string
}) {
  if (tone === 'endpoints') {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-pill border border-ok/30 bg-ok/10 px-2.5 py-1 text-[10px] text-ok',
          className,
        )}
        title="端点池、绑定链与图像网关都已接后端；是否真出图取决于有没有配可用端点"
      >
        <Check size={11} /> 已接后端 · 图像网关
      </span>
    )
  }
  if (tone === 'gateway') {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-pill border border-ok/30 bg-ok/10 px-2.5 py-1 text-[10px] text-ok',
          className,
        )}
        title="出图走图像端点网关：按镜头能力分派到绑定的端点，失败自动试下一个，全失败才回落占位图"
      >
        <Check size={11} /> 网关已就位 · {endpointCount ?? 0} 个端点
      </span>
    )
  }
  if (tone === 'ok') {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-pill border border-ok/30 bg-ok/10 px-2.5 py-1 text-[10px] text-ok',
          className,
        )}
        title="该页已接后端：文件落本地磁盘，接口与表均已就绪"
      >
        <Check size={11} /> 已接后端 · 本地磁盘
      </span>
    )
  }
  if (tone === 'mock') {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-pill border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] text-warn',
          className,
        )}
        title="任务链路已接通，但端点池里还没有可用真实端点，成图回落占位图"
      >
        <Info size={11} /> 链路已通 · 占位图兜底
      </span>
    )
  }
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-pill border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] text-warn',
        className,
      )}
      title="页面结构已接通，图像生成能力尚未实现"
    >
      <Info size={11} /> 契约页 · 未接模型
    </span>
  )
}

export default function StudioWorkbench({ pane, onPaneChange }: StudioWorkbenchProps) {
  const activeItem = STUDIO_ITEMS.find((item) => item.pane === pane) ?? STUDIO_ITEMS[0]
  const ActiveIcon = activeItem?.icon ?? Wand2
  const activeGroup = STUDIO_GROUPS.find((group) => group.id === activeItem.group)

  // 端点池是运行时数据：从端点页切回来要重新读一次，页头才不会一直说「还在用占位图」
  const [engine, setEngine] = useState<StudioEngineInfo | null>(null)
  useEffect(() => {
    void getStudioEngine().then(setEngine).catch(() => setEngine(null))
  }, [pane])

  const noticeTone: 'ok' | 'endpoints' | 'gateway' | 'mock' | 'skeleton' =
    pane === 'endpoints'
      ? 'endpoints'
      : pane === 'assets'
        ? 'ok'
        : pane === 'canvas'
          ? 'skeleton'
          : engine && !engine.is_mock
            ? 'gateway'
            : 'mock'

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-panel">
      {/* 页头：显示「组 / 功能」两级身份，而不是把一个功能写成链路第几步 */}
      <header className="h-14 px-5 flex items-center justify-between border-b border-line flex-shrink-0 gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-flare/15 text-flare flex items-center justify-center flex-shrink-0">
            <ActiveIcon size={16} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-ink leading-tight truncate">
              {activeGroup?.label ?? 'AI 创作'}
              <span className="text-ink-subtle font-normal"> / {activeItem?.label}</span>
            </h2>
            <p className="text-[11px] text-ink-subtle truncate">{activeItem?.desc}</p>
          </div>
        </div>
        <StudioSkeletonNotice
          tone={noticeTone}
          endpointCount={engine?.endpoint_count}
          className="flex-shrink-0 hidden sm:inline-flex"
        />
      </header>

      {/* 功能切换条：五组并列，组间用分隔线断开，不暗示先后顺序 */}
      <div className="flex-shrink-0 border-b border-line/60 bg-panel-2/25 px-3 py-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex items-center min-w-max">
          {STUDIO_GROUPS.map((group, groupIndex) => (
            <div key={group.id} className="flex items-center gap-1">
              {groupIndex > 0 && <span className="mx-2 h-4 w-px bg-line/70 flex-shrink-0" aria-hidden="true" />}
              <span
                title={group.hint}
                className="px-1 font-mono text-[9px] tracking-wide text-ink-subtle whitespace-nowrap flex-shrink-0"
              >
                {group.label}
              </span>
              {STUDIO_ITEMS.filter((entry) => entry.group === group.id).map((item) => {
                const Icon = item.icon
                const active = item.id === activeItem?.id
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => item.pane && onPaneChange(item.pane)}
                    aria-current={active ? 'page' : undefined}
                    title={item.desc}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1.5 text-[12px] transition-colors border whitespace-nowrap',
                      active
                        ? 'border-flare/40 bg-flare/15 text-ink'
                        : 'border-transparent text-ink-muted hover:text-ink hover:bg-panel-2/60',
                    )}
                  >
                    <Icon size={13} className={active ? 'text-flare' : 'text-ink-subtle'} />
                    {item.label}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {pane === 'home' ? (
          <StudioHome onPaneChange={onPaneChange} />
        ) : pane === 'assets' ? (
          <StudioAssets />
        ) : isTaskPane(pane) ? (
          <StudioTaskRunner key={pane} kind={pane} onOpenEndpoints={() => onPaneChange('endpoints')} />
        ) : pane === 'canvas' ? (
          <StudioPaneView pane="canvas" onPaneChange={onPaneChange} />
        ) : pane === 'endpoints' ? (
          <StudioEndpoints />
        ) : null}
      </div>
    </div>
  )
}

/** 首页：一个「挑目标」的入口，不重复罗列开发者视角的路线图 */
function StudioHome({ onPaneChange }: { onPaneChange: (pane: StudioPane) => void }) {
  const generateItems = STUDIO_ITEMS.filter((item) => item.group === 'generate')
  const supportItems = STUDIO_ITEMS.filter((item) => item.group === 'post' || item.group === 'base')
  const endpointItems = STUDIO_ITEMS.filter((item) => item.group === 'endpoints')

  const card = (item: (typeof STUDIO_ITEMS)[number], compact = false) => {
    const Icon = item.icon
    const spec = item.pane && item.pane !== 'home' ? STUDIO_SPEC_BY_PANE[item.pane] : null
    const missing = spec ? spec.capabilities.filter((cap) => cap.state === 'todo').length : 0
    const readyCount = spec ? spec.capabilities.filter((cap) => cap.state === 'ready').length : 0
    return (
      <button
        key={item.id}
        type="button"
        onClick={() => item.pane && onPaneChange(item.pane)}
        className={cn(
          'group text-left rounded-card border border-line/70 bg-panel/60 hover:border-flare/40 hover:bg-panel-2/50 transition-colors',
          compact ? 'p-3.5 flex items-center gap-3' : 'p-4',
        )}
      >
        <div
          className={cn(
            'rounded-lg bg-panel-2/70 text-ink-muted group-hover:bg-flare/15 group-hover:text-flare flex items-center justify-center transition-colors flex-shrink-0',
            compact ? 'w-9 h-9' : 'w-8 h-8',
          )}
        >
          <Icon size={15} />
        </div>
        <div className={cn('min-w-0', compact ? 'flex-1' : 'mt-2.5')}>
          <div className="flex items-center gap-2">
            <p className="text-[13px] font-medium text-ink">{item.label}</p>
            {spec && (
              <span className="ml-auto font-mono text-[10px] text-ink-subtle flex-shrink-0">
                <span className={missing > 0 ? 'text-warn' : 'text-ok'}>缺 {missing}</span>
                {readyCount > 0 && <span className="text-ok"> · 备 {readyCount}</span>}
              </span>
            )}
          </div>
          <p className="text-[11px] leading-relaxed text-ink-subtle mt-1">{item.desc}</p>
          {!compact && item.steps && (
            <p className="font-mono text-[9px] text-ink-subtle mt-2 truncate">{item.steps.join(' → ')}</p>
          )}
          <span className="inline-flex items-center gap-1 text-[10px] text-ink-subtle group-hover:text-flare mt-2 transition-colors">
            {readyCount > 0 ? '打开工作台' : '看接口契约'} <ArrowRight size={10} />
          </span>
        </div>
      </button>
    )
  }

  return (
    <div className="px-5 py-5 space-y-5">
      <section className="rounded-card border border-line/70 bg-panel-2/35 px-4 py-3 flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-flare/15 text-flare flex items-center justify-center flex-shrink-0">
          <Wand2 size={17} />
        </div>
        <div className="min-w-0">
          <p className="text-[12px] font-medium text-ink">挑一个出图目标开始</p>
          <p className="text-[11px] leading-relaxed text-ink-subtle mt-1">
            下面五个功能是并列的出图目标，按这次要做什么挑一个即可，不用依次走完；
            素材库是所有功能共用的输入与产出底座，图像端点决定这些功能实际用谁出图。
          </p>
          <p className="text-[11px] leading-relaxed text-warn mt-1.5">
            当前进度：素材库、两阶段任务链路、图像端点网关均已接后端；规划仍是规则引擎。
            端点池里没有可用真实端点时成图回落占位图，配好端点后自动按镜头能力动态分派。
          </p>
        </div>
      </section>

      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-[12px] font-medium text-ink">出图能力</h3>
          <span className="font-mono text-[10px] text-ink-subtle">5 个并列目标 · 按需选一个</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{generateItems.map((item) => card(item))}</div>
      </section>

      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-[12px] font-medium text-ink">后期编排与素材底座</h3>
          <span className="font-mono text-[10px] text-ink-subtle">所有功能共用</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">{supportItems.map((item) => card(item, true))}</div>
      </section>

      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-[12px] font-medium text-ink">图像端点</h3>
          <span className="font-mono text-[10px] text-ink-subtle">配端点 · 绑服务 · 运行时按能力选</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">{endpointItems.map((item) => card(item, true))}</div>
      </section>

      {/* 建设顺序是给维护者看的，默认收起，不再挤占用户工作台首屏 */}
      <details className="rounded-card border border-line/70 bg-panel-2/25">
        <summary className="cursor-pointer list-none px-4 py-2.5 flex items-center gap-2 text-[11px] text-ink-muted hover:text-ink transition-colors">
          <span className="font-mono text-[10px] text-ink-subtle">开发者视图</span>
          建设顺序与能力替换点
          <span className="ml-auto font-mono text-[10px] text-ink-subtle">先底座，后模型</span>
        </summary>
        <div className="border-t border-line/60 divide-y divide-line/60">
          {STUDIO_ROADMAP.map((entry) => (
            <div key={entry.phase} className="flex items-start gap-3 px-4 py-2.5">
              <span
                className={cn(
                  'font-mono text-[10px] rounded-md px-1.5 py-0.5 flex-shrink-0 mt-0.5 border inline-flex items-center gap-1',
                  entry.done ? 'text-ok bg-ok/10 border-ok/30' : 'text-flare bg-flare/10 border-flare/25',
                )}
              >
                {entry.done && <Check size={9} />}
                {entry.phase}
              </span>
              <div className="min-w-0 flex-1">
                <p className={cn('text-[12px]', entry.done ? 'text-ink-muted' : 'text-ink')}>{entry.title}</p>
                <p className="text-[11px] text-ink-subtle leading-relaxed mt-0.5">{entry.detail}</p>
              </div>
              <span className="font-mono text-[10px] text-ink-subtle flex-shrink-0 mt-1">依赖 {entry.depends}</span>
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}
