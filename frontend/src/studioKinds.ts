// -*- coding: utf-8 -*-
/**
 * studioKinds.ts — 五个出图功能各自的输入契约
 *
 * 为什么必须有这一层：之前五个功能共用一张「选一堆图 + 张数 + 比例 + 备注」的表单，
 * 点进去除了标题几乎一样，用户根本分不清自己在哪个功能、该给什么东西。
 * 实际上它们的输入**结构不同**：
 *   SKU 替换要「底图」和「新商品图」两个角色，服装组图要「上装 / 下装 / 模特」，
 *   精修是按勾选项出图，风格复刻要锁定维度——不是同一堆素材换个模板就行。
 *
 * 这里只描述「每个功能要什么」，表单由 StudioTaskRunner 按契约渲染；
 * 后端 studio_task_service.KIND_CONFIG 用同样的 slot/field key 做白名单与规划，
 * 改 key 时两边必须同步（后端会对未知 key 直接丢弃，不会报错也不会误用）。
 */
import type { MediaKind, StudioTaskKind } from './api'

/** 有角色的素材位：不是「一堆图」，而是「哪张图当底图 / 哪张当新品」 */
export interface StudioAssetSlot {
  key: string
  label: string
  hint: string
  /** 最多选几张，1 表示单选 */
  max: number
  required?: boolean
  /** 就地上传时默认归入的一级 / 二级目录：别让新图散落在「未归类」 */
  uploadKind: MediaKind
  uploadCategory?: string
  /** 打开「从素材库选择」时默认筛到哪个一级目录，仍可切到全部 */
  browseKind?: MediaKind
}

export type StudioField =
  | {
      type: 'multi'
      key: string
      label: string
      hint: string
      options: Array<{ value: string; label: string }>
      /** 至少选几项，0 表示可全不选 */
      min?: number
      defaults?: string[]
    }
  | {
      type: 'choice'
      key: string
      label: string
      hint: string
      options: Array<{ value: string; label: string }>
      default: string
    }
  | {
      type: 'text'
      key: string
      label: string
      hint?: string
      placeholder: string
      maxLength: number
    }

export interface StudioKindConfig {
  kind: StudioTaskKind
  /** 一句话说清这个功能解决什么，配置页顶部 */
  tagline: string
  /** 这一功能专属的素材角色 */
  slots: StudioAssetSlot[]
  /** 这一功能专属的选项 */
  fields: StudioField[]
  /** 「张数」在不同功能里语义不同 */
  countLabel: string
  countHint: string
  defaultCount: number
  /** 产出说明 */
  outputHint: string
  /** 静态主题色类名：Tailwind 只扫描字面量，不能靠字符串替换拼类名 */
  accent: {
    text: string
    bg: string
    border: string
    dot: string
  }
}

const ACCENTS = {
  flare: { text: 'text-flare', bg: 'bg-flare/15', border: 'border-flare/35', dot: 'bg-flare' },
  iris: { text: 'text-iris', bg: 'bg-iris/15', border: 'border-iris/35', dot: 'bg-iris' },
  mint: { text: 'text-mint', bg: 'bg-mint/15', border: 'border-mint/35', dot: 'bg-mint' },
  ok: { text: 'text-ok', bg: 'bg-ok/15', border: 'border-ok/35', dot: 'bg-ok' },
  warn: { text: 'text-warn', bg: 'bg-warn/15', border: 'border-warn/35', dot: 'bg-warn' },
} as const

