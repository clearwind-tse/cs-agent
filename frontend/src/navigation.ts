/**
 * navigation.ts — 交互信息架构（IA）唯一真源
 *
 * 背景：原来 9 个一级入口平铺在一条图标导航里，在线服务链路与离线数据链路混排，
 * 各视图又各自用「X 返回聊天」表达层级，用户看不出自己在业务闭环的哪一步。
 *
 * 这里把功能分布按业务链路收成四个工作区，导航条、展开面板、上下文条共用同一份定义：
 *   01 在线服务 RUN   —— 对话 → 工具 → 建单 → 人审
 *   02 数据治理 DATA  —— 聊天记录 → 清洗审核 → 质检 → 知识
 *   03 模型优化 TRAIN —— SFT / DPO → 数据集 → 考核
 *   04 AI 创作 STUDIO —— 商品套图 → 风格复刻 → SKU 替换 → 组图 → 精修 → 画布
 *
 * 04 与前三者不同：它不服务客服链路，而是复刻商品图生产（picsetai 那一类）的能力。
 * 之所以仍然收进同一份 IA，是因为导航/面包屑/上下文条只认这一份真源——
 * 另起一套导航会让「我在哪、怎么回去」两个问题出现两种答案。
 *
 * 约束：只定义「去哪 / 属于哪条链路 / 前后是谁」，不定义外观。
 * URL 契约仍由 appRoutes.ts 持有，本文件不新增路由，只复用已存在的路径。
 */
