// -*- coding: utf-8 -*-
/**
 * StudioAssetSlotPicker — 一个「有角色」的素材位（紧凑卡片 + 弹窗选图）
 *
 * 配置页里不再为每个角色平铺一条长缩略图：三个角色会把页面撑到要滚两屏，
 * 窄条里也看不清图。现在槽位只显示「已选什么」，点「选择素材」才打开弹窗，
 * 在弹窗里按两级目录浏览 / 搜索 / 多选 / 就地上传，确认后一次性写回。
 *
 * 已选素材按 id 单独回显（listMedia({ids})），不依赖「最近 100 张」缓存：
 * 打开一条旧任务时，它当时选的图可能早就排到第一页之外了。
 */
import { useEffect, useState } from 'react'
import { ImagePlus, X } from 'lucide-react'
import { cn } from '../utils'
import { listMedia, type MediaAsset, type MediaCategoryTree } from '../api'
import { directoryLabel } from '../mediaCategories'
import type { StudioAssetSlot } from '../studioKinds'
import StudioAssetPickerModal from './StudioAssetPickerModal'

export default function StudioAssetSlotPicker({
  slot,
  tree,
  accent,
  picked,
  onSetPicked,
  onUploaded,
}: {
  slot: StudioAssetSlot
  tree: MediaCategoryTree | null
  accent: { text: string; bg: string; border: string; dot: string }
  picked: number[]
  onSetPicked: (ids: number[]) => void
  onUploaded?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [known, setKnown] = useState<Record<number, MediaAsset>>({})

  // 只补查还没见过的 id；旧任务回显的素材可能不在最近列表里
  useEffect(() => {
    const missing = picked.filter((id) => !known[id])
    if (missing.length === 0) return
    let alive = true
    void listMedia({ ids: missing, page_size: 100 })
      .then(({ items }) => {
        if (!alive) return
        setKnown((previous) => {
          const next = { ...previous }
          for (const asset of items) next[asset.id] = asset
          return next
        })
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [picked, known])

  const remove = (id: number) => onSetPicked(picked.filter((value) => value !== id))

  return (
    <>
      <div className="rounded-xl border border-line/60 bg-panel-2/25 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', accent.dot)} />
          <span className="text-[11px] font-medium text-ink flex-shrink-0">{slot.label}</span>
          {slot.required && <span className="text-[9px] text-bad flex-shrink-0">必选</span>}
          <span className="text-[10px] text-ink-subtle truncate" title={slot.hint}>
            {slot.hint}
          </span>
          <span className="ml-auto font-mono text-[10px] text-ink-subtle flex-shrink-0">
            {picked.length}/{slot.max}
          </span>
          {picked.length > 0 && (
            <button
              type="button"
              onClick={() => onSetPicked([])}
              aria-label={`清空${slot.label}`}
              title="清空这个角色"
              className="p-0.5 rounded text-ink-subtle hover:text-bad transition-colors"
            >
              <X size={11} />
            </button>
          )}
        </div>

        <div className="flex items-center gap-1.5 mt-2 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {picked.map((id) => {
            const asset = known[id]
            return (
              <div key={id} className="relative w-12 h-12 flex-shrink-0 group/chip">
                <button
                  type="button"
                  onClick={() => setOpen(true)}
                  title={asset ? `${asset.original_name} · 点击重新选择` : `素材 #${id} · 点击重新选择`}
                  aria-label="重新选择素材"
                  className="w-full h-full rounded-lg overflow-hidden border border-flare/60 bg-panel-2/60"
                >
                  {asset ? (
                    <img src={asset.url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <span className="w-full h-full flex items-center justify-center font-mono text-[9px] text-ink-subtle">
                      #{id}
                    </span>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => remove(id)}
                  aria-label={`移除素材 #${id}`}
                  title="移除"
                  className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-scrim/85 text-brand-fg flex items-center justify-center opacity-0 group-hover/chip:opacity-100 transition-opacity"
                >
                  <X size={9} />
                </button>
              </div>
            )
          })}

          <button
            type="button"
            onClick={() => setOpen(true)}
            className={cn(
              'h-12 flex-shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-dashed px-3 text-[10px] transition-colors',
              picked.length === 0
                ? cn(accent.border, accent.bg, 'text-ink')
                : 'border-line-strong/70 text-ink-subtle hover:text-ink hover:border-flare/50',
            )}
          >
            <ImagePlus size={12} />
            {picked.length === 0 ? '选择素材' : '继续添加'}
          </button>

          <span className="ml-auto text-[9px] text-ink-subtle whitespace-nowrap pl-2 flex-shrink-0" title="就地上传时的默认归档目录">
            上传归入 {directoryLabel(tree, slot.uploadKind, slot.uploadCategory ?? '')}
          </span>
        </div>
      </div>

      <StudioAssetPickerModal
        open={open}
        slot={slot}
        tree={tree}
        accent={accent}
        selected={picked}
        onClose={() => setOpen(false)}
        onConfirm={onSetPicked}
        onUploaded={onUploaded}
      />
    </>
  )
}
