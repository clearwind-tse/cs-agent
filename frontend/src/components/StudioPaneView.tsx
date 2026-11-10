// -*- coding: utf-8 -*-
/**
 * StudioPaneView — AI 创作里尚未落真实实现的「接口契约 / 骨架」页
 *
 * 现在只有「后期编排 canvas」还在用这个渲染器；五个出图功能、素材库、端点池
 * 都已有各自真实页面，由 StudioWorkbench 直接分发，不再套骨架。
 * 骨架页统一回答同一组问题：输入什么 → 输出什么 → 分几步 → 缺哪些能力 → 与复刻目标的差异。
 *
 * 刻意不做的事：
 * - 不放假的上传框、假的「生成中」进度条 —— 这块后端还没接真实能力，
 *   摆一个能点但没反应的按钮，比写一行「待建设」更误导；
 * - 不把「所需能力」写成一句话概括 —— 缺哪块要能直接当工单用。
 */
import { ArrowRight, Boxes, CornerDownRight, Cpu, FileOutput, FileInput, GitBranch } from 'lucide-react'
import { cn } from '../utils'
import type { StudioPane } from '../appRoutes'
import { STUDIO_ITEMS } from '../navigation'
import { CAPABILITY_STATE_META, STUDIO_SPEC_BY_PANE } from '../studioSpec'

interface StudioPaneViewProps {
  pane: Exclude<StudioPane, 'home'>
  onPaneChange: (pane: StudioPane) => void
}