export const STUDIO_KIND_CONFIGS: Record<StudioTaskKind, StudioKindConfig> = {
  set: {
    kind: 'set',
    tagline: '一张商品图进去，一套主图 + 详情图出来，先把要出哪几张定清楚。',
    slots: [
      { key: 'product', label: '商品图', hint: '白底或实拍，作为画面主体', max: 5, required: true, uploadKind: 'product', uploadCategory: 'white_bg', browseKind: 'product' },
      { key: 'reference', label: '风格参考', hint: '可选，用来对齐色温与留白', max: 3, uploadKind: 'style', uploadCategory: 'color', browseKind: 'style' },
    ],
    fields: [
      {
        type: 'choice',
        key: 'platform',
        label: '目标平台',
        hint: '决定默认构图与留白比例',
        default: '通用',
        options: [
          { value: '通用', label: '通用' },
          { value: '淘宝主图', label: '淘宝主图' },
          { value: '抖音竖版', label: '抖音竖版' },
          { value: '小红书', label: '小红书' },
        ],
      },
      {
        type: 'multi',
        key: 'modules',
        label: '详情模块',
        hint: '勾选的模块会排进详情图，不勾就只出主图',
        min: 0,
        defaults: ['卖点分栏', '场景'],
        options: [
          { value: '尺寸标注', label: '尺寸标注' },
          { value: '卖点分栏', label: '卖点分栏' },
          { value: '材质特写', label: '材质特写' },
          { value: '场景', label: '使用场景' },
        ],
      },
      {
        type: 'text',
        key: 'selling_point',
        label: '核心卖点',
        placeholder: '例：双层真空，保温 12 小时',
        maxLength: 120,
      },
    ],
    countLabel: '本次出图张数',
    countHint: '包含主图与勾选的详情模块',
    defaultCount: 4,
    outputHint: '主图 + 详情图，每张带构图、文案位与提示词',
    accent: ACCENTS.flare,
  },

  style: {
    kind: 'style',
    tagline: '把参考图的调性抽成可锁定的维度，换商品也不跑偏。',
    slots: [
      { key: 'reference', label: '风格参考图', hint: '提供色温、光线、构图基准', max: 3, required: true, uploadKind: 'style', uploadCategory: 'color', browseKind: 'style' },
      { key: 'product', label: '目标商品图', hint: '要套用该风格的新商品', max: 3, required: true, uploadKind: 'product', uploadCategory: 'white_bg', browseKind: 'product' },
    ],
    fields: [
      {
        type: 'multi',
        key: 'lock',
        label: '锁定维度',
        hint: '勾选项会在每张图里保持一致，未勾的允许自由发挥',
        min: 1,
        defaults: ['色板', '光线', '构图'],
        options: [
          { value: '色板', label: '色板' },
          { value: '光线', label: '光线' },
          { value: '构图', label: '构图' },
          { value: '材质', label: '材质' },
        ],
      },
      {
        type: 'choice',
        key: 'similarity',
        label: '复刻强度',
        hint: '强度越高越贴近参考图，越低越自由',
        default: '平衡',
        options: [
          { value: '严格', label: '严格' },
          { value: '平衡', label: '平衡' },
          { value: '只要感觉', label: '只要感觉' },
        ],
      },
    ],
    countLabel: '产出张数',
    countHint: '同一风格下的不同角度 / 场景',
    defaultCount: 3,
    outputHint: '同风格的多角度成图，附锁定维度与相似度说明',
    accent: ACCENTS.iris,
  },

  sku: {
    kind: 'sku',
    tagline: '版式、光线、阴影都不动，只把画面里的商品换成新的那个。',
    slots: [
      { key: 'base', label: '底图', hint: '已有版式的成图，只取一张', max: 1, required: true, uploadKind: 'result', uploadCategory: 'main', browseKind: 'result' },
      { key: 'new_sku', label: '新商品图', hint: '白底图，可批量；每张出一组替换结果', max: 6, required: true, uploadKind: 'product', uploadCategory: 'white_bg', browseKind: 'product' },
    ],
    fields: [
      {
        type: 'text',
        key: 'region',
        label: '替换区域提示',
        hint: '描述主体所在范围，便于将来接分割模型',
        placeholder: '例：画面中央的杯身，保留左侧文案',
        maxLength: 120,
      },
      {
        type: 'choice',
        key: 'shadow',
        label: '投影处理',
        hint: '决定要不要沿用底图原有投影',
        default: '沿用底图投影',
        options: [
          { value: '沿用底图投影', label: '沿用底图投影' },
          { value: '按新品重算', label: '按新品重算' },
        ],
      },
    ],
    countLabel: '每个 SKU 出图数',
    countHint: '总产出 = 新商品图数 × 每个 SKU 出图数',
    defaultCount: 1,
    outputHint: '每个新 SKU 一组替换图，沿用底图版式与光影',
    accent: ACCENTS.mint,
  },

  outfit: {
    kind: 'outfit',
    tagline: '上装与下装自由搭配，同一次任务内锁定同一模特与场景。',
    slots: [
      { key: 'top', label: '上装', hint: '可多选，用于组合搭配', max: 3, required: true, uploadKind: 'product', uploadCategory: 'live', browseKind: 'product' },
      { key: 'bottom', label: '下装', hint: '可多选，用于组合搭配', max: 3, required: true, uploadKind: 'product', uploadCategory: 'live', browseKind: 'product' },
      { key: 'model', label: '模特图', hint: '可选，用于锁定人物一致性', max: 1, uploadKind: 'reference', uploadCategory: 'mood', browseKind: 'reference' },
    ],
    fields: [
      {
        type: 'choice',
        key: 'pose',
        label: '姿势',
        hint: '同批成图保持一致',
        default: '站姿',
        options: [
          { value: '站姿', label: '站姿' },
          { value: '坐姿', label: '坐姿' },
          { value: '行走', label: '行走' },
        ],
      },
      {
        type: 'choice',
        key: 'scene',
        label: '场景',
        hint: '影响背景与光线设定',
        default: '棚拍',
        options: [
          { value: '棚拍', label: '棚拍' },
          { value: '街拍', label: '街拍' },
          { value: '居家', label: '居家' },
        ],
      },
      {
        type: 'choice',
        key: 'scope',
        label: '产出范围',
        hint: '单品图便于复用，成套图用于上架',
        default: '成套 + 单品',
        options: [
          { value: '成套 + 单品', label: '成套 + 单品' },
          { value: '只要成套', label: '只要成套' },
        ],
      },
    ],
    countLabel: '每套搭配张数',
    countHint: '同一搭配下的不同角度',
    defaultCount: 2,
    outputHint: '成套上身图 + 可复用的单品图，附搭配清单',
    accent: ACCENTS.warn,
  },

  retouch: {
    kind: 'retouch',
    tagline: '单图修到能上架，每个修复项独立成图，方便单独取舍。',
    slots: [{ key: 'source', label: '原图', hint: '只取一张，逐项精修', max: 1, required: true, uploadKind: 'product', uploadCategory: 'live', browseKind: 'product' }],
    fields: [
      {
        type: 'multi',
        key: 'fixes',
        label: '修复项',
        hint: '每勾一项就产出一张对应结果图',
        min: 1,
        defaults: ['去瑕疵', '提清晰度'],
        options: [
          { value: '去瑕疵', label: '去瑕疵' },
          { value: '去水印', label: '去水印' },
          { value: '换背景', label: '换背景' },
          { value: '提清晰度', label: '提清晰度' },
        ],
      },
      {
        type: 'text',
        key: 'background',
        label: '目标背景',
        hint: '勾选「换背景」时生效',
        placeholder: '例：纯暖白，柔和顶光',
        maxLength: 120,
      },
    ],
    countLabel: '每项产出张数',
    countHint: '总产出 = 勾选修复项数 × 每项张数',
    defaultCount: 1,
    outputHint: '逐项修复结果图 + 前后对比用的修复记录',
    accent: ACCENTS.ok,
  },
}

