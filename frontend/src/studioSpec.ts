// -*- coding: utf-8 -*-
/**
 * studioSpec.ts — 「04 AI 创作」各功能的接口契约草稿
 *
 * 这一层刻意只描述「输入什么、输出什么、缺什么能力」，不写任何调用代码。
 * 目的：先让结构立住，让后续接模型的人一眼看出缺哪块，而不是先做一堆假界面。
 *
 * 能力状态只有三种，都必须如实标注：
 *   ready  —— 后端现有链路已具备
 *   reuse  —— 现有代码可复用一部分（须改造，不是开箱即用）
 *   todo   —— 完全没有，需要新建接口与存储
 *
 * 现状（2026-11）：
 * - 素材库已落本地磁盘（上传 / 列表 / 去重 / 删除 / 静态直出 / 一致性检查与清理）；
 *   目录是两级：一级五个 key 固定（显示名可在素材库里双击改名，存 media_kind_labels，可恢复默认），
 *   二级由 media_categories 表维护（预置 + 自建），素材只存二级 key，
 *   删目录只把素材移到「未归类」，不删文件；
 *   所有显示一级名的地方都读 GET /api/media/categories 的 group.label，不在组件里硬编码；
 * - 出图功能的每个素材角色都是紧凑卡片，点开「选图弹窗」再取图：左侧两级目录树、右侧大图网格、
 *   搜索与多选，确认后一次写回；弹窗另一个 Tab 可就地上传，传完自动进入待选并按
 *   studioKinds.ts 声明的默认目录归档。弹窗自行按目录/关键词查后端，不受「最近 100 张」限制；
 *   已选素材按 id 精确回查，旧任务里的老图也能显示缩略图；
 * - 两阶段任务链路已通：studio_tasks 表、逐图规划、人工确认闸门、后台执行、进度轮询、产出入库；
 * - 五个出图功能各有专属输入契约（studioKinds.ts）：素材角色与选项不同，后端按 kind 生成不同规划，
 *   不是同一个表单换标题；九个功能按五组并列排布（含端点池），跨功能没有「上一步 / 下一步」；
 * - 后台任务是进程内的，进程被 kill / reload 重启会留下僵尸任务：
 *   启动时全量回收 + 查询时 90 秒超时兜底，用户点「重跑」即可恢复；
 * - 出图已改为**图像端点网关驱动**：端点池（image_endpoints）可任意多个，服务绑定一条有序候选链
 *   （image_endpoint_bindings），镜头按能力标签动态分派，任务创建时还能临时指定端点、但不砍掉 fallback。
 *   全链路失败才回落 PIL 占位图；没配任何真实端点时整站仍然是 mock，页头会如实标注。
 *   所以端点体系本身标 ready，「真实图像模型已接入」不标 ready —— 取决于使用者有没有配端点。
 * - 素材库里可对单张图做「即席处理」：选动作 + 选端点，走同一个网关，结果回写素材库并记 image_process_jobs。
 * - 模型选择已统一到「设置 → 模型信息」：密钥在 .env，板块 → provider/模型 存 DB，
 *   后端所有调用点走 services/model_registry.py 的 resolve(slot)。
 *   注意这套是**文本模型**的板块选择器，与上面的**图像端点池**是两套机制，别混用。
 */
import type { StudioPane } from './appRoutes'

export type CapabilityState = 'ready' | 'reuse' | 'todo'

export interface StudioCapability {
  label: string
  detail: string
  state: CapabilityState
}

export interface StudioFlowStep {
  title: string
  detail: string
}

export interface StudioPaneSpec {
  pane: Exclude<StudioPane, 'home'>
  /** 本功能要解决的问题，一句话 */
  goal: string
  /** 输入物：用户要提供的 */
  inputs: string[]
  /** 输出物：交付给用户的 */
  outputs: string[]
  /** 处理步骤 */
  steps: StudioFlowStep[]
  /** 所需能力 */
  capabilities: StudioCapability[]
  /** 复刻目标的原始设计要点（来自 picsetai 逆向），留作实现时的对照 */
  reference?: string[]
}

