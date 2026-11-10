// -*- coding: utf-8 -*-
/**
 * PrimarySidebar — 主导航（按业务链路分组）
 *
 * 交互重设计：
 * - 原来 9 个一级入口平铺，在线服务 / 离线数据混在一起，只能靠图标猜位置。
 * - 现在窄条只放「4 个工作区 + 当前工作区的功能 + 全局工具」；完整功能分布、
 *   业务链路步骤、跨链路入口都在可展开的玻璃导航面板里。
 * - 面板聚焦哪个工作区与当前页面所在工作区是两件事：点工作区按钮只展开菜单，
 *   不偷偷换页；真正跳转必须点具体功能，避免误触丢失当前上下文。
 * - 面板底部可设置「跳转后自动折叠」，偏好写入 localStorage：
 *   开启 = 点功能即收起；关闭 = 面板常驻，宽屏下切换为停靠布局（推右内容而非遮挡）。
 *   ESC / 点遮罩 / 关闭按钮是显式操作，始终能收起面板。
 *
 * 视觉约束：沿用 tokens.css / glass / iris / line 等既有类名，不新增配色与字体。
 */
import {
  ChevronRight,
  LogOut,
  MessageCircle,
  Moon,
  Sun,
  User,
  X,
} from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { cn } from '../utils'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import {
  FLOWS,
  GLOBAL_TOOLS,
  NAV_ITEM_BY_ID,
  OVERVIEW_ITEM,
  WORKSPACES,
  getNavItem,
  getStudioGroup,
  getWorkspace,
  type NavItem,
  type WorkspaceId,
} from '../navigation'
import type { AgentPane, StudioPane } from '../appRoutes'
import { getBrowserStorage, readAutoCollapse, writeAutoCollapse } from '../navigationPref'

interface PrimarySidebarProps {
  currentView: string
  currentPane?: AgentPane | StudioPane | null
  onOpenChat: () => void
  onOpenSearch: () => void
  onOpenAI: () => void
  onOpenAdmin?: () => void
  onOpenCustom?: () => void
  onOpenExtractor?: () => void
  onOpenQuiz?: () => void
  onOpenAgent?: () => void
  onOpenTraining?: () => void
  onLoginClick?: () => void
  /** 按 IA 真源里的精确路径跳转（含 /agent/* 子页） */
  onNavigate?: (path: string) => void
}