export type StudioSlotValues = Record<string, number[]>
export type StudioFieldValues = Record<string, string | string[]>

/** 新建表单的初始值；切功能时必须重新算，不能沿用上一个功能的选择 */
export function initialFormValues(config: StudioKindConfig): {
  slots: StudioSlotValues
  fields: StudioFieldValues
  count: number
} {
  const slots: StudioSlotValues = {}
  for (const slot of config.slots) slots[slot.key] = []

  const fields: StudioFieldValues = {}
  for (const field of config.fields) {
    if (field.type === 'multi') fields[field.key] = [...(field.defaults ?? [])]
    else if (field.type === 'choice') fields[field.key] = field.default
    else fields[field.key] = ''
  }
  return { slots, fields, count: config.defaultCount }
}

/** 前端校验：把「能不能生成规划」的判断放在提交前，别让用户白等一个 400 */
export function validateForm(
  config: StudioKindConfig,
  slots: StudioSlotValues,
  fields: StudioFieldValues,
): string | null {
  for (const slot of config.slots) {
    const picked = slots[slot.key] ?? []
    if (slot.required && picked.length === 0) return `请先选择「${slot.label}」`
  }
  for (const field of config.fields) {
    if (field.type !== 'multi') continue
    const value = fields[field.key]
    const picked = Array.isArray(value) ? value : []
    if ((field.min ?? 0) > 0 && picked.length < (field.min ?? 0)) {
      return `「${field.label}」至少选 ${field.min} 项`
    }
  }
  return null
}

/** 所有槽位的素材 id 扁平去重，后端 asset_ids 仍用这个字段做存在性校验 */
export function flattenAssetIds(slots: StudioSlotValues): number[] {
  return Array.from(new Set(Object.values(slots).flat()))
}

/** 配置摘要，给「本次任务」卡片与规划页读，避免每个功能都显示同一句话 */
export function describeForm(
  config: StudioKindConfig,
  slots: StudioSlotValues,
  fields: StudioFieldValues,
  count: number,
): string[] {
  const lines: string[] = []
  for (const slot of config.slots) {
    const picked = slots[slot.key] ?? []
    lines.push(`${slot.label} ${picked.length}/${slot.max}`)
  }
  for (const field of config.fields) {
    const value = fields[field.key]
    if (field.type === 'multi') {
      const picked = Array.isArray(value) ? value : []
      if (picked.length) lines.push(`${field.label} ${picked.join(' / ')}`)
    } else if (field.type === 'choice') {
      lines.push(`${field.label} ${value || field.default}`)
    } else if (value) {
      lines.push(`${field.label} ${value}`)
    }
  }
  lines.push(`${config.countLabel} ${count}`)
  return lines
}