export const CAPABILITY_STATE_META: Record<CapabilityState, { label: string; cls: string; dot: string }> = {
  ready: { label: '已具备', cls: 'text-ok border-ok/30 bg-ok/10', dot: 'bg-ok' },
  reuse: { label: '可复用', cls: 'text-warn border-warn/30 bg-warn/10', dot: 'bg-warn' },
  todo: { label: '待建设', cls: 'text-bad border-bad/30 bg-bad/10', dot: 'bg-bad' },
}

const RAW_SPECS: StudioPaneSpec[] = [
  {
    pane: 'set',
    goal: '一张商品图进去，一套主图 + 详情图出来，风格可控、可批量重跑。',
    inputs: ['商品图 1–5 张（白底 / 实拍）', '风格参考图（可选，1–3 张）', '卖点文案 / 类目 / 目标平台尺寸'],
    outputs: ['主图 ×N（尺寸按平台预设）', '详情图 ×N（按模块拼装）', '每张图的生成参数与提示词（可重跑）'],
    steps: [
      { title: '上传商品图', detail: '落对象存储，生成缩略图与主体掩码' },
      { title: '提取商品特征', detail: '类目、主体轮廓、颜色、材质、可卖点' },
      { title: '选风格', detail: '选参考图或选风格画像；无参考则用类目默认' },
      { title: '生成规划', detail: '文本模型产出「逐图规划」：构图、文案、尺寸、留白' },
      { title: '人工确认', detail: '两阶段的关键闸门：规划不对就不该白跑一次后台任务' },
      { title: '批量出图', detail: '按规划逐张生成，失败单张重试' },
      { title: '挑图入库', detail: '采用 / 丢弃，结果进素材库' },
    ],
    capabilities: [
      { label: '文本规划（LLM）', detail: '现有 app/services 文本链路可改造产出规划 JSON', state: 'reuse' },
      { label: '商品图上传与存储', detail: '已具备：POST /api/media/upload 落本地磁盘，素材库可直接取图', state: 'ready' },
      { label: '图像生成（文生图 / 图生图）', detail: '无任何 images/generations 适配，需接白标模型', state: 'todo' },
      { label: '主体提取 / 掩码', detail: '抠图能力缺失，套图与换背景都依赖它', state: 'todo' },
      { label: '单张失败重试', detail: '当前只能整单重跑，单张重试未做', state: 'todo' },
    ],
    reference: [
      '16 个详情模块 + 5 个主图模块由数据库配置驱动，不写死在代码里',
      '两阶段：先分析出规划，用户确认后才出图',
      '三种任务形态：单图 / 套图 / 换背景',
    ],
  },
  {
    pane: 'style',
    goal: '把某张参考图的「风格」抽成可复用的画像，换商品不换调性。',
    inputs: ['参考图 1–N 张', '目标商品图', '需要锁定的风格维度（色 / 光 / 构图 / 材质）'],
    outputs: ['风格画像（结构化 JSON + 可读描述）', '按画像生成的新图', '画像可保存为「风格资产」'],
    steps: [
      { title: '风格提取', detail: '视觉模型读图，输出色板、光线、构图、材质关键词' },
      { title: '画像结构化', detail: '转成可拼进提示词的槽位，避免每次重新描述' },
      { title: '应用复刻', detail: '画像 + 目标商品 → 生成；对照参考图评估相似度' },
    ],
    capabilities: [
      { label: '视觉理解（VLM）', detail: '需要读图输出结构化风格描述，当前无视觉链路', state: 'todo' },
      { label: '画像落库与版本', detail: '风格资产需要表与版本号，可复用现有模型基类习惯', state: 'todo' },
      { label: '画像转提示词', detail: '现有文本链路可承担拼装与改写', state: 'reuse' },
      { label: '图像生成', detail: '同套图，需接图像模型', state: 'todo' },
    ],
    reference: ['风格复刻的关键不是「像」，而是「换了商品还像」', '画像必须可编辑，纯提示词不可维护'],
  },
  {
    pane: 'sku',
    goal: '版式、光线、阴影都不动，只把画面里的商品换成新的那个。',
    inputs: ['底图（已有版式）', '新商品图（白底）', '替换区域提示（可选）'],
    outputs: ['替换后成图', '掩码与生成参数', '与底图的差异对比'],
    steps: [
      { title: '选底图', detail: '从素材库或刚生成的成图里挑' },
      { title: '抠主体', detail: '分割出要替换的区域' },
      { title: '换品', detail: '局部重绘，保持背景与投影' },
      { title: '校准光影', detail: '色温、强度、投影方向对齐底图' },
    ],
    capabilities: [
      { label: '交互式分割', detail: '需要点选 / 框选生成掩码，无现成能力', state: 'todo' },
      { label: '局部重绘（inpaint）', detail: '图像编辑接口，缺失', state: 'todo' },
      { label: '光影匹配', detail: '可先用提示词近似，效果不可控', state: 'todo' },
    ],
    reference: ['SKU 替换是电商最高频场景：同一套版式换 N 个 SKU', '必须支持批量：一个底图 × 多个商品图'],
  },
  {
    pane: 'outfit',
    goal: '上衣 + 下装自由搭配，生成成套上身图，单品可复用。',
    inputs: ['上装图 / 下装图', '模特图（可选）', '姿势与场景偏好'],
    outputs: ['成套上身图 ×N', '搭配清单（上装 ↔ 下装）'],
    steps: [
      { title: '选版型', detail: '确定品类与版型约束，避免生成不存在的结构' },
      { title: '配上下装', detail: '从素材库挑，或上传' },
      { title: '成套出图', detail: '同一次生成内保持同一模特与场景' },
    ],
    capabilities: [
      { label: '服装分割与品类识别', detail: '需视觉模型 + 分割，缺失', state: 'todo' },
      { label: '多图一致性生成', detail: '同一次任务内锁定人物 / 场景，需专门参数', state: 'todo' },
      { label: '搭配关系建模', detail: '可用现有关系表思路，需要新表', state: 'todo' },
    ],
    reference: ['服装组图的难点是一致性，不是单图质量', '单品图与成套图要能双向追溯'],
  },
  {
    pane: 'retouch',
    goal: '单图修到能上架：去瑕疵、去水印、换背景、提清晰度。',
    inputs: ['原图', '修复项勾选（可多选）', '目标背景（换背景时）'],
    outputs: ['修复图', '前后对比', '修复项记录（可撤回到单项）'],
    steps: [
      { title: '上传原图', detail: '校验尺寸与格式' },
      { title: '选修复项', detail: '每项一次独立调用，便于单点重试' },
      { title: '对比保存', detail: '左右对比，接受后写回素材' },
    ],
    capabilities: [
      { label: '去瑕疵 / 去水印', detail: '图像编辑接口，缺失', state: 'todo' },
      { label: '超分 / 清晰度增强', detail: '需专用模型', state: 'todo' },
      { label: '换背景（分割 + 合成）', detail: '依赖主体掩码，缺失', state: 'todo' },
      { label: '原图上传', detail: '已具备：走素材库上传（本地磁盘）', state: 'ready' },
    ],
    reference: ['精修的价值在「可控」：每项可单独开关、单独回退'],
  },
  {
    pane: 'canvas',
    goal: '把散装成图排成一张能上架的详情页长图，一次导出多尺寸。',
    inputs: ['成图多张（来自套图 / 精修）', '模板（详情页 / 主图 / 长图）', '品牌信息（可选）'],
    outputs: ['排版结果', '多尺寸导出（含平台预设）', '可再编辑的版式数据'],
    steps: [
      { title: '拉入图片', detail: '从素材库或当前任务结果' },
      { title: '排版', detail: '模板约束下的拖拽与自动对齐' },
      { title: '导出多尺寸', detail: '一套版式导出多平台规格' },
    ],
    capabilities: [
      { label: '前端排版引擎', detail: '可作为纯前端能力优先实现，不依赖后端', state: 'reuse' },
      { label: '服务端导出 / 转码', detail: '多尺寸批量导出需要服务端渲染，缺失', state: 'todo' },
      { label: '模板库', detail: '需数据库配置 + 前端渲染器', state: 'todo' },
    ],
    reference: ['画布是唯一可以在没有出图能力时先跑通的功能', '版式数据要能存能读，否则导出即终点'],
  },
  {
    pane: 'assets',
    goal: '商品、风格、成图统一沉淀：能找到、能复用、能追溯从哪来。',
    inputs: ['上传文件 / 生成结果自动入库', '两级目录（一级五类 + 可自建的二级目录）', '备注与标签'],
    outputs: ['按目录浏览的素材列表与检索', '静态直链（可直接贴进 prompt 或页面）', '磁盘占用与一致性核对'],
    steps: [
      { title: '上传', detail: '拖拽 / 点选，服务端算 sha256 去重，同名同内容只存一份' },
      { title: '归入目录', detail: '上传时选一级 + 二级；预览弹层可移动；改一级会清掉旧二级，避免素材藏进看不见的组合' },
      { title: '复用', detail: '其他功能以 URL 引用，不复制文件；选图弹窗里按目录浏览 / 搜索 / 多选，也可就地上传后自动进入待选' },
    ],
    capabilities: [
      {
        label: '文件存储（本地磁盘）',
        detail: '已具备：backend/data/media/{年}/{月}/{uuid}.ext，静态直出 /api/media/files/*；换 OSS 只改 media_store.py',
        state: 'ready',
      },
      {
        label: '两级分类目录',
        detail: '已具备：media_categories 表 + media_assets.category；目录树带计数、新建 / 删除、按目录筛选、移动素材、未归类虚拟节点；删目录不删图',
        state: 'ready',
      },
      {
        label: '一级目录显示名',
        detail: '已具备：五个 key 固定不动，显示名存 media_kind_labels，素材库里双击 / 铅笔改名、回车保存、可一键恢复默认；目录树 / 上传区 / 选图弹窗 / 槽位提示 / 卡片全部读同一份目录树',
        state: 'ready',
      },
      {
        label: '去重与一致性核对',
        detail: '已具备：sha256 去重；/api/media/files-check 查丢失与孤儿，/api/media/files-cleanup 默认 dry-run、显式 apply 才删',
        state: 'ready',
      },
      {
        label: '安全边界',
        detail: '已具备：文件名服务端生成、拒绝 SVG / HTML（防存储型 XSS）、20MB 上限、路径穿越校验',
        state: 'ready',
      },
      {
        label: '标签与检索',
        detail: '文件名 / 备注搜索已通；tags 字段已建，前端标签编辑未做',
        state: 'reuse',
      },
      {
        label: '血缘关系表',
        detail: 'parent_id 已写入：生成图指向输入素材；素材 → 任务 → 素材 的完整追溯 UI 未做',
        state: 'reuse',
      },
    ],
    reference: ['素材库不是文件夹，是其他所有功能的输入来源', '没有血缘就说不清「这张图能不能删」'],
  },
  {
    pane: 'endpoints',
    goal: '把「很多个图像端点」管成池，绑到服务，再在每次出图时按镜头能力动态挑端点。',
    inputs: [
      '任意多个端点：协议 / base_url / 模型名 / 密钥模式 / 能力标签 / 参数 / 超时 / 优先级',
      '每个服务一条有序候选链（可按具体动作覆盖）',
      '任务创建时的运行时端点选择（本次覆盖）',
    ],
    outputs: ['端点池与密钥状态（不回显明文）', '服务 → 候选链绑定', '逐镜头实际命中的端点与失败尝试记录'],
    steps: [
      { title: '注册端点', detail: '端点是一等数据，不是代码常量；协议适配 webhook / OpenAI 图像 / 火山方舟 / 内置兜底' },
      { title: '绑定服务', detail: '候选链顺序就是 fallback 顺序；可给某个动作单独配链，优先于默认链' },
      { title: '运行时选择', detail: '镜头标题翻译成能力标签，网关按能力解析候选链逐个尝试；任务里还能临时指定端点' },
      { title: '结果留痕', detail: '每张成图记录命中端点 / 协议 / 耗时 / 尝试链，素材库里对单图也能即席处理' },
    ],
    capabilities: [
      {
        label: '端点池与密钥隔离',
        detail: '已具备：image_endpoints 表可任意增删；密钥 none / env / inline 三种模式，接口只回掩码，推荐 env 只存变量名',
        state: 'ready',
      },
      {
        label: '服务绑定候选链',
        detail: '已具备：image_endpoint_bindings 按 service + capability 存有序链，支持上移 / 下移 / 添加 / 删除；具体动作链优先于默认链',
        state: 'ready',
      },
      {
        label: '按能力动态分派',
        detail: '已具备：8 类能力标签，infer_capability() 把镜头翻译成能力，网关逐项尝试失败 endpoint 后回落下一项，全失败才用内置占位图',
        state: 'ready',
      },
      {
        label: '运行时端点选择',
        detail: '已具备：任务创建可传 endpoint_key / endpoint_params，本次覆盖提前但仍保留 fallback；规划页提前展示每张镜头将用哪个端点',
        state: 'ready',
      },
      {
        label: '单图即席处理',
        detail: '已具备：素材库对一张已有图选动作 + 选端点，走同一网关，结果回写素材库并记 image_process_jobs',
        state: 'ready',
      },
      {
        label: '真实图像模型',
        detail: '取决于使用者配置：没配任何可用端点时仍回落 PIL 占位图；本仓库不内置第三方模型凭证',
        state: 'todo',
      },
      {
        label: '异步执行可靠性',
        detail: '后台任务仍是进程内 BackgroundTasks，进程被 kill / reload 会中断；出图任务有自愈回收，即席处理暂未做启动回收',
        state: 'reuse',
      },
    ],
    reference: ['端点要能加很多个，不能写死成「五个功能各配一个模型」', '绑定是候选集不是单选；运行时选择是本次覆盖，不是改绑定'],
  },
]

