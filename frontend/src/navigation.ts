/**
 * navigation.ts — 交互信息架构（IA）唯一真源
 *
 * 背景：原来 9 个一级入口平铺在一条图标导航里，在线服务链路与离线数据链路混排，
 * 各视图又各自用「X 返回聊天」表达层级，用户看不出自己在业务闭环的哪一步。
 *
 * 这里把功能分布按业务链路收成三个工作区，导航条、展开面板、上下文条共用同一份定义：
 *   01 在线服务 RUN   —— 对话 → 工具 → 建单 → 人审
 *   02 数据治理 DATA  —— 聊天记录 → 清洗审核 → 质检 → 知识
 *   03 模型优化 TRAIN —— SFT / DPO → 数据集 → 考核
 *
 * 约束：只定义「去哪 / 属于哪条链路 / 前后是谁」，不定义外观。
 * URL 契约仍由 appRoutes.ts 持有，本文件不新增路由，只复用已存在的路径。
 */
import {
  Bot,
  ClipboardList,
  Database,
  Edit3,
  Gauge,
  GraduationCap,
  LayoutDashboard,
  LifeBuoy,
  Lightbulb,
  MessageCircle,
  MessageSquare,
  Search,
  Sparkles,
  Tag,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { buildAgentPath, buildViewPath, type AgentPane, type ViewMode } from './appRoutes'

export type WorkspaceId = 'run' | 'data' | 'train'
export type FlowId = 'online' | 'data'

export interface NavItem {
  id: string
  label: string
  desc: string
  path: string
  view: ViewMode
  pane?: AgentPane
  icon: LucideIcon
  /** 视图内部的业务步骤，仅用于导航面板说明，不产生额外路由 */
  steps?: string[]
}

export interface Workspace {
  id: WorkspaceId
  index: string
  label: string
  desc: string
  icon: LucideIcon
  /** 静态类名：Tailwind 不做动态拼接 */
  activeCls: string
  dotCls: string
  defaultItemId: string
  items: NavItem[]
}

export const WORKSPACE_ACTIVE_CLS: Record<WorkspaceId, string> = {
  run: 'bg-ok/15 text-ok',
  data: 'bg-iris/20 text-info',
  train: 'bg-flare/15 text-flare',
}

export const WORKSPACES: Workspace[] = [
  {
    id: 'run',
    index: '01',
    label: '在线服务',
    desc: '客户对话 → 意图路由 → 工具调用 → 建单 → 人工审批',
    icon: Bot,
    activeCls: WORKSPACE_ACTIVE_CLS.run,
    dotCls: 'bg-mint',
    defaultItemId: 'agent-chat',
    items: [
      {
        id: 'agent-chat',
        label: '智能客服工作台',
        desc: '多轮对话 · 意图与情绪识别 · 工具调用',
        path: buildAgentPath('chat'),
        view: 'agent',
        pane: 'chat',
        icon: MessageSquare,
        steps: ['接收消息', '意图识别', '状态机推进', '工具调用'],
      },
      {
        id: 'agent-ticket',
        label: '工单与审批',
        desc: '自动建单 · 退款挂起 · 坐席批准 / 驳回',
        path: buildAgentPath('ticket'),
        view: 'agent',
        pane: 'ticket',
        icon: LifeBuoy,
        steps: ['建单', '挂起待审', '人工决策', '断点恢复'],
      },
      {
        id: 'agent-skill',
        label: '能力挂载',
        desc: 'Skill SOP 与外部 MCP 服务',
        path: buildAgentPath('skill'),
        view: 'agent',
        pane: 'skill',
        icon: Tag,
        steps: ['Skill 注册', 'MCP 接入', '健康检查'],
      },
      {
        id: 'agent-config',
        label: 'Agent 配置',
        desc: '子 Agent · 意图路由 · 提示词',
        path: buildAgentPath('config'),
        view: 'agent',
        pane: 'config',
        icon: Bot,
        steps: ['子 Agent', '路由规则', '提示词'],
      },
    ],
  },
  {
    id: 'data',
    index: '02',
    label: '数据治理',
    desc: '聊天记录 → 清洗审核 → 质检校准 → 知识提炼',
    icon: Database,
    activeCls: WORKSPACE_ACTIVE_CLS.data,
    dotCls: 'bg-iris',
    defaultItemId: 'chat-record',
    items: [
      {
        id: 'chat-record',
        label: '会话记录',
        desc: '原始聊天记录 · 会话检索与消息定位',
        path: buildViewPath('chat'),
        view: 'chat',
        icon: MessageCircle,
        steps: ['会话列表', '消息流', '定位跳转'],
      },
      {
        id: 'admin',
        label: '清洗与质检',
        desc: '会话清洗审核 · 质检评分 · 校准对比',
        path: buildViewPath('admin'),
        view: 'admin',
        icon: Gauge,
        steps: ['清洗审核', '质检评分', '校准对比'],
      },
      {
        id: 'extractor',
        label: '知识提炼',
        desc: '知识条目 · 向量切片 · RAG 检索源',
        path: buildViewPath('extractor'),
        view: 'extractor',
        icon: Lightbulb,
        steps: ['知识条目', '核验', '切片入库'],
      },
      {
        id: 'custom',
        label: '自定义数据',
        desc: '手工构造与维护对话样本',
        path: buildViewPath('custom'),
        view: 'custom',
        icon: Edit3,
        steps: ['新建对话', '编辑消息', '入库'],
      },
    ],
  },
  {
    id: 'train',
    index: '03',
    label: '模型优化',
    desc: '标注数据 → SFT / DPO → 数据集导出 → 考核验证',
    icon: GraduationCap,
    activeCls: WORKSPACE_ACTIVE_CLS.train,
    dotCls: 'bg-flare',
    defaultItemId: 'training',
    items: [
      {
        id: 'training',
        label: '训练数据管理',
        desc: 'SFT 样本 · DPO 偏好对 · 微调数据集导出',
        path: buildViewPath('training'),
        view: 'training',
        icon: GraduationCap,
        steps: ['SFT 提取', 'DPO 标注', '数据集导出'],
      },
      {
        id: 'quiz',
        label: 'AI 考核',
        desc: '考核题库 · 对话实训 · 成绩复盘',
        path: buildViewPath('quiz'),
        view: 'quiz',
        icon: ClipboardList,
        steps: ['生成考核', '答题 / 实训', '历史复盘'],
      },
    ],
  },
]

/**
 * 全局数据看板：跨三条业务链路的汇总视图，不属于任何单一工作区。
 * 用现有统计接口聚合，不新增后端端点；入口独立于工作区，避免把「总览」误读成某个阶段。
 */
export const OVERVIEW_ITEM: NavItem = {
  id: 'overview',
  label: '全局数据看板',
  desc: '在线服务 · 数据治理 · 模型优化的统计汇总',
  path: buildViewPath('overview'),
  view: 'overview',
  icon: LayoutDashboard,
  steps: ['采集统计', '按链路汇总', '下钻到模块'],
}

/** 全局工具：不归属任何工作区，固定在导航条底部 */
export const GLOBAL_TOOLS: NavItem[] = [
  {
    id: 'ai-assistant',
    label: 'RAG 智能问答',
    desc: '基于知识库的检索增强问答',
    path: buildViewPath('ai'),
    view: 'ai',
    icon: Sparkles,
  },
  {
    id: 'global-search',
    label: '全文搜索',
    desc: '跨会话检索并定位到具体消息',
    path: buildViewPath('search'),
    view: 'search',
    icon: Search,
  },
]

export const ALL_NAV_ITEMS: NavItem[] = [
  ...WORKSPACES.flatMap((w) => w.items),
  OVERVIEW_ITEM,
  ...GLOBAL_TOOLS,
]

export const NAV_ITEM_BY_ID: Record<string, NavItem> = Object.fromEntries(
  ALL_NAV_ITEMS.map((item) => [item.id, item]),
)

/**
 * 业务链路：只列主链路上的节点。
 * 支撑能力（能力挂载 / Agent 配置 / 自定义数据 / 全局工具）不占用链路步骤，
 * 在上下文条里以「支撑能力」呈现，避免出现假的「下一步」。
 */
export const FLOWS: Record<FlowId, { label: string; itemIds: string[] }> = {
  online: {
    label: '在线服务链路',
    itemIds: ['agent-chat', 'agent-ticket'],
  },
  data: {
    label: '离线数据闭环',
    itemIds: ['chat-record', 'admin', 'extractor', 'training', 'quiz'],
  },
}

/** 跨链路关联：当前功能最常被一起使用的入口，用于上下文条的快捷跳转 */
export const CROSS_LINKS: Record<string, string[]> = {
  'agent-chat': ['agent-ticket', 'chat-record'],
  'agent-ticket': ['chat-record', 'admin'],
  'agent-skill': ['agent-chat', 'agent-config'],
  'agent-config': ['agent-chat', 'agent-skill'],
  'chat-record': ['admin', 'agent-chat'],
  admin: ['extractor', 'training'],
  extractor: ['ai-assistant', 'training'],
  custom: ['admin', 'extractor'],
  training: ['quiz', 'admin'],
  quiz: ['training'],
  overview: ['agent-chat', 'admin', 'training'],
  'ai-assistant': ['chat-record', 'extractor'],
  'global-search': ['chat-record'],
}

export function getNavItem(view: ViewMode, pane?: AgentPane | null): NavItem {
  if (view === 'overview') return OVERVIEW_ITEM
  if (view === 'agent') {
    return NAV_ITEM_BY_ID[`agent-${pane ?? 'chat'}`] ?? NAV_ITEM_BY_ID['agent-chat']
  }
  if (view === 'ai') return NAV_ITEM_BY_ID['ai-assistant']
  if (view === 'search') return NAV_ITEM_BY_ID['global-search']
  return (
    WORKSPACES.flatMap((w) => w.items).find((item) => item.view === view) ??
    NAV_ITEM_BY_ID['chat-record']
  )
}

export function getWorkspace(view: ViewMode, pane?: AgentPane | null): Workspace {
  const item = getNavItem(view, pane)
  return WORKSPACES.find((w) => w.items.some((entry) => entry.id === item.id)) ?? WORKSPACES[1]
}

export interface FlowPosition {
  flowId: FlowId
  flowLabel: string
  index: number
  total: number
  prev?: NavItem
  next?: NavItem
}

export function getFlowPosition(itemId: string): FlowPosition | null {
  for (const flowId of Object.keys(FLOWS) as FlowId[]) {
    const flow = FLOWS[flowId]
    const index = flow.itemIds.indexOf(itemId)
    if (index === -1) continue
    return {
      flowId,
      flowLabel: flow.label,
      index,
      total: flow.itemIds.length,
      prev: index > 0 ? NAV_ITEM_BY_ID[flow.itemIds[index - 1]] : undefined,
      next: index < flow.itemIds.length - 1 ? NAV_ITEM_BY_ID[flow.itemIds[index + 1]] : undefined,
    }
  }
  return null
}

export function getRelatedItems(itemId: string): NavItem[] {
  return (CROSS_LINKS[itemId] ?? [])
    .map((id) => NAV_ITEM_BY_ID[id])
    .filter((item): item is NavItem => Boolean(item))
}

export interface Crumb {
  label: string
  muted?: boolean
}

export function getBreadcrumb(view: ViewMode, pane?: AgentPane | null): Crumb[] {
  const workspace = getWorkspace(view, pane)
  const item = getNavItem(view, pane)

  // 总览与全局工具挂在「全局」而不是某个工作区下
  if (view === 'overview') {
    return [{ label: '全局总览', muted: true }, { label: item.label }]
  }
  if (view === 'ai' || view === 'search') {
    return [{ label: '全局工具', muted: true }, { label: item.label }]
  }

  return [
    { label: `${workspace.index} / ${workspace.label}`, muted: true },
    { label: item.label },
  ]
}
