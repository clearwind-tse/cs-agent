// -*- coding: utf-8 -*-
/**
 * StudioAssetPickerModal — 槽位选图弹窗
 *
 * 之前每个素材角色都在配置页里平铺一条缩略图，三个角色的页面被撑得很长，
 * 而且窄条里既看不清图也放不下目录树。现在改成「点一下 → 弹窗里挑」：
 *   左侧两级目录树 + 右侧大图网格 + 搜索，选好一次性确认写回槽位；
 *   另一个 Tab 就地上传，传完自动进入待选并切回素材库。
 *
 * 弹窗自己按目录/关键词查后端（不复用父组件那 100 张缓存），
 * 所以素材库超过 100 张时仍可按目录或搜索找到老图。
 * 传给后端的 category 一定和具体 kind 同传：二级 key 只在一级内唯一，
 * 否则 product.detail 与 result.detail 会串。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Image as ImageIcon,
  ImageOff,
  ImagePlus,
  Loader2,
  Search,
  UploadCloud,
  X,
} from 'lucide-react'
import { cn } from '../utils'
import {
  UNCATEGORIZED,
  listMedia,
  uploadMedia,
  type MediaAsset,
  type MediaCategoryTree,
  type MediaKind,
} from '../api'
import { useToast } from '../contexts/ToastContext'
import {
  categoryLabel,
  childrenOf,
  directoryLabel,
  kindLabel,
  KIND_ORDER,
} from '../mediaCategories'
import type { StudioAssetSlot } from '../studioKinds'

type Tab = 'library' | 'upload'

const SELECT_CLASS =
  'rounded-lg border border-line/70 bg-panel/70 px-2 py-1.5 text-[11px] text-ink-muted focus:border-flare/50 focus:outline-none'

interface Props {
  open: boolean
  slot: StudioAssetSlot
  tree: MediaCategoryTree | null
  accent: { text: string; bg: string; border: string; dot: string }
  selected: number[]
  onClose: () => void
  onConfirm: (ids: number[]) => void
  /** 上传成功后通知父组件刷新目录树计数 */
  onUploaded?: () => void
}