import {
  Bot,
  Brush,
  ClipboardList,
  Cpu,
  Database,
  Edit3,
  FolderOpen,
  Frame,
  Gauge,
  GraduationCap,
  Layers,
  LayoutDashboard,
  LayoutTemplate,
  LifeBuoy,
  Lightbulb,
  MessageCircle,
  MessageSquare,
  Palette,
  RefreshCw,
  Search,
  Settings2,
  Shirt,
  Sparkles,
  Tag,
  Wand2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { buildAgentPath, buildStudioPath, buildViewPath, type AgentPane, type StudioPane, type ViewMode } from './appRoutes'

export type WorkspaceId = 'run' | 'data' | 'train' | 'studio'
/** 只有客服体系的两条链路是真正的「前后步骤」；AI 创作的九个功能按五组并列，不是流水线 */
export type FlowId = 'online' | 'data'

/** AI 创作内部的功能分组：同组才是同一类操作，跨组没有前后关系 */
export type StudioGroupId = 'workbench' | 'generate' | 'post' | 'base' | 'endpoints'

export interface StudioGroup {
  id: StudioGroupId
  label: string
  hint: string
  itemIds: string[]
}

export const STUDIO_GROUPS: StudioGroup[] = [
  { id: 'workbench', label: '创作工作台', hint: '挑出图目标 · 回看任务', itemIds: ['studio-home'] },
  {
    id: 'generate',
    label: '出图能力',
    hint: '五个并列目标，按需求挑一个',
    itemIds: ['studio-set', 'studio-style', 'studio-sku', 'studio-outfit', 'studio-retouch'],
  },
  { id: 'post', label: '后期编排', hint: '把成图排成详情页', itemIds: ['studio-canvas'] },
  { id: 'base', label: '素材底座', hint: '所有功能的输入与产出', itemIds: ['studio-assets'] },
  { id: 'endpoints', label: '图像端点', hint: '配端点 · 绑服务 · 按能力动态分派', itemIds: ['studio-endpoints'] },
]

export interface NavItem {
  id: string
  label: string
  desc: string
  path: string
  view: ViewMode
  /** 视图内部子页：Agent 工作台用 AgentPane，AI 创作工作区用 StudioPane */
  pane?: AgentPane | StudioPane
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
  /* AI 创作与模型优化共用 flare：两者不会同时高亮，窄条上不产生歧义 */
  studio: 'bg-flare/15 text-flare',
}

/**
 * AI 创作的子页。
 *
 * 单独收窄成 StudioNavItem：NavItem.pane 是 AgentPane | StudioPane 的并集，
 * 直接拿去索引 StudioPane 的映射会丢类型，调用方每次都要断言一次——不如在这里收一次。
 */
export interface StudioNavItem extends NavItem {
  view: 'studio'
  pane: StudioPane
  group: StudioGroupId
}

export function getStudioGroup(itemId: string): StudioGroup | undefined {
  return STUDIO_GROUPS.find((group) => group.itemIds.includes(itemId))
}

export const STUDIO_ITEMS: StudioNavItem[] = [
  {
    id: 'studio-home',
    label: '创作首页',
    desc: '按出图目标挑功能 · 任务记录 · 建设顺序',
    path: buildStudioPath('home'),
    view: 'studio',
    pane: 'home',
    group: 'workbench',
    icon: LayoutTemplate,
    steps: ['选功能', '传素材', '出图'],
  },
  {
    id: 'studio-set',
    label: '商品套图',
    desc: '上传商品图 + 参考风格，批量生成主图 / 详情图',
    path: buildStudioPath('set'),
    view: 'studio',
    pane: 'set',
    group: 'generate',
    icon: Layers,
    steps: ['商品图', '风格参考', '两阶段生成', '批量出图'],
  },
  {
    id: 'studio-style',
    label: '风格复刻',
    desc: '从参考图提取风格画像，复用到新品',
    path: buildStudioPath('style'),
    view: 'studio',
    pane: 'style',
    group: 'generate',
    icon: Palette,
    steps: ['风格提取', '风格画像', '应用复刻'],
  },
  {
    id: 'studio-sku',
    label: 'SKU 替换',
    desc: '保留版式与光影，只替换商品本体',
    path: buildStudioPath('sku'),
    view: 'studio',
    pane: 'sku',
    group: 'generate',
    icon: RefreshCw,
    steps: ['选底图', '抠主体', '换品', '校准光影'],
  },
  {
    id: 'studio-outfit',
    label: '服装组图',
    desc: '上衣 / 下装自由搭配，生成成套组图',
    path: buildStudioPath('outfit'),
    view: 'studio',
    pane: 'outfit',
    group: 'generate',
    icon: Shirt,
    steps: ['选版型', '配上下装', '成套出图'],
  },
  {
    id: 'studio-retouch',
    label: '精修',
    desc: '去瑕疵 / 换背景 / 提清晰度，单图修到可用',
    path: buildStudioPath('retouch'),
    view: 'studio',
    pane: 'retouch',
    group: 'generate',
    icon: Brush,
    steps: ['上传原图', '选修复项', '对比保存'],
  },
  {
    id: 'studio-canvas',
    label: '画布编排',
    desc: '把多张成图排成详情页长图与尺寸变体',
    path: buildStudioPath('canvas'),
    view: 'studio',
    pane: 'canvas',
    group: 'post',
    icon: Frame,
    steps: ['拉入图片', '排版', '导出多尺寸'],
  },
  {
    id: 'studio-assets',
    label: '素材库',
    desc: '商品 / 风格 / 成图的统一沉淀与复用',
    path: buildStudioPath('assets'),
    view: 'studio',
    pane: 'assets',
    group: 'base',
    icon: FolderOpen,
    steps: ['归集', '打标', '复用'],
  },
  {
    id: 'studio-endpoints',
    label: '端点池',
    desc: '端点池、服务绑定与图片处理能力分派',
    path: buildStudioPath('endpoints'),
    view: 'studio',
    pane: 'endpoints',
    group: 'endpoints',
    icon: Cpu,
    steps: ['注册端点', '绑定服务', '运行时选择'],
  },
]

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
  {
    id: 'studio',
    index: '04',
    label: 'AI 创作',
    desc: '商品套图 → 风格复刻 → SKU 替换 → 服装组图 → 精修 → 画布',
    icon: Wand2,
    activeCls: WORKSPACE_ACTIVE_CLS.studio,
    dotCls: 'bg-flare',
    defaultItemId: 'studio-home',
    items: STUDIO_ITEMS,
  },
]

