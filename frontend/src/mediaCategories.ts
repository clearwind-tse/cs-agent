// -*- coding: utf-8 -*-
/**
 * 素材库两级目录的展示层公共逻辑
 *
 * 一级 key 固定五类（保证 studioKinds 默认目录、后端白名单、生成结果归类不出错），
 * 但**显示名可以由用户改**并存在 media_kind_labels 表里。所以任何要显示一级名字的地方
 * 都必须走 kindLabel(tree, kind) 取目录树里的 label，不能直接读 KIND_META[kind].label——
 * 后者只是「表没加载 / 接口挂了」时的兜底。
 */
import { UNCATEGORIZED, type MediaCategoryNode, type MediaCategoryTree, type MediaKind } from './api'

/** 配色 / 圆点这类与 key 绑定的视觉元信息，不随显示名变化 */
export const KIND_META: Record<MediaKind, { label: string; chip: string; dot: string }> = {
  product: { label: '商品图', chip: 'text-info border-iris/30 bg-iris/10', dot: 'bg-iris' },
  style: { label: '风格参考', chip: 'text-flare border-flare/30 bg-flare/10', dot: 'bg-flare' },
  result: { label: '成图', chip: 'text-ok border-ok/30 bg-ok/10', dot: 'bg-ok' },
  reference: { label: '参考图', chip: 'text-warn border-warn/30 bg-warn/10', dot: 'bg-warn' },
  other: { label: '其他', chip: 'text-ink-subtle border-line/70 bg-panel-2/60', dot: 'bg-line-strong' },
}

export const KIND_ORDER: MediaKind[] = ['product', 'style', 'result', 'reference', 'other']

/** 生效中的一级显示名；tree 未就绪时回落到代码默认值 */
export function kindLabel(tree: MediaCategoryTree | null, kind: MediaKind): string {
  return tree?.groups.find((group) => group.kind === kind)?.label || KIND_META[kind]?.label || kind
}

export function childrenOf(tree: MediaCategoryTree | null, kind: MediaKind): MediaCategoryNode[] {
  return tree?.groups.find((group) => group.kind === kind)?.children ?? []
}

export function categoryLabel(tree: MediaCategoryTree | null, kind: MediaKind, key: string): string {
  if (!key || key === UNCATEGORIZED) return '未归类'
  return childrenOf(tree, kind).find((node) => node.key === key)?.label ?? key
}

/** 「商品图 / 白底图」这样的完整路径，用于缩略图 title 与卡片标签 */
export function directoryLabel(tree: MediaCategoryTree | null, kind: MediaKind, key: string): string {
  return `${kindLabel(tree, kind)} / ${categoryLabel(tree, kind, key)}`
}