/** 五个出图功能共用的一条能力，不在每页重复写一遍 */
const TASK_PANES: ReadonlySet<StudioPane> = new Set<StudioPane>([
  'set',
  'style',
  'sku',
  'outfit',
  'retouch',
])

const SHARED_TASK_CAPABILITY: StudioCapability = {
  label: '两阶段任务链路',
  detail: '已具备：功能专属输入表单与素材角色（弹窗选图：两级目录 + 网格 + 搜索 + 多选 + 就地上传，确认后一次写回，旧任务按 id 回显）、按 kind 生成的逐图规划（带专属元信息 + 能力标签 + 将用哪个端点）、运行时端点选择、人工确认闸门、后台执行、进度轮询、逐镜头路由留痕、中断任务自愈与重跑；规划仍是规则引擎，无可用端点时成图回落占位图',
  state: 'ready',
}

export const STUDIO_SPECS: StudioPaneSpec[] = RAW_SPECS.map((spec) =>
  TASK_PANES.has(spec.pane)
    ? { ...spec, capabilities: [SHARED_TASK_CAPABILITY, ...spec.capabilities] }
    : spec,
)

export const STUDIO_SPEC_BY_PANE: Record<Exclude<StudioPane, 'home'>, StudioPaneSpec> =
  Object.fromEntries(STUDIO_SPECS.map((spec) => [spec.pane, spec])) as Record<
    Exclude<StudioPane, 'home'>,
    StudioPaneSpec
  >