export default function StudioPaneView({ pane, onPaneChange }: StudioPaneViewProps) {
  const spec = STUDIO_SPEC_BY_PANE[pane]
  const item = STUDIO_ITEMS.find((entry) => entry.pane === pane)
  const currentIndex = STUDIO_ITEMS.findIndex((entry) => entry.pane === pane)
  const nextItem = STUDIO_ITEMS[currentIndex + 1]

  const counts = {
    ready: spec.capabilities.filter((cap) => cap.state === 'ready').length,
    reuse: spec.capabilities.filter((cap) => cap.state === 'reuse').length,
    todo: spec.capabilities.filter((cap) => cap.state === 'todo').length,
  }

  return (
    <div className="px-5 py-5 space-y-5">
      {/* 目标：一句话说清这个功能换到什么 */}
      <div className="rounded-card border border-line/70 bg-panel-2/35 px-4 py-3 flex items-start gap-3">
        <CornerDownRight size={15} className="text-flare flex-shrink-0 mt-0.5" />
        <p className="text-[12px] leading-relaxed text-ink-muted">{spec.goal}</p>
      </div>

      {/* 输入 / 输出 / 步骤：三列并排，骨架期它就是规格书 */}
      <div className="grid gap-3 lg:grid-cols-2">
        <SpecList
          icon={FileInput}
          title="输入"
          hint="用户要提供什么"
          items={spec.inputs}
          tone="text-info"
        />
        <SpecList
          icon={FileOutput}
          title="输出"
          hint="交付给用户什么"
          items={spec.outputs}
          tone="text-ok"
        />
      </div>

      <section className="rounded-card border border-line/70 bg-panel/50 p-4">
        <div className="flex items-center gap-2 mb-3">
          <GitBranch size={14} className="text-iris" />
          <h3 className="text-[12px] font-medium text-ink">处理步骤</h3>
          <span className="font-mono text-[10px] text-ink-subtle">{spec.steps.length} 步</span>
        </div>
        <ol className="space-y-2.5">
          {spec.steps.map((step, index) => (
            <li key={step.title} className="flex items-start gap-3">
              <span className="font-mono text-[10px] text-ink-subtle w-5 flex-shrink-0 mt-0.5 text-right">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className="relative flex-shrink-0 mt-1">
                <span className="block w-1.5 h-1.5 rounded-full bg-iris/70" />
                {index < spec.steps.length - 1 && (
                  <span className="absolute left-1/2 top-2 -translate-x-1/2 w-px h-[calc(100%+0.6rem)] bg-line/80" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] text-ink leading-tight">{step.title}</span>
                <span className="block text-[11px] text-ink-subtle leading-relaxed mt-0.5">{step.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      {/* 能力缺口：这块是骨架期最该被读的部分 */}
      <section className="rounded-card border border-line/70 bg-panel/50 p-4">
        <div className="flex items-center gap-2 mb-1">
          <Cpu size={14} className="text-warn" />
          <h3 className="text-[12px] font-medium text-ink">所需能力</h3>
          <span className="ml-auto flex items-center gap-2 font-mono text-[10px]">
            <span className="text-ok">已具备 {counts.ready}</span>
            <span className="text-warn">可复用 {counts.reuse}</span>
            <span className="text-bad">待建设 {counts.todo}</span>
          </span>
        </div>
        <p className="text-[10px] text-ink-subtle mb-3 leading-relaxed">
          后端现状：素材库（上传 / 本地存储 / 去重）已具备；图像生成与视觉模型尚未接入，
          标「待建设」的就是本功能的实际缺口。
        </p>
        <div className="space-y-1.5">
          {spec.capabilities.map((cap) => {
            const meta = CAPABILITY_STATE_META[cap.state]
            return (
              <div
                key={cap.label}
                className="flex items-start gap-2.5 rounded-xl border border-line/60 bg-panel-2/30 px-3 py-2"
              >
                <span className={cn('mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0', meta.dot)} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[12px] text-ink">{cap.label}</span>
                    <span className={cn('rounded-pill border px-1.5 py-0.5 text-[9px]', meta.cls)}>{meta.label}</span>
                  </div>
                  <p className="text-[11px] text-ink-subtle leading-relaxed mt-0.5">{cap.detail}</p>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 复刻对照：留着这条，实现时不用回头翻方案文档 */}
      {spec.reference && spec.reference.length > 0 && (
        <section className="rounded-card border border-line/70 bg-panel-2/25 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Boxes size={14} className="text-ink-subtle" />
            <h3 className="text-[12px] font-medium text-ink-muted">复刻要点</h3>
            <span className="font-mono text-[10px] text-ink-subtle">来自 picsetai 逆向</span>
          </div>
          <ul className="space-y-1.5">
            {spec.reference.map((line) => (
              <li key={line} className="flex items-start gap-2 text-[11px] leading-relaxed text-ink-subtle">
                <span className="text-flare/70 flex-shrink-0">·</span>
                {line}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 链路下一站：骨架期也要能顺着走完，不然每一步都要回导航 */}
      {nextItem && (
        <div className="flex items-center justify-between rounded-card border border-line/60 bg-panel-2/20 px-4 py-3">
          <span className="text-[11px] text-ink-subtle">
            链路上一步之后：<span className="text-ink-muted">{nextItem.label}</span>
          </span>
          <button
            type="button"
            onClick={() => nextItem.pane && onPaneChange(nextItem.pane)}
            className="inline-flex items-center gap-1.5 rounded-pill border border-flare/35 bg-flare/10 px-3 py-1 text-[11px] text-ink hover:border-flare/60 transition-colors"
          >
            {nextItem.label} <ArrowRight size={11} />
          </button>
        </div>
      )}

      {item?.steps && (
        <p className="font-mono text-[10px] text-ink-subtle pb-2">{item.steps.join(' → ')}</p>
      )}
    </div>
  )
}

function SpecList({
  icon: Icon,
  title,
  hint,
  items,
  tone,
}: {
  icon: typeof FileInput
  title: string
  hint: string
  items: string[]
  tone: string
}) {
  return (
    <section className="rounded-card border border-line/70 bg-panel/50 p-4">
      <div className="flex items-center gap-2 mb-1">
        <Icon size={14} className={tone} />
        <h3 className="text-[12px] font-medium text-ink">{title}</h3>
        <span className="font-mono text-[10px] text-ink-subtle ml-auto">{items.length} 项</span>
      </div>
      <p className="text-[10px] text-ink-subtle mb-2.5">{hint}</p>
      <ul className="space-y-1.5">
        {items.map((entry) => (
          <li key={entry} className="flex items-start gap-2 text-[12px] leading-relaxed text-ink-muted">
            <span className="mt-1.5 w-1 h-1 rounded-full bg-line-strong flex-shrink-0" />
            {entry}
          </li>
        ))}
      </ul>
    </section>
  )
}
