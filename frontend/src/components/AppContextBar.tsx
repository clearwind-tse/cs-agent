// -*- coding: utf-8 -*-
/**
 * AppContextBar — 全站统一上下文条
 *
 * 原来每个视图各自用一个「X」表达层级，等价于把「会话记录」当隐式首页，
 * 跨链路（工单 → 会话 → 质检 → 训练）没有任何可走的路径。
 * 这一条把「我在哪个工作区 / 业务链路的第几步 / 下一步去哪 / 关联入口」固定下来：
 * - 面包屑来自 navigation.ts 的 IA 真源；
 * - 上一步 / 下一步只给主链路节点，支撑能力不伪造步骤；
 * - 关联入口是跨链路跳转，不是重复当前页。
 *
 * 视觉约束：沿用 panel / line / ink / iris 语义色与 mono 字号体系，高度为一条紧凑的 36px。
 */
import { ArrowLeft, ArrowRight, ChevronRight } from 'lucide-react'
import { cn } from '../utils'
import {
  getBreadcrumb,
  getFlowPosition,
  getNavItem,
  getRelatedItems,
  getStudioGroup,
  getWorkspace,
  type NavItem,
} from '../navigation'
import type { AgentPane, StudioPane, ViewMode } from '../appRoutes'

interface AppContextBarProps {
  view: ViewMode
  pane?: AgentPane | StudioPane | null
  onNavigate: (item: NavItem) => void
}

export default function AppContextBar({ view, pane, onNavigate }: AppContextBarProps) {
  const item = getNavItem(view, pane)
  const workspace = getWorkspace(view, pane)
  const crumbs = getBreadcrumb(view, pane)
  const flow = getFlowPosition(item.id)
  // 关联入口不与「上一步 / 下一步」重复，否则同一目标会在一条里出现两次
  const related = getRelatedItems(item.id)
    .filter((entry) => entry.id !== flow?.prev?.id && entry.id !== flow?.next?.id)
    .slice(0, 2)
  const isGlobalTool = view === 'ai' || view === 'search' || view === 'overview' || view === 'settings'
  /**
   * 不在主链路上的页面，给身份说明而不是留空。
   * AI 创作的九个功能按五组并列，不属于任何线性链路，所以显示「功能组 · 当前功能」；
   * 不能显示「出图链路 2/9」那种伪造的前后步骤。
   */
  const studioGroup = getStudioGroup(item.id)
  const fallbackLabel = isGlobalTool
    ? '全局入口'
    : studioGroup
      ? `${studioGroup.label} · ${item.label}`
      : '支撑能力'

  return (
    <div className="flex-shrink-0 h-9 px-4 flex items-center gap-3 border-b border-line/60 bg-panel/40 backdrop-blur-md z-10">
      {/* 当前位置 */}
      <nav aria-label="当前位置" className="flex items-center gap-1.5 min-w-0">
        <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', isGlobalTool ? 'bg-ink-subtle' : workspace.dotCls)} />
        {crumbs.map((crumb, index) => (
          <span key={`${crumb.label}-${index}`} className="flex items-center gap-1.5 min-w-0">
            {index > 0 && <ChevronRight size={11} className="text-ink-subtle flex-shrink-0" />}
            <span className={cn('text-[11px] truncate', crumb.muted ? 'font-mono text-ink-subtle' : 'text-ink font-medium')}>
              {crumb.label}
            </span>
          </span>
        ))}
      </nav>

      <div className="flex-1" />

      {/* 链路位置与前后步骤 */}
      {flow ? (
        <div className="hidden md:flex items-center gap-1.5 flex-shrink-0">
          <span className="font-mono text-[10px] text-ink-subtle">
            {flow.flowLabel} {flow.index + 1}/{flow.total}
          </span>
          {flow.prev && (
            <button
              type="button"
              onClick={() => onNavigate(flow.prev!)}
              title={`上一步：${flow.prev.label}`}
              className="flex items-center gap-1 rounded-pill border border-line/70 px-2 py-0.5 text-[10px] text-ink-muted hover:text-ink hover:border-line-strong transition-colors"
            >
              <ArrowLeft size={11} /> {flow.prev.label}
            </button>
          )}
          {flow.next && (
            <button
              type="button"
              onClick={() => onNavigate(flow.next!)}
              title={`下一步：${flow.next.label}`}
              className="flex items-center gap-1 rounded-pill border border-iris/35 bg-iris/10 px-2 py-0.5 text-[10px] text-ink hover:border-iris/60 transition-colors"
            >
              {flow.next.label} <ArrowRight size={11} />
            </button>
          )}
        </div>
      ) : (
        <span className="hidden md:inline font-mono text-[10px] text-ink-subtle flex-shrink-0">
          {fallbackLabel}
        </span>
      )}

      {/* 跨链路关联入口 */}
      {related.length > 0 && (
        <div className="hidden lg:flex items-center gap-1.5 pl-3 ml-1 border-l border-line/70 flex-shrink-0">
          <span className="text-[10px] text-ink-subtle">关联</span>
          {related.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => onNavigate(entry)}
              title={entry.desc}
              className="text-[10px] text-ink-muted hover:text-ink underline-offset-2 hover:underline transition-colors"
            >
              {entry.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