export default function StudioAssetPickerModal({
  open,
  slot,
  tree,
  accent,
  selected,
  onClose,
  onConfirm,
  onUploaded,
}: Props) {
  const { showToast } = useToast()
  const [tab, setTab] = useState<Tab>('library')
  const [kindFilter, setKindFilter] = useState<MediaKind | 'all'>(slot.browseKind ?? 'all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(KIND_ORDER.map((kind) => [kind, true])),
  )
  const [keyword, setKeyword] = useState('')
  const [debounced, setDebounced] = useState('')
  const [rows, setRows] = useState<MediaAsset[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState<number[]>(selected)

  const [uploadKind, setUploadKind] = useState<MediaKind>(slot.uploadKind)
  const [uploadCategory, setUploadCategory] = useState(slot.uploadCategory ?? '')
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // 只有「成图」类角色（如 SKU 替换的底图）允许选生成的成图；其余角色是输入素材
  const allowGenerated = slot.browseKind === 'result'

  // 每次打开重置草稿与筛选，避免上一个槽位的选择串过来
  useEffect(() => {
    if (!open) return
    setDraft(selected)
    setTab('library')
    setKindFilter(slot.browseKind ?? 'all')
    setCategoryFilter('all')
    setKeyword('')
    setDebounced('')
    setUploadKind(slot.uploadKind)
    setUploadCategory(slot.uploadCategory ?? '')
    // selected / slot 只作为打开瞬间的初值，弹窗里的草稿不随外部变化重设
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, slot.key])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(keyword.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [keyword])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const useCategory = categoryFilter !== 'all' && kindFilter !== 'all' ? categoryFilter : undefined
      const data = await listMedia({
        kind: kindFilter === 'all' ? undefined : kindFilter,
        category: useCategory,
        q: debounced || undefined,
        page_size: 100,
      })
      setRows(allowGenerated ? data.items : data.items.filter((item) => item.source !== 'generated'))
      setTotal(data.total)
    } catch {
      setRows([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [kindFilter, categoryFilter, debounced, allowGenerated])

  useEffect(() => {
    if (!open || tab !== 'library') return
    void load()
  }, [open, tab, load])

  // ESC 关闭 + 锁滚动
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  const toggle = (id: number) => {
    // 提示用闭包里的 draft 判断即可；写入必须用函数式更新，
    // 否则快速连点两张卡时两次点击都基于同一个旧数组，后一次会把前一次覆盖掉。
    if (slot.max !== 1 && draft.length >= slot.max && !draft.includes(id)) {
      showToast(`「${slot.label}」最多选 ${slot.max} 张`, 'warning')
      return
    }
    setDraft((previous) => {
      if (previous.includes(id)) return previous.filter((value) => value !== id)
      if (slot.max === 1) return [id]
      if (previous.length >= slot.max) return previous
      return [...previous, id]
    })
  }

  const handleFiles = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((file) => file.type.startsWith('image/') || file.type === '')
    if (list.length === 0) {
      showToast('只支持图片文件', 'error')
      return
    }
    setUploading({ done: 0, total: list.length })
    const uploaded: MediaAsset[] = []
    for (let index = 0; index < list.length; index += 1) {
      try {
        const { item, reused } = await uploadMedia(list[index], {
          kind: uploadKind,
          category: uploadCategory || undefined,
        })
        uploaded.push(item)
        if (reused) showToast(`${list[index].name} 已存在，直接复用原文件`, 'info')
      } catch (err: any) {
        showToast(`${list[index].name}：${err?.response?.data?.detail?.message || err?.message || '上传失败'}`, 'error')
      }
      setUploading({ done: index + 1, total: list.length })
    }
    setUploading(null)
    if (uploaded.length === 0) return

    // 传完自动进入待选（满位时顶掉最后一张），并把筛选定位到刚上传的目录
    setDraft((previous) => {
      const next = [...previous]
      for (const asset of uploaded) {
        if (next.includes(asset.id)) continue
        if (slot.max === 1) return [asset.id]
        if (next.length >= slot.max) next.pop()
        next.push(asset.id)
      }
      return next
    })
    setKindFilter(uploadKind)
    setCategoryFilter(uploadCategory || 'all')
    setKeyword('')
    setDebounced('')
    setTab('library')
    onUploaded?.()
    showToast(`已入库 ${uploaded.length} 张并选中，确认后写入「${slot.label}」`, 'success')
  }

  const confirm = () => {
    onConfirm(draft)
    onClose()
  }

  const activeDirectory = useMemo(() => {
    if (kindFilter === 'all') return '全部素材'
    if (categoryFilter === 'all') return kindLabel(tree, kindFilter)
    return directoryLabel(tree, kindFilter, categoryFilter)
  }, [kindFilter, categoryFilter, tree])

  const uploadChildren = childrenOf(tree, uploadKind)

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`为「${slot.label}」选择素材`}
      className="fixed inset-0 z-50 bg-scrim/70 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl h-[min(84vh,780px)] rounded-card border border-line bg-panel shadow-glass flex flex-col overflow-hidden"
        onClick={(event) => event.stopPropagation()}
      >
        {/* 头部：身份 + 两个 Tab + 关闭 */}
        <header className="flex-shrink-0 px-4 py-2.5 border-b border-line flex items-center gap-3 flex-wrap">
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0', accent.bg, accent.text)}>
            <ImageIcon size={16} />
          </div>
          <div className="min-w-0">
            <h3 className="text-[13px] font-medium text-ink leading-tight">为「{slot.label}」选择素材</h3>
            <p className="text-[10px] text-ink-subtle mt-0.5">
              {slot.hint} · 最多 {slot.max} 张
            </p>
          </div>
          <div className="ml-auto flex items-center gap-1 rounded-pill border border-line/70 bg-panel-2/50 p-0.5">
            {(['library', 'upload'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setTab(value)}
                className={cn(
                  'rounded-pill px-3 py-1 text-[11px] transition-colors',
                  tab === value ? cn(accent.bg, 'text-ink') : 'text-ink-subtle hover:text-ink',
                )}
              >
                {value === 'library' ? '从素材库' : '上传新图'}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭选图"
            className="p-1.5 rounded-lg text-ink-subtle hover:text-ink hover:bg-panel-2 transition-colors"
          >
            <X size={16} />
          </button>
        </header>

        {tab === 'library' ? (
          <div className="flex-1 min-h-0 flex">
            {/* 左侧两级目录树 */}
            <aside className="w-48 flex-shrink-0 border-r border-line/70 bg-panel-2/20 p-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <button
                type="button"
                onClick={() => {
                  setKindFilter('all')
                  setCategoryFilter('all')
                }}
                className={cn(
                  'w-full flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] transition-colors',
                  kindFilter === 'all' ? cn(accent.bg, 'text-ink') : 'text-ink-muted hover:bg-panel-2 hover:text-ink',
                )}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-flare/70 flex-shrink-0" />
                全部素材
              </button>

              <div className="mt-1 space-y-0.5">
                    {KIND_ORDER.map((kind) => {
                  const group = tree?.groups.find((entry) => entry.kind === kind)
                  const isOpen = expanded[kind] ?? true
                  // 成图全是生成结果，输入类角色选不到；与其点进去一片空，不如在这里说清
                  const blocked = !allowGenerated && kind === 'result'
                  return (
                    <div key={kind}>
                      <div className="flex items-center">
                        <button
                          type="button"
                          onClick={() => setExpanded((prev) => ({ ...prev, [kind]: !isOpen }))}
                          aria-label={isOpen ? '收起' : '展开'}
                          className="p-1 text-ink-subtle hover:text-ink"
                        >
                          {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                        </button>
                        <button
                          type="button"
                          disabled={blocked}
                          title={blocked ? '生成结果不作为本角色的输入' : undefined}
                          onClick={() => {
                            setKindFilter(kind)
                            setCategoryFilter('all')
                          }}
                          className={cn(
                            'flex-1 flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-[11px] text-left transition-colors',
                            blocked
                              ? 'text-ink-subtle/50 cursor-not-allowed'
                              : kindFilter === kind && categoryFilter === 'all'
                                ? cn(accent.bg, 'text-ink')
                                : 'text-ink-muted hover:bg-panel-2 hover:text-ink',
                          )}
                        >
                          {isOpen ? <FolderOpen size={11} className="flex-shrink-0" /> : <Folder size={11} className="flex-shrink-0" />}
                          <span className="truncate">{kindLabel(tree, kind)}</span>
                          {blocked ? (
                            <span className="ml-auto text-[9px] whitespace-nowrap">不可选</span>
                          ) : (
                            <span className="ml-auto font-mono text-[9px] text-ink-subtle">{group?.count ?? 0}</span>
                          )}
                        </button>
                      </div>
                      {isOpen && !blocked && (
                        <div className="ml-3.5 pl-2 border-l border-line/60 space-y-0.5 mt-0.5">
                          {(group?.children ?? []).map((node) => (
                            <button
                              key={node.key}
                              type="button"
                              onClick={() => {
                                setKindFilter(kind)
                                setCategoryFilter(node.key)
                              }}
                              className={cn(
                                'w-full flex items-center rounded-md px-1.5 py-1 text-[10px] text-left transition-colors',
                                kindFilter === kind && categoryFilter === node.key
                                  ? cn(accent.bg, 'text-ink')
                                  : 'text-ink-subtle hover:bg-panel-2 hover:text-ink',
                              )}
                            >
                              <span className="truncate">{node.label}</span>
                              <span className="ml-auto font-mono text-[9px] opacity-70">{node.count}</span>
                            </button>
                          ))}
                          <button
                            type="button"
                            onClick={() => setCategoryFilter(UNCATEGORIZED)}
                            className={cn(
                              'w-full flex items-center rounded-md px-1.5 py-1 text-[10px] text-left transition-colors',
                              categoryFilter === UNCATEGORIZED
                                ? cn(accent.bg, 'text-ink')
                                : 'text-ink-subtle hover:bg-panel-2 hover:text-ink',
                            )}
                          >
                            未归类
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </aside>

            {/* 右侧：工具栏 + 网格 */}
            <div className="flex-1 min-w-0 flex flex-col">
              <div className="flex-shrink-0 px-3 py-2 border-b border-line/60 flex items-center gap-2 flex-wrap">
                <div className="relative">
                  <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
                  <input
                    value={keyword}
                    onChange={(event) => setKeyword(event.target.value)}
                    placeholder="搜文件名 / 备注"
                    aria-label="搜索素材"
                    className="w-48 rounded-pill border border-line/70 bg-panel/60 pl-7 pr-3 py-1 text-[11px] text-ink placeholder:text-ink-subtle focus:border-flare/50 focus:outline-none"
                  />
                </div>
                <span className="rounded-pill border border-line/70 bg-panel-2/50 px-2 py-0.5 text-[10px] text-ink-muted truncate max-w-[220px]" title={activeDirectory}>
                  {activeDirectory}
                </span>
                <span className="font-mono text-[10px] text-ink-subtle">{rows.length} 张</span>
                {loading && <Loader2 size={11} className="animate-spin text-flare" />}
                {draft.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setDraft([])}
                    className="ml-auto text-[10px] text-ink-subtle hover:text-bad transition-colors"
                  >
                    清空已选
                  </button>
                )}
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto p-3">
                {loading ? (
                  <div className="grid gap-2.5 grid-cols-3 sm:grid-cols-4 xl:grid-cols-5">
                    {Array.from({ length: 10 }).map((_, index) => (
                      <div key={index} className="rounded-xl border border-line/60 overflow-hidden animate-pulse">
                        <div className="aspect-[4/3] bg-panel-2/70" />
                        <div className="px-2 py-1.5">
                          <div className="h-2 w-2/3 rounded bg-panel-3/70" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : rows.length === 0 ? (
                  <div className="h-full min-h-[220px] flex flex-col items-center justify-center text-center">
                    <ImageIcon size={22} className="text-ink-subtle" />
                    <p className="text-[12px] text-ink mt-2.5">这个条件下没有素材</p>
                    <p className="text-[10px] text-ink-subtle mt-1">换个目录 / 清空搜索，或直接上传一张新图</p>
                    <button
                      type="button"
                      onClick={() => setTab('upload')}
                      className="mt-3 inline-flex items-center gap-1.5 rounded-pill border border-flare/40 bg-flare/10 px-3 py-1.5 text-[11px] text-ink hover:border-flare/70 transition-colors"
                    >
                      <ImagePlus size={11} /> 上传新图
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="grid gap-2.5 grid-cols-3 sm:grid-cols-4 xl:grid-cols-5">
                      {rows.map((asset) => (
                        <PickerCard
                          key={asset.id}
                          asset={asset}
                          active={draft.includes(asset.id)}
                          order={draft.indexOf(asset.id) + 1}
                          directory={directoryLabel(tree, asset.kind, asset.category)}
                          onClick={() => toggle(asset.id)}
                        />
                      ))}
                    </div>
                    {total >= 100 && (
                      <p className="text-center text-[10px] text-ink-subtle mt-3">
                        最多显示最近 100 张 · 用搜索或按目录筛选可找到更老的图
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* 上传 Tab：目标目录 + 拖放 */
          <div className="flex-1 min-h-0 overflow-y-auto p-5 flex items-center justify-center">
            <div className="w-full max-w-lg space-y-3">
              <div className="rounded-card border border-line/70 bg-panel-2/25 p-3">
                <div className="flex items-center gap-2 mb-2.5">
                  <FolderOpen size={12} className="text-ink-subtle" />
                  <h4 className="text-[11px] font-medium text-ink">新图存到哪个目录</h4>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={uploadKind}
                    aria-label="上传一级目录"
                    onChange={(event) => {
                      setUploadKind(event.target.value as MediaKind)
                      setUploadCategory('')
                    }}
                    className={SELECT_CLASS}
                  >
                    {KIND_ORDER.map((kind) => (
                      <option key={kind} value={kind}>
                        {kindLabel(tree, kind)}
                      </option>
                    ))}
                  </select>
                  <select
                    value={uploadCategory}
                    aria-label="上传二级目录"
                    onChange={(event) =>
                      setUploadCategory(event.target.value === UNCATEGORIZED ? '' : event.target.value)
                    }
                    className={SELECT_CLASS}
                  >
                    <option value={UNCATEGORIZED}>未归类</option>
                    {uploadChildren.map((node) => (
                      <option key={node.key} value={node.key}>
                        {node.label}
                      </option>
                    ))}
                  </select>
                  <span className="text-[10px] text-ink-subtle">
                    目标：{kindLabel(tree, uploadKind)} / {categoryLabel(tree, uploadKind, uploadCategory)}
                  </span>
                </div>
              </div>

              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragOver(true)
                }}
                onDragLeave={(event) => {
                  event.preventDefault()
                  setDragOver(false)
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragOver(false)
                  if (event.dataTransfer.files?.length) void handleFiles(event.dataTransfer.files)
                }}
                className={cn(
                  'rounded-card border border-dashed p-6 transition-colors',
                  dragOver ? 'border-flare/70 bg-flare/10' : 'border-line-strong/70 bg-panel-2/25',
                )}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  multiple={slot.max > 1}
                  className="hidden"
                  onChange={(event) => {
                    if (event.target.files?.length) void handleFiles(event.target.files)
                    event.target.value = ''
                  }}
                />
                {uploading ? (
                  <div className="flex items-center justify-center gap-2 py-6 text-[12px] text-ink-muted">
                    <Loader2 size={14} className="animate-spin text-flare" />
                    上传中 {uploading.done}/{uploading.total}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => fileRef.current?.click()}
                    className="w-full flex flex-col items-center gap-2 py-6 text-center"
                  >
                    <UploadCloud size={24} className="text-ink-subtle" />
                    <span className="text-[12px] text-ink">拖图片到这里，或点击选择</span>
                    <span className="text-[10px] text-ink-subtle">
                      JPG / PNG / WEBP / GIF / AVIF · 单张 ≤ 20MB
                    </span>
                  </button>
                )}
              </div>
              <p className="text-[10px] text-ink-subtle leading-relaxed">
                上传成功后会自动进入待选，并把目录筛选切到刚上传的位置；点底部「确定」才写回「{slot.label}」。
              </p>
            </div>
          </div>
        )}

        {/* 底部：已选摘要 + 取消 / 确定 */}
        <footer className="flex-shrink-0 px-4 py-2.5 border-t border-line flex items-center gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[11px] text-ink-muted flex-shrink-0">已选</span>
            <span className={cn('font-mono text-[12px]', draft.length > 0 ? accent.text : 'text-ink-subtle')}>
              {draft.length}
            </span>
            <span className="text-[10px] text-ink-subtle">/ {slot.max}</span>
            {draft.length > 0 && (
              <div className="flex items-center gap-1 ml-1 overflow-hidden">
                {draft.slice(0, 6).map((id, index) => (
                  <span
                    key={id}
                    title={`已选素材 #${id}`}
                    className={cn(
                      'w-5 h-5 rounded-md flex items-center justify-center font-mono text-[9px] flex-shrink-0',
                      accent.bg,
                      accent.text,
                    )}
                  >
                    {index + 1}
                  </span>
                ))}
                {draft.length > 6 && <span className="text-[9px] text-ink-subtle">+{draft.length - 6}</span>}
              </div>
            )}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-pill border border-line/70 px-3.5 py-1.5 text-[11px] text-ink-muted hover:text-ink hover:border-line-strong transition-colors"
            >
              取消
            </button>
            <button
              type="button"
              onClick={confirm}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-pill border px-4 py-1.5 text-[11px] text-ink transition-colors',
                accent.border,
                accent.bg,
              )}
            >
              <Check size={12} /> 确定
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}

function PickerCard({
  asset,
  active,
  order,
  directory,
  onClick,
}: {
  asset: MediaAsset
  active: boolean
  order: number
  directory: string
  onClick: () => void
}) {
  const [broken, setBroken] = useState(false)
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={`选择 ${asset.original_name}`}
      title={`${asset.original_name} · ${directory}`}
      className={cn(
        'group rounded-xl border-2 overflow-hidden text-left transition-all',
        active ? 'border-flare shadow-glow' : 'border-line/60 hover:border-line-strong',
      )}
    >
      <div className="relative aspect-[4/3] bg-panel-2/60">
        {broken ? (
          <span className="w-full h-full flex flex-col items-center justify-center gap-1 text-ink-subtle">
            <ImageOff size={15} />
            <span className="text-[9px]">文件丢失</span>
          </span>
        ) : (
          <img
            src={asset.url}
            alt={asset.original_name}
            loading="lazy"
            onError={() => setBroken(true)}
            className="w-full h-full object-cover"
          />
        )}
        {active && (
          <span className="absolute top-1 right-1 w-4 h-4 rounded-full bg-flare text-brand-fg flex items-center justify-center">
            <Check size={10} />
          </span>
        )}
        {active && order > 0 && slotOrderBadge(order)}
      </div>
      <div className="px-2 py-1.5 bg-panel/60">
        <p className="text-[10px] text-ink truncate" title={asset.original_name}>
          {asset.original_name}
        </p>
        <p className="text-[9px] text-ink-subtle truncate" title={directory}>
          {directory}
        </p>
      </div>
    </button>
  )
}

function slotOrderBadge(order: number) {
  return (
    <span className="absolute bottom-1 left-1 rounded-md bg-scrim/75 backdrop-blur-md px-1.5 py-0.5 font-mono text-[9px] text-brand-fg">
      {order}
    </span>
  )
}