export default function PrimarySidebar(props: PrimarySidebarProps) {
  const { user, isAuthenticated, logout } = useAuth()
  const { resolvedTheme, toggleTheme } = useTheme()
  const reduceMotion = useReducedMotion()
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [focusedWorkspace, setFocusedWorkspace] = useState<WorkspaceId | null>(null)
  const [autoCollapse, setAutoCollapse] = useState(() => readAutoCollapse(getBrowserStorage()))
  const [isWide, setIsWide] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(min-width: 1024px)').matches
      : false,
  )

  const view = props.currentView as Parameters<typeof getNavItem>[0]
  const isOverview = view === 'overview'
  const OverviewIcon = OVERVIEW_ITEM.icon
  const activeItem = getNavItem(view, props.currentPane)
  const activeWorkspace = getWorkspace(view, props.currentPane)
  /** 全局入口（工作台 / 看板 / 全局工具）不归属任何工作区，面板默认停在第一条链路 */
  const isGlobalEntry = view === 'overview' || view === 'ai' || view === 'search'
  const panelDefaultWorkspaceId = isGlobalEntry ? WORKSPACES[0].id : activeWorkspace.id
  const panelWorkspace = WORKSPACES.find((w) => w.id === (focusedWorkspace ?? panelDefaultWorkspaceId)) ?? activeWorkspace
  /** 常驻面板只在宽屏停靠；窄屏保持浮层，避免把内容区挤没 */
  const docked = expanded && !autoCollapse && isWide
  /**
   * 窄条高度预算只够 5 个功能入口（与 02 数据治理的实际占用对齐）。
   * AI 创作有 8 个功能，多出的走展开面板与页内切换条，避免把底部全局工具挤出屏幕。
   */
  const railItems = isOverview
    ? WORKSPACES.map((workspace) => workspace.items[0])
    : activeWorkspace.items.slice(0, 5)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(min-width: 1024px)')
    const onChange = (event: MediaQueryListEvent) => setIsWide(event.matches)
    setIsWide(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!expanded) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [expanded])

  const toggleAutoCollapse = () => {
    setAutoCollapse((current) => {
      const next = !current
      writeAutoCollapse(next, getBrowserStorage())
      return next
    })
  }

  /** 统一跳转出口：精确路径优先，保留旧回调以兼容既有调用方 */
  const selectItem = (item: NavItem) => {
    // 关闭自动折叠后面板保持展开，方便连续切换功能；显式关闭依然随时可用
    if (autoCollapse) setExpanded(false)
    const isGlobalTool = item.view === 'ai' || item.view === 'search' || item.view === 'overview' || item.view === 'settings'
    setFocusedWorkspace(isGlobalTool ? activeWorkspace.id : getWorkspace(item.view, item.pane).id)

    if (item.view === 'chat') {
      props.onOpenChat()
      return
    }
    if (props.onNavigate) {
      props.onNavigate(item.path)
      return
    }
    const legacy: Partial<Record<NavItem['view'], () => void>> = {
      search: props.onOpenSearch,
      ai: props.onOpenAI,
      admin: props.onOpenAdmin,
      custom: props.onOpenCustom,
      extractor: props.onOpenExtractor,
      quiz: props.onOpenQuiz,
      agent: props.onOpenAgent,
      training: props.onOpenTraining,
    }
    legacy[item.view]?.()
  }

  const openWorkspaceMenu = (id: WorkspaceId) => {
    setFocusedWorkspace(id)
    setExpanded(true)
  }

  const NavButton = ({
    icon: Icon,
    label,
    active,
    onClick,
    tone,
  }: {
    icon: NavItem['icon']
    label: string
    active: boolean
    onClick?: () => void
    tone?: string
  }) => (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative w-10 h-10 md:w-12 md:h-12 flex items-center justify-center rounded-xl transition-all group flex-shrink-0',
        active ? (tone ?? 'bg-iris/20 text-iris') : 'text-ink-muted hover:bg-panel-2/50 hover:text-ink',
      )}
      title={label}
    >
      {active && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-iris rounded-r-md" />}
      <Icon size={22} strokeWidth={active ? 2.5 : 2} />
    </button>
  )

  return (
    <>
      <nav className="w-16 md:w-20 h-full flex-shrink-0 bg-panel-2/70 border-r border-line flex flex-col items-center py-5 gap-4 z-20 backdrop-blur-xl relative">
        {/* Logo */}
        <div
          className="w-10 h-10 md:w-12 md:h-12 rounded-2xl flex items-center justify-center shadow-glow flex-shrink-0"
          style={{ background: 'conic-gradient(from 210deg, rgb(var(--c-mint)), rgb(var(--c-iris)), rgb(var(--c-flare)), rgb(var(--c-mint)))' }}
        >
          <div className="w-[calc(100%-6px)] h-[calc(100%-6px)] rounded-xl bg-canvas/85 backdrop-blur-md flex items-center justify-center">
            <MessageCircle size={20} className="text-ink" strokeWidth={1.8} />
          </div>
        </div>

        {/* 功能地图：完整 IA 与业务链路 */}
        <button
          type="button"
          onClick={() => {
            setFocusedWorkspace(isGlobalEntry ? WORKSPACES[0].id : activeWorkspace.id)
            setExpanded((value) => !value)
          }}
          aria-expanded={expanded}
          aria-label={expanded ? '收起功能地图' : '展开功能地图'}
          title={expanded ? '收起功能地图' : '展开功能地图'}
          className={cn(
            'w-10 h-10 md:w-12 md:h-12 rounded-xl flex items-center justify-center transition-colors flex-shrink-0',
            expanded ? 'bg-iris/20 text-iris' : 'text-ink-subtle hover:bg-panel-2/60 hover:text-ink',
          )}
        >
          {expanded ? <X size={20} /> : <ChevronRight size={20} />}
        </button>

        {/* 全局总览：待办 + 统计，跨三条链路，不归属任何工作区 */}
        <NavButton
          icon={OVERVIEW_ITEM.icon}
          label={OVERVIEW_ITEM.label}
          active={isOverview}
          onClick={() => selectItem(OVERVIEW_ITEM)}
        />

        <div className="w-8 h-px bg-line/70 flex-shrink-0" />

        {/* 工作区切换：只展开对应菜单，不直接换页 */}
        <div className="flex flex-col items-center gap-2 w-full flex-shrink-0">
          {WORKSPACES.map((workspace) => {
            const active = !isOverview && workspace.id === activeWorkspace.id
            const Icon = workspace.icon
            return (
              <NavButton
                key={workspace.id}
                icon={Icon}
                label={`${workspace.index} ${workspace.label} · ${workspace.desc}`}
                active={active}
                tone={workspace.activeCls}
                onClick={() => openWorkspaceMenu(workspace.id)}
              />
            )
          })}
        </div>

        <div className="w-8 h-px bg-line/70 flex-shrink-0" />

        {/**
          * 功能入口区：自己吃掉剩余高度并允许滚动。
          * 原来这里是 flex-shrink-0 + 一个 flex-1 占位，窗口不够高时（900px 常见笔记本）
          * 底部全局工具与账户会被挤出视口——900px 下实测溢出 67px，AI 创作 8 个功能更多。
          * 改成可滚动后，工具区永远可见，功能多时只滚功能本身。
          * 滚动条隐藏：80px 宽的窄条放条形滚动条会把图标挤歪，滚动仍可用（滚轮 / 触控板）。
          */}
        <div className="flex-1 min-h-0 w-full overflow-y-auto overflow-x-hidden flex flex-col items-center gap-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {railItems.map((item) => (
            <NavButton
              key={item.id}
              icon={item.icon}
              label={item.label}
              active={item.id === activeItem.id}
              onClick={() => selectItem(item)}
            />
          ))}
        </div>

        {/* 全局工具 + 主题 + 账户 */}
        <div className="flex flex-col items-center gap-2 w-full pb-2 flex-shrink-0">
          <div className="w-8 h-px bg-line/70 mb-1" />
          {GLOBAL_TOOLS.map((item) => (
            <NavButton
              key={item.id}
              icon={item.icon}
              label={item.label}
              active={item.id === activeItem.id}
              onClick={() => selectItem(item)}
            />
          ))}

          <button
            type="button"
            onClick={toggleTheme}
            aria-label={resolvedTheme === 'dark' ? '切换到亮色主题' : '切换到暗色主题'}
            title={resolvedTheme === 'dark' ? '切换到亮色主题' : '切换到暗色主题'}
            className="w-10 h-10 md:w-12 md:h-12 flex items-center justify-center rounded-xl text-ink-subtle hover:bg-panel-2/60 hover:text-ink transition-colors"
          >
            {resolvedTheme === 'dark' ? <Sun size={19} strokeWidth={1.8} /> : <Moon size={19} strokeWidth={1.8} />}
          </button>

          <div className="relative mt-1">
            {isAuthenticated ? (
              <>
                <button
                  type="button"
                  onClick={() => setShowProfileMenu(!showProfileMenu)}
                  className="w-12 h-12 flex flex-col items-center justify-center rounded-xl hover:bg-panel-2/50 transition-colors"
                  title={user?.nickname || undefined}
                  aria-label="账户菜单"
                >
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-mint to-mint flex items-center justify-center">
                    <span className="text-ink text-xs font-bold">
                      {(user?.nickname || user?.username || 'U').charAt(0).toUpperCase()}
                    </span>
                  </div>
                </button>

                {showProfileMenu && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setShowProfileMenu(false)} />
                    <div className="absolute left-full ml-4 bottom-0 w-48 bg-panel border border-line rounded-xl shadow-xl overflow-hidden animate-fade-in z-50">
                      <div className="px-4 py-3 border-b border-panel-2">
                        <p className="text-sm font-medium text-ink max-w-[160px] truncate">{user?.nickname}</p>
                        <p className="text-xs text-ink-subtle max-w-[160px] truncate">@{user?.username}</p>
                        <p className="text-[10px] mt-1 text-iris uppercase tracking-wider">{user?.role}</p>
                      </div>
                      <div className="p-1">
                        <button
                          type="button"
                          onClick={() => {
                            logout()
                            setShowProfileMenu(false)
                          }}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-bad hover:text-bad hover:bg-panel-2 rounded-lg transition-colors"
                        >
                          <LogOut size={16} /> 退出登录
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </>
            ) : (
              <button
                type="button"
                onClick={props.onLoginClick}
                className="w-12 h-12 flex items-center justify-center rounded-xl bg-panel text-ink-muted hover:text-iris hover:bg-panel-2 transition-all border border-line/50 hover:border-iris/20"
                title="登录"
                aria-label="登录"
              >
                <User size={20} />
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* 浮层模式才有遮罩；停靠模式面板占位，不挡内容 */}
      {expanded && !docked && (
        <div className="fixed inset-0 z-40" onClick={() => setExpanded(false)} aria-hidden="true" />
      )}

      {/* 展开式功能地图：自动折叠开启为浮层，关闭且宽屏时为停靠面板 */}
      <AnimatePresence>
        {expanded && (
          <motion.aside
            key="nav-panel"
            role="dialog"
            aria-label="功能地图"
            data-docked={docked ? 'true' : 'false'}
            initial={{ opacity: 0, x: -14 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -14 }}
            transition={{ duration: reduceMotion ? 0 : 0.22, ease: 'easeOut' }}
            className={cn(
              'z-50 glass border-r border-line flex flex-col shadow-glass',
              docked
                ? 'relative h-full w-[300px] xl:w-[340px] flex-shrink-0'
                : 'fixed left-16 md:left-20 top-0 bottom-0 w-[min(340px,calc(100vw-4rem))]',
            )}
          >
              <header className="px-5 pt-5 pb-4 border-b border-line/70 flex-shrink-0">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-ink-subtle">Navigation Map</p>
                    <h2 className="font-display text-lg font-bold text-ink mt-1">功能地图</h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setExpanded(false)}
                    className="p-2 rounded-lg hover:bg-panel-2/60 text-ink-muted hover:text-ink transition-colors"
                    aria-label="关闭功能地图"
                  >
                    <X size={17} />
                  </button>
                </div>
                <p className="text-[11px] leading-relaxed text-ink-subtle mt-2">
                  按业务链路分组，点击工作区只看菜单，点击功能才跳转。
                </p>
              </header>

              <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
                {/* 全局总览：待办 + 统计 */}
                <button
                  type="button"
                  onClick={() => selectItem(OVERVIEW_ITEM)}
                  aria-current={isOverview ? 'page' : undefined}
                  className={cn(
                    'w-full mb-5 flex items-start gap-3 rounded-xl border p-3 text-left transition-colors',
                    isOverview ? 'border-iris/40 bg-iris/15' : 'border-line/70 bg-panel-2/40 hover:bg-panel-2/70',
                  )}
                >
                  <span className="w-8 h-8 rounded-lg bg-iris/15 text-iris flex items-center justify-center flex-shrink-0">
                    <OverviewIcon size={16} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-ink">{OVERVIEW_ITEM.label}</span>
                    <span className="block text-[10px] text-ink-subtle leading-relaxed">{OVERVIEW_ITEM.desc}</span>
                  </span>
                  <ChevronRight size={14} className="text-ink-subtle mt-2 flex-shrink-0" />
                </button>

                {/* 业务链路总览 */}
                <section className="mb-5">
                  <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle mb-2 px-1">业务链路</p>
                  {(Object.keys(FLOWS) as Array<keyof typeof FLOWS>).map((flowId) => {
                    const flow = FLOWS[flowId]
                    return (
                      <div key={flowId} className="mb-3 rounded-xl border border-line/70 bg-panel-2/40 p-3">
                        <p className="text-[11px] text-ink-muted mb-2">{flow.label}</p>
                        <div className="flex flex-wrap items-center gap-1">
                          {flow.itemIds.map((id, index) => {
                            const item = NAV_ITEM_BY_ID[id]
                            return (
                              <span key={id} className="flex items-center gap-1">
                                {index > 0 && <ChevronRight size={11} className="text-ink-subtle" />}
                                <button
                                  type="button"
                                  onClick={() => selectItem(item)}
                                  className={cn(
                                    'rounded-pill border px-2 py-1 text-[10px] transition-colors',
                                    item.id === activeItem.id
                                      ? 'border-iris/40 bg-iris/15 text-ink'
                                      : 'border-line/70 bg-panel/50 text-ink-muted hover:text-ink hover:border-line-strong',
                                  )}
                                >
                                  {item.label}
                                </button>
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </section>

                {/* 三个工作区：默认展开当前聚焦的那一组 */}
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle mb-2 px-1">工作区</p>
                {WORKSPACES.map((workspace) => {
                  const focused = workspace.id === panelWorkspace.id
                  const Icon = workspace.icon
                  return (
                    <section key={workspace.id} className="mb-2">
                      <button
                        type="button"
                        onClick={() => setFocusedWorkspace(workspace.id)}
                        className={cn(
                          'w-full flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors',
                          focused ? 'bg-panel-2/70' : 'hover:bg-panel-2/40',
                        )}
                      >
                        <span className={cn('w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0', focused ? workspace.activeCls : 'bg-panel-2/60 text-ink-subtle')}>
                          <Icon size={15} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="font-mono text-[10px] text-ink-subtle">{workspace.index}</span>
                            <span className="text-sm font-medium text-ink">{workspace.label}</span>
                          </span>
                          <span className="block text-[10px] text-ink-subtle truncate">{workspace.desc}</span>
                        </span>
                        <ChevronRight size={14} className={cn('text-ink-subtle transition-transform', focused && 'rotate-90')} />
                      </button>

                      {focused && (
                        <div className="mt-1 mb-3 pl-2 border-l border-line/70 ml-5">
                          {workspace.items.map((item) => {
                            const active = item.id === activeItem.id
                            const ItemIcon = item.icon
                            // AI 创作的并列目标按组分段，别在功能地图里排成一条假流水线
                            const group = workspace.id === 'studio' ? getStudioGroup(item.id) : undefined
                            const firstInGroup = Boolean(group && group.itemIds[0] === item.id)
                            return (
                              <Fragment key={item.id}>
                                {group && firstInGroup && (
                                  <p className="px-2.5 pt-2.5 pb-1 font-mono text-[9px] tracking-wide text-ink-subtle">
                                    {group.label}
                                  </p>
                                )}
                                <button
                                  type="button"
                                  onClick={() => selectItem(item)}
                                  aria-current={active ? 'page' : undefined}
                                  className={cn(
                                    'w-full flex items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors',
                                    active ? 'bg-iris/15' : 'hover:bg-panel-2/50',
                                  )}
                                >
                                  <ItemIcon size={15} className={cn('mt-0.5 flex-shrink-0', active ? 'text-iris' : 'text-ink-subtle')} />
                                  <span className="min-w-0 flex-1">
                                    <span className={cn('block text-[13px]', active ? 'text-ink font-medium' : 'text-ink-muted')}>{item.label}</span>
                                    <span className="block text-[10px] text-ink-subtle leading-relaxed">{item.desc}</span>
                                    {item.steps && (
                                      <span className="block font-mono text-[9px] text-ink-subtle mt-1 truncate">
                                        {item.steps.join(' → ')}
                                      </span>
                                    )}
                                  </span>
                                </button>
                              </Fragment>
                            )
                          })}
                        </div>
                      )}
                    </section>
                  )
                })}

                {/* 全局工具 */}
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle mb-2 mt-5 px-1">全局工具</p>
                <div className="space-y-1">
                  {GLOBAL_TOOLS.map((item) => {
                    const ItemIcon = item.icon
                    const active = item.id === activeItem.id
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => selectItem(item)}
                        className={cn(
                          'w-full flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors',
                          active ? 'bg-iris/15 text-ink' : 'text-ink-muted hover:bg-panel-2/50 hover:text-ink',
                        )}
                      >
                        <ItemIcon size={15} className="flex-shrink-0" />
                        <span className="text-[13px]">{item.label}</span>
                        <span className="ml-auto text-[10px] text-ink-subtle truncate max-w-[130px]">{item.desc}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              <footer className="px-4 py-3 border-t border-line/70 flex-shrink-0">
                <button
                  type="button"
                  role="switch"
                  aria-checked={autoCollapse}
                  onClick={toggleAutoCollapse}
                  className="w-full flex items-center justify-between gap-3 rounded-xl px-2.5 py-2 text-left hover:bg-panel-2/50 transition-colors"
                >
                  <span className="min-w-0">
                    <span className="block text-[12px] text-ink">跳转后自动折叠</span>
                    <span className="block text-[10px] text-ink-subtle leading-relaxed">
                      {autoCollapse
                        ? '点功能即收起，不占用内容宽度'
                        : isWide ? '面板常驻并停靠在左侧' : '面板常驻，窄屏需手动关闭'}
                    </span>
                  </span>
                  <span className={cn(
                    'relative w-9 h-5 rounded-pill border flex-shrink-0 transition-colors',
                    autoCollapse ? 'bg-brand/80 border-brand' : 'bg-panel-2/80 border-line-strong',
                  )}>
                    <span className={cn(
                      'absolute top-[3px] w-3.5 h-3.5 rounded-full transition-all',
                      autoCollapse ? 'left-[18px] bg-brand-fg' : 'left-[3px] bg-ink-subtle',
                    )} />
                  </span>
                </button>
                <p className="font-mono text-[10px] text-ink-subtle truncate mt-1 px-2.5">
                  当前 · {isGlobalEntry ? '全局' : `${activeWorkspace.index} ${activeWorkspace.label}`} /{' '}
                  {activeItem.label}
                </p>
              </footer>
            </motion.aside>
        )}
      </AnimatePresence>
    </>
  )
}