/** 骨架建设的推荐顺序：先把「存储 + 任务 + 规划」打通，再接模型 */
export const STUDIO_ROADMAP: Array<{
  phase: string
  title: string
  detail: string
  depends: string
  done?: boolean
}> = [
  {
    phase: 'P0',
    title: '底座：上传 + 存储 + 素材表 + 两级目录',
    detail: '已完成：文件落 backend/data/media、/api/media/* 接口、media_assets 表、media_categories 两级目录、sha256 去重、槽位就地上传',
    depends: '无',
    done: true,
  },
  {
    phase: 'P1',
    title: '异步任务：任务表 + 轮询',
    detail: '已完成：studio_tasks 表、BackgroundTasks 后台执行、progress 轮询、失败 / 取消 / 重跑，进程中断的任务自动回收',
    depends: 'P0',
    done: true,
  },
  {
    phase: 'P2',
    title: '两阶段：规划 → 确认 → 出图',
    detail: '链路已完成；五个功能各有专属表单与规划内容，规划暂用规则引擎、出图暂用 mock 占位图，两者都留了替换点',
    depends: 'P1',
    done: true,
  },
  {
    phase: 'P3',
    title: '图像端点网关',
    detail: '已完成：端点池 + 服务绑定候选链 + 按能力动态分派 + 协议适配器 + 运行时端点选择 + 单图即席处理；没配端点时回落 _render_shot 占位图，规划仍可换 LLM',
    depends: 'P2',
    done: true,
  },
  {
    phase: 'P4',
    title: '画布与导出',
    detail: '可独立于模型先做，产出可演示的闭环',
    depends: 'P0',
  },
]