/**
 * 全局总览：一个入口，两个视角。
 *
 *   - 待办：今天先做哪件（待处理工单 / 待审对话 / 未达线质检，取真实条目）
 *   - 统计：数据有多少（跨链路 KPI、闭环健康度、图表、下钻）
 *
 * 两者都属于「全局」，不属于任何单一工作区，因此不占用业务链路的步骤；
 * 用同一页的 Tab 承载，避免一进站就要在「工作台」和「看板」之间猜哪个更该先点。
 */
export const OVERVIEW_ITEM: NavItem = {
  id: 'overview',
  label: '全局总览',
  desc: '待办队列与跨链路统计：先看要做哪件，再看数据有多少',
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
  {
    id: 'model-settings',
    label: '设置',
    desc: '按业务板块选择模型；API Key 与端点仍在 .env 配置',
    path: buildViewPath('settings'),
    view: 'settings',
    icon: Settings2,
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
  // 这里刻意没有 studio：AI 创作的九个功能是「按目标二选一」的并列入口，
  // 不是要依次走完的步骤。真正的步骤在单次任务内部（配置 → 规划 → 确认 → 执行 → 入库），
  // 由任务工作台自己展示，不能挂到全站上下文条上伪装成跨功能流水线。
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
  // 出图功能之间不互指「下一个」：它们是并列目标，不是流水线。
  // 关联只给底座（素材库）和入口（创作首页），让「我在做商品套图」这件事不被打断。
  'studio-home': ['studio-assets', 'studio-canvas', 'studio-endpoints'],
  'studio-set': ['studio-assets'],
  'studio-style': ['studio-assets'],
  'studio-sku': ['studio-assets'],
  'studio-outfit': ['studio-assets'],
  'studio-retouch': ['studio-assets'],
  'studio-canvas': ['studio-assets'],
  'studio-assets': ['studio-home', 'studio-endpoints'],
  // 端点页是「配置入口」，不是出图流水线的下一步；只关联底座与首页，不给它接上一步/下一步
  'studio-endpoints': ['studio-assets', 'studio-home'],
}

export function getNavItem(
  view: ViewMode,
  pane?: AgentPane | StudioPane | null,
): NavItem {
  if (view === 'overview') return OVERVIEW_ITEM
  if (view === 'agent') {
    return NAV_ITEM_BY_ID[`agent-${pane ?? 'chat'}`] ?? NAV_ITEM_BY_ID['agent-chat']
  }
  if (view === 'studio') {
    return NAV_ITEM_BY_ID[`studio-${pane ?? 'home'}`] ?? NAV_ITEM_BY_ID['studio-home']
  }
  if (view === 'ai') return NAV_ITEM_BY_ID['ai-assistant']
  if (view === 'search') return NAV_ITEM_BY_ID['global-search']
  if (view === 'settings') return NAV_ITEM_BY_ID['model-settings']
  return (
    WORKSPACES.flatMap((w) => w.items).find((item) => item.view === view) ??
    NAV_ITEM_BY_ID['chat-record']
  )
}

export function getWorkspace(
  view: ViewMode,
  pane?: AgentPane | StudioPane | null,
): Workspace {
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

export function getBreadcrumb(
  view: ViewMode,
  pane?: AgentPane | StudioPane | null,
): Crumb[] {
  const workspace = getWorkspace(view, pane)
  const item = getNavItem(view, pane)

  // 总览与全局工具挂在「全局」而不是某个工作区下
  if (view === 'overview') {
    return [{ label: '全局总览', muted: true }, { label: item.label }]
  }
  if (view === 'ai' || view === 'search' || view === 'settings') {
    return [{ label: '全局工具', muted: true }, { label: item.label }]
  }

  return [
    { label: `${workspace.index} / ${workspace.label}`, muted: true },
    { label: item.label },
  ]
}
