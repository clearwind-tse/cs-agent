// -*- coding: utf-8 -*-
/**
 * StudioAssets — AI 创作 · 素材库（两级目录 + 本地磁盘存储）
 *
 * 目录体系：
 *   一级固定五类（商品图 / 风格参考 / 成图 / 参考图 / 其他），写死在后端 MEDIA_KINDS；
 *   二级由 media_categories 表维护，启动时 seed 预置项，用户可以自建 / 删除自定义目录。
 *   素材只存二级目录 key 不存目录 id，所以删目录只是把素材移到「未归类」，不会删图。
 *
 * 左侧目录树是筛选器，不是装饰：点一级看全类，点二级只看该目录，「未归类」也是可点的虚拟节点。
 * 上传默认落到当前选中的目录，避免每次传完还要再手动归一次类。
 *
 * 存储策略：文件落本地磁盘（backend/data/media），后端只存元数据。
 * 换 OSS 时后端换 media_store 实现即可，本组件的契约（url 字段）不变。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Folder,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  ImageOff,
  ImagePlus,
  Loader2,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'
import { cn } from '../utils'
import {
  UNCATEGORIZED,
  createMediaCategory,
  deleteMedia,
  deleteMediaCategory,
  getMediaCategories,
  getMediaStats,
  listMedia,
  updateMedia,
  uploadMedia,
  type MediaAsset,
  type MediaCategoryTree,
  type MediaKind,
  type MediaStats,
} from '../api'
import { useToast } from '../contexts/ToastContext'
import StudioImageProcessModal from './StudioImageProcessModal'
import {
  categoryLabel,
  childrenOf,
  directoryLabel,
  kindLabel,
  KIND_META,
  KIND_ORDER,
} from '../mediaCategories'
import {
  resetMediaKindLabel,
  setMediaKindLabel,
} from '../api'

const PAGE_SIZE = 24

interface Filter {
  kind: MediaKind | 'all'
  category: string // 'all' | UNCATEGORIZED | 二级目录 key
}

const ALL: Filter = { kind: 'all', category: 'all' }

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  const value = bytes / 1024 ** index
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`
}

/**
 * 后端返回的是不带时区的 UTC 字符串（项目里所有表都这样）。
 * 直接丢给 Date 会被当成本地时间，显示出来差 8 小时——这里显式补 Z。
 */
function parseUtc(value: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)
}

export default function StudioAssets() {
  const { showToast } = useToast()
  const [assets, setAssets] = useState<MediaAsset[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState<Filter>(ALL)
  const [tree, setTree] = useState<MediaCategoryTree | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(KIND_ORDER.map((kind) => [kind, true])),
  )
  const [keyword, setKeyword] = useState('')
  const [debounced, setDebounced] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stats, setStats] = useState<MediaStats | null>(null)

  const [uploadKind, setUploadKind] = useState<MediaKind>('product')
  const [uploadCategory, setUploadCategory] = useState<string>('')
  const [uploading, setUploading] = useState<{ done: number; total: number; percent: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState<MediaAsset | null>(null)
  // 单图即席处理：对一张已有图选动作 + 选端点，走图像网关，结果回写素材库
  const [processing, setProcessing] = useState<MediaAsset | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)

  // 新建二级目录：内联输入，按一级分组挂「+ 新建目录」
  const [newCatFor, setNewCatFor] = useState<MediaKind | null>(null)
  const [newCatLabel, setNewCatLabel] = useState('')
  const [creating, setCreating] = useState(false)

  // 改一级显示名：只改 label，key 保持不变
  const [editingKind, setEditingKind] = useState<MediaKind | null>(null)
  const [editKindLabel, setEditKindLabel] = useState('')
  const [savingKind, setSavingKind] = useState(false)

  // 预览弹层里的「移动到」
  const [moveKind, setMoveKind] = useState<MediaKind>('product')
  const [moveCategory, setMoveCategory] = useState<string>('')
  const [moving, setMoving] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(keyword.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [keyword])

  const loadTree = useCallback(async () => {
    try {
      setTree(await getMediaCategories())
    } catch {
      setTree(null)
    }
  }, [])

  const loadStats = useCallback(async () => {
    try {
      setStats(await getMediaStats())
    } catch {
      setStats(null)
    }
  }, [])

  const loadPage = useCallback(
    async (targetPage: number, append: boolean) => {
      if (append) setLoadingMore(true)
      else setLoading(true)
      setError(null)
      try {
        const data = await listMedia({
          kind: filter.kind,
          // 二级 key 只在一级内唯一，必须与具体 kind 同传；后端会拒绝「只给 category」
          category: filter.kind !== 'all' && filter.category !== 'all' ? filter.category : undefined,
          q: debounced || undefined,
          page: targetPage,
          page_size: PAGE_SIZE,
        })
        setAssets((prev) => (append ? [...prev, ...data.items] : data.items))
        setTotal(data.total)
        setPage(data.page)
      } catch (err: any) {
        setError(err?.response?.data?.detail?.message || err?.message || '加载失败')
        if (!append) setAssets([])
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [filter, debounced],
  )

  useEffect(() => {
    void loadPage(1, false)
  }, [loadPage])

  useEffect(() => {
    void loadStats()
    void loadTree()
  }, [loadStats, loadTree])

  const refreshAll = useCallback(
    () => Promise.all([loadPage(1, false), loadStats(), loadTree()]),
    [loadPage, loadStats, loadTree],
  )

  // 稳定的回调，避免即席处理弹窗的轮询 effect 每次渲染都重建定时器
  const onProcessCompleted = useCallback(() => { void refreshAll() }, [refreshAll])

  // 预览弹层：ESC 关闭 + 锁滚动
  useEffect(() => {
    if (!preview) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [preview])

  const selectNode = (next: Filter) => {
    setFilter(next)
    if (next.kind !== 'all') {
      setUploadKind(next.kind)
      setUploadCategory(next.category === 'all' || next.category === UNCATEGORIZED ? '' : next.category)
    }
  }

  const uncatCountOf = (kind: MediaKind) =>
    stats?.by_category.find((row) => row.kind === kind && row.category === UNCATEGORIZED)?.count ?? 0

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files).filter((file) => file.type.startsWith('image/') || file.type === '')
      if (list.length === 0) {
        showToast('只支持图片文件', 'error')
        return
      }

      setUploading({ done: 0, total: list.length, percent: 0 })
      let reused = 0
      let failed = 0
      for (let index = 0; index < list.length; index += 1) {
        const file = list[index]
        try {
          const result = await uploadMedia(file, {
            kind: uploadKind,
            category: uploadCategory || undefined,
            onProgress: (percent) => setUploading({ done: index, total: list.length, percent }),
          })
          if (result.reused) reused += 1
        } catch (err: any) {
          failed += 1
          const message = err?.response?.data?.detail?.message || err?.message || '上传失败'
          showToast(`${file.name}：${message}`, 'error')
        }
        setUploading({ done: index + 1, total: list.length, percent: 100 })
      }
      setUploading(null)

      const okCount = list.length - failed
      if (okCount > 0) {
        showToast(
          `${reused > 0 ? `已入库 ${okCount} 张（${reused} 张复用原文件）` : `已入库 ${okCount} 张`} · ${directoryLabel(tree, uploadKind, uploadCategory)}`,
          'success',
        )
      }
      await refreshAll()
    },
    [refreshAll, showToast, tree, uploadKind, uploadCategory],
  )

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    if (event.dataTransfer.files?.length) void handleFiles(event.dataTransfer.files)
  }

  const startRenameKind = (kind: MediaKind) => {
    setNewCatFor(null)
    setEditingKind(kind)
    setEditKindLabel(kindLabel(tree, kind))
  }

  const saveRenameKind = async (kind: MediaKind) => {
    const label = editKindLabel.trim()
    if (!label || label === kindLabel(tree, kind)) {
      setEditingKind(null)
      return
    }
    setSavingKind(true)
    try {
      const { tree: nextTree } = await setMediaKindLabel(kind, label)
      setTree(nextTree)
      setEditingKind(null)
      showToast(`一级目录已改名为「${label}」（key ${kind} 不变）`, 'success')
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '改名失败', 'error')
    } finally {
      setSavingKind(false)
    }
  }

  const resetRenameKind = async (kind: MediaKind) => {
    setSavingKind(true)
    try {
      const { tree: nextTree, item } = await resetMediaKindLabel(kind)
      setTree(nextTree)
      setEditingKind(null)
      showToast(`已恢复默认名「${item.label}」`, 'success')
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '恢复失败', 'error')
    } finally {
      setSavingKind(false)
    }
  }

  const handleCreateCategory = async (kind: MediaKind) => {
    const label = newCatLabel.trim()
    if (!label) return
    setCreating(true)
    try {
      const { tree: nextTree } = await createMediaCategory(kind, label)
      setTree(nextTree)
      setNewCatFor(null)
      setNewCatLabel('')
      showToast(`已在「${kindLabel(tree, kind)}」下新建目录：${label}`, 'success')
      void loadStats()
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '新建目录失败', 'error')
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteCategory = async (id: number, label: string) => {
    try {
      const { tree: nextTree, moved } = await deleteMediaCategory(id)
      setTree(nextTree)
      // 正看着这个目录时要退出，否则列表会停在已经不存在的筛选条件上
      const removedKey = tree?.groups.flatMap((group) => group.children).find((node) => node.id === id)?.key
      if (removedKey && filter.category === removedKey) selectNode({ kind: filter.kind as MediaKind, category: 'all' })
      showToast(`已删除目录「${label}」，${moved} 张素材移到未归类（文件保留）`, 'success')
      void refreshAll()
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '删除目录失败', 'error')
    }
  }

  const handleMove = async () => {
    if (!preview) return
    setMoving(true)
    try {
      const { item } = await updateMedia(preview.id, {
        kind: moveKind,
        category: moveCategory || UNCATEGORIZED,
      })
      setPreview(item)
      showToast(`已移动到「${directoryLabel(tree, moveKind, moveCategory)}」`, 'success')
      void refreshAll()
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '移动失败', 'error')
    } finally {
      setMoving(false)
    }
  }

  const handleDelete = async (asset: MediaAsset) => {
    try {
      await deleteMedia(asset.id)
      setPreview((current) => (current?.id === asset.id ? null : current))
      const nextPage = assets.length === 1 && page > 1 ? page - 1 : page
      await Promise.all([loadPage(nextPage, false), loadStats(), loadTree()])
      showToast('已删除', 'success')
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '删除失败', 'error')
    }
  }

  const copyLink = async (asset: MediaAsset) => {
    const absolute = `${window.location.origin}${asset.url}`
    try {
      await navigator.clipboard.writeText(absolute)
      showToast('直链已复制', 'success')
    } catch {
      showToast(absolute, 'info')
    }
  }

  const openPreview = (asset: MediaAsset) => {
    setPreview(asset)
    setMoveKind(asset.kind)
    setMoveCategory(asset.category || '')
  }

  const openProcess = (asset: MediaAsset) => {
    setPreview(null)
    setProcessing(asset)
  }

  const currentLabel = useMemo(() => {
    if (filter.kind === 'all') return '全部素材'
    if (filter.category === 'all') return kindLabel(tree, filter.kind)
    return directoryLabel(tree, filter.kind, filter.category)
  }, [filter, tree])

  const usedPercent = stats && stats.max_mb > 0 ? Math.min(100, (stats.total_size / (stats.max_mb * 1024 * 1024)) * 100) : 0
  const moveChildren = childrenOf(tree, moveKind)

  return (
    <div className="px-5 py-5 flex gap-4 items-start">
      {/* 左侧：两级目录树 */}
      <aside className="w-52 flex-shrink-0 rounded-card border border-line/70 bg-panel/40 p-2.5 lg:sticky lg:top-0">
        <div className="flex items-center gap-1.5 px-1 pb-2 mb-1 border-b border-line/60">
          <FolderOpen size={12} className="text-ink-subtle" />
          <h3 className="text-[11px] font-medium text-ink">目录</h3>
          <span className="ml-auto font-mono text-[9px] text-ink-subtle">{stats?.total ?? total}</span>
        </div>

        <button
          type="button"
          onClick={() => selectNode(ALL)}
          className={cn(
            'w-full flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] transition-colors',
            filter.kind === 'all' ? 'bg-flare/15 text-ink' : 'text-ink-muted hover:bg-panel-2/70 hover:text-ink',
          )}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-flare/70 flex-shrink-0" />
          全部素材
          <span className="ml-auto font-mono text-[9px] text-ink-subtle">{stats?.total ?? total}</span>
        </button>

        <div className="mt-1 space-y-0.5 max-h-[62vh] overflow-y-auto pr-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {KIND_ORDER.map((kind) => {
            const group = tree?.groups.find((entry) => entry.kind === kind)
            const isOpen = expanded[kind] ?? true
            const activeKind = filter.kind === kind && filter.category === 'all'
            return (
              <div key={kind}>
                {editingKind === kind ? (
                  <div className="ml-4 py-1 pr-1 space-y-1">
                    <div className="flex items-center gap-1">
                      <input
                        autoFocus
                        value={editKindLabel}
                        maxLength={20}
                        aria-label={`${kind} 的新显示名`}
                        onFocus={(event) => event.target.select()}
                        onChange={(event) => setEditKindLabel(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void saveRenameKind(kind)
                          if (event.key === 'Escape') setEditingKind(null)
                        }}
                        className="min-w-0 flex-1 rounded-md border border-flare/40 bg-panel/70 px-1.5 py-1 text-[11px] text-ink focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => void saveRenameKind(kind)}
                        disabled={savingKind || !editKindLabel.trim()}
                        aria-label="保存一级目录名"
                        className="p-1 rounded text-ok hover:bg-ok/10 disabled:opacity-40"
                      >
                        {savingKind ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingKind(null)}
                        aria-label="取消改名"
                        className="p-1 rounded text-ink-subtle hover:text-ink"
                      >
                        <X size={11} />
                      </button>
                    </div>
                    {group?.custom && (
                      <button
                        type="button"
                        onClick={() => void resetRenameKind(kind)}
                        className="text-[9px] text-ink-subtle hover:text-ink transition-colors"
                      >
                        恢复默认名「{group.default_label}」
                      </button>
                    )}
                    <p className="font-mono text-[9px] text-ink-subtle">key {kind} 不变</p>
                  </div>
                ) : (
                  <div className="group/kind flex items-center" onDoubleClick={() => startRenameKind(kind)}>
                    <button
                      type="button"
                      onClick={() => setExpanded((prev) => ({ ...prev, [kind]: !isOpen }))}
                      aria-label={isOpen ? `收起${kindLabel(tree, kind)}` : `展开${kindLabel(tree, kind)}`}
                      className="p-1 text-ink-subtle hover:text-ink transition-colors"
                    >
                      {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                    </button>
                    <button
                      type="button"
                      onClick={() => selectNode({ kind, category: 'all' })}
                      title={`双击可改名 · key ${kind}`}
                      className={cn(
                        'flex-1 flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-[11px] text-left transition-colors',
                        activeKind ? 'bg-flare/15 text-ink' : 'text-ink-muted hover:bg-panel-2/70 hover:text-ink',
                      )}
                    >
                      {isOpen ? <FolderOpen size={11} className="flex-shrink-0" /> : <Folder size={11} className="flex-shrink-0" />}
                      <span className="truncate">{kindLabel(tree, kind)}</span>
                      {group?.custom && <span className="w-1 h-1 rounded-full bg-flare/70 flex-shrink-0" title="已自定义显示名" />}
                      <span className="ml-auto font-mono text-[9px] text-ink-subtle">{group?.count ?? 0}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => startRenameKind(kind)}
                      aria-label={`重命名 ${kindLabel(tree, kind)}`}
                      title="改一级目录显示名"
                      className="p-0.5 mr-0.5 text-ink-subtle opacity-0 group-hover/kind:opacity-100 hover:text-flare transition-opacity"
                    >
                      <Pencil size={10} />
                    </button>
                  </div>
                )}

                {isOpen && (
                  <div className="ml-3.5 pl-2 border-l border-line/60 space-y-0.5 mt-0.5">
                    {(group?.children ?? []).map((node) => {
                      const active = filter.kind === kind && filter.category === node.key
                      return (
                        <div key={node.key} className="group/cat flex items-center">
                          <button
                            type="button"
                            onClick={() => selectNode({ kind, category: node.key })}
                            className={cn(
                              'flex-1 flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-left transition-colors',
                              active ? 'bg-flare/15 text-ink' : 'text-ink-subtle hover:bg-panel-2/70 hover:text-ink',
                            )}
                          >
                            <span className="truncate">{node.label}</span>
                            <span className="ml-auto font-mono text-[9px] opacity-70">{node.count}</span>
                          </button>
                          {!node.builtin && (
                            <button
                              type="button"
                              onClick={() => void handleDeleteCategory(node.id, node.label)}
                              aria-label={`删除目录 ${node.label}`}
                              title="删除目录（素材移到未归类，文件保留）"
                              className="p-0.5 mr-0.5 text-ink-subtle opacity-0 group-hover/cat:opacity-100 hover:text-bad transition-opacity"
                            >
                              <Trash2 size={10} />
                            </button>
                          )}
                        </div>
                      )
                    })}

                    <button
                      type="button"
                      onClick={() => selectNode({ kind, category: UNCATEGORIZED })}
                      className={cn(
                        'w-full flex items-center rounded-md px-1.5 py-1 text-[10px] text-left transition-colors',
                        filter.kind === kind && filter.category === UNCATEGORIZED
                          ? 'bg-flare/15 text-ink'
                          : 'text-ink-subtle hover:bg-panel-2/70 hover:text-ink',
                      )}
                    >
                      未归类
                      <span className="ml-auto font-mono text-[9px] opacity-70">{uncatCountOf(kind)}</span>
                    </button>

                    {newCatFor === kind ? (
                      <div className="flex items-center gap-1 pt-0.5">
                        <input
                          autoFocus
                          value={newCatLabel}
                          maxLength={20}
                          onChange={(event) => setNewCatLabel(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') void handleCreateCategory(kind)
                            if (event.key === 'Escape') {
                              setNewCatFor(null)
                              setNewCatLabel('')
                            }
                          }}
                          placeholder="目录名"
                          className="min-w-0 flex-1 rounded-md border border-flare/40 bg-panel/70 px-1.5 py-1 text-[10px] text-ink placeholder:text-ink-subtle focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => void handleCreateCategory(kind)}
                          disabled={creating || !newCatLabel.trim()}
                          aria-label="确认新建目录"
                          className="p-1 rounded text-ok hover:bg-ok/10 disabled:opacity-40"
                        >
                          {creating ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setNewCatFor(null)
                            setNewCatLabel('')
                          }}
                          aria-label="取消新建目录"
                          className="p-1 rounded text-ink-subtle hover:text-ink"
                        >
                          <X size={11} />
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          setNewCatFor(kind)
                          setNewCatLabel('')
                        }}
                        className="w-full flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-ink-subtle hover:text-flare transition-colors"
                      >
                        <Plus size={10} /> 新建目录
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <p className="px-1 pt-2 mt-1.5 border-t border-line/60 text-[9px] text-ink-subtle leading-relaxed">
          双击一级目录或点铅笔可改显示名（key 不变）；二级目录可自建，删除只把素材移到「未归类」，不会删文件。
        </p>
      </aside>

      {/* 右侧：存储 + 上传 + 列表 */}
      <div className="flex-1 min-w-0 space-y-4">
        <section className="grid gap-3 xl:grid-cols-[1fr_320px]">
          <div className="rounded-card border border-line/70 bg-panel/50 p-4">
            <div className="flex items-center gap-2">
              <HardDrive size={14} className="text-ink-subtle" />
              <h3 className="text-[12px] font-medium text-ink">存储</h3>
              <span className="font-mono text-[10px] text-ink-subtle">本地磁盘 · backend/data/media</span>
            </div>
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="素材" value={String(stats?.total ?? total)} unit="张" />
              <Stat label="占用" value={formatBytes(stats?.total_size ?? 0)} />
              <Stat label="磁盘文件" value={String(stats?.disk_count ?? 0)} unit="个" />
              <Stat label="单文件上限" value={String(stats?.max_mb ?? 20)} unit="MB" />
            </div>
            <div className="mt-3">
              <div className="h-1.5 rounded-pill bg-panel-2 overflow-hidden">
                <div className="h-full rounded-pill bg-flare/70 transition-all" style={{ width: `${Math.max(usedPercent, 1)}%` }} />
              </div>
              <p className="font-mono text-[10px] text-ink-subtle mt-1.5">
                {formatBytes(stats?.total_size ?? 0)} 已用 · 上限按单文件计，总量未设限
                {stats && stats.disk_count !== stats.total ? ' · 磁盘与记录不一致，可跑一致性检查' : ''}
              </p>
            </div>
          </div>

          {/* 上传区：目标目录可改，默认跟随左侧当前选中目录 */}
          <div
            onDragEnter={(event) => {
              event.preventDefault()
              dragDepth.current += 1
              setDragging(true)
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              event.preventDefault()
              dragDepth.current = Math.max(0, dragDepth.current - 1)
              if (dragDepth.current === 0) setDragging(false)
            }}
            onDrop={handleDrop}
            className={cn(
              'rounded-card border border-dashed p-4 transition-colors',
              dragging ? 'border-flare/70 bg-flare/10' : 'border-line-strong/70 bg-panel-2/30',
            )}
          >
            <div className="flex items-center gap-2 mb-2.5">
              <UploadCloud size={14} className={dragging ? 'text-flare' : 'text-ink-subtle'} />
              <h3 className="text-[12px] font-medium text-ink">上传到素材库</h3>
            </div>

            <div className="flex flex-wrap items-center gap-1.5 mb-2">
              {KIND_ORDER.map((entry) => (
                <button
                  key={entry}
                  type="button"
                  onClick={() => {
                    setUploadKind(entry)
                    setUploadCategory('')
                  }}
                  className={cn(
                    'rounded-pill border px-2 py-0.5 text-[10px] transition-colors',
                    uploadKind === entry
                      ? 'border-flare/50 bg-flare/15 text-ink'
                      : 'border-line/70 text-ink-subtle hover:text-ink hover:border-line-strong',
                  )}
                >
                  {kindLabel(tree, entry)}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1.5 mb-2.5">
              <span className="text-[10px] text-ink-subtle flex-shrink-0">二级目录</span>
              <select
                value={uploadCategory}
                aria-label="上传到的二级目录"
                onChange={(event) =>
                  setUploadCategory(event.target.value === UNCATEGORIZED ? '' : event.target.value)
                }
                className="min-w-0 flex-1 rounded-lg border border-line/70 bg-panel/70 px-2 py-1 text-[10px] text-ink-muted focus:border-flare/50 focus:outline-none"
              >
                <option value={UNCATEGORIZED}>未归类</option>
                {childrenOf(tree, uploadKind).map((node) => (
                  <option key={node.key} value={node.key}>
                    {node.label}
                  </option>
                ))}
              </select>
            </div>

            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(event) => {
                if (event.target.files?.length) void handleFiles(event.target.files)
                event.target.value = ''
              }}
            />

            {uploading ? (
              <div className="rounded-xl border border-line/60 bg-panel/60 px-3 py-2.5">
                <div className="flex items-center gap-2 text-[11px] text-ink-muted">
                  <Loader2 size={12} className="animate-spin text-flare" />
                  上传中 {uploading.done}/{uploading.total}
                  <span className="ml-auto font-mono text-[10px] text-ink-subtle">{uploading.percent}%</span>
                </div>
                <div className="h-1 rounded-pill bg-panel-2 mt-2 overflow-hidden">
                  <div
                    className="h-full bg-flare transition-all"
                    style={{ width: `${Math.max(4, ((uploading.done + uploading.percent / 100) / uploading.total) * 100)}%` }}
                  />
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="w-full rounded-xl border border-line/60 bg-panel/50 px-3 py-3 text-center hover:border-flare/40 hover:bg-panel/80 transition-colors"
              >
                <ImagePlus size={16} className="mx-auto text-ink-subtle" />
                <span className="block text-[11px] text-ink-muted mt-1">拖图片到这里，或点击选择</span>
                <span className="block font-mono text-[9px] text-ink-subtle mt-0.5">
                  存入 {directoryLabel(tree, uploadKind, uploadCategory)} · 单张 ≤ {stats?.max_mb ?? 20}MB
                </span>
              </button>
            )}
          </div>
        </section>

        {/* 当前目录 + 搜索 */}
        <section className="flex flex-wrap items-center gap-2">
          <Folder size={13} className="text-ink-subtle" />
          <span className="text-[10px] text-ink-subtle">当前目录</span>
          <span className="rounded-pill border border-flare/35 bg-flare/10 px-2.5 py-0.5 text-[11px] text-ink">
            {currentLabel}
          </span>
          <span className="font-mono text-[10px] text-ink-subtle">{total} 张</span>
          <div className="ml-auto relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜文件名 / 备注"
              aria-label="搜索素材"
              className="w-52 rounded-pill border border-line/70 bg-panel/60 pl-7 pr-3 py-1 text-[11px] text-ink placeholder:text-ink-subtle focus:border-flare/50 focus:outline-none"
            />
          </div>
        </section>

        {/* 网格 */}
        {error ? (
          <div className="rounded-card border border-bad/30 bg-bad/10 px-4 py-6 text-center">
            <AlertTriangle size={18} className="mx-auto text-bad" />
            <p className="text-[12px] text-ink mt-2">素材加载失败</p>
            <p className="text-[11px] text-ink-subtle mt-1">{error}</p>
            <button
              type="button"
              onClick={() => void loadPage(1, false)}
              className="mt-3 rounded-pill border border-line-strong px-3 py-1 text-[11px] text-ink hover:border-flare/50 transition-colors"
            >
              重试
            </button>
          </div>
        ) : loading ? (
          <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="rounded-card border border-line/60 bg-panel-2/40 overflow-hidden animate-pulse">
                <div className="aspect-[4/3] bg-panel-2/70" />
                <div className="px-3 py-2 space-y-1.5">
                  <div className="h-2 w-2/3 rounded bg-panel-3/70" />
                  <div className="h-2 w-1/3 rounded bg-panel-3/50" />
                </div>
              </div>
            ))}
          </div>
        ) : assets.length === 0 ? (
          <div className="rounded-card border border-line/70 bg-panel-2/25 px-6 py-12 text-center">
            <ImageIcon size={22} className="mx-auto text-ink-subtle" />
            <p className="text-[13px] text-ink mt-2.5">
              {debounced || filter.kind !== 'all' ? '这个目录下没有素材' : '素材库还是空的'}
            </p>
            <p className="text-[11px] text-ink-subtle mt-1">
              {debounced || filter.kind !== 'all'
                ? '换个目录、清空搜索，或直接在上方上传到当前目录'
                : '先把商品图传上来：商品套图、SKU 替换、精修都从这里取图'}
            </p>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="mt-4 inline-flex items-center gap-1.5 rounded-pill border border-flare/40 bg-flare/10 px-3.5 py-1.5 text-[11px] text-ink hover:border-flare/60 transition-colors"
            >
              <ImagePlus size={12} /> 选择图片
            </button>
          </div>
        ) : (
          <>
            <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-4 auto-rows-fr">
              {assets.map((asset) => (
                <AssetCard
                  key={asset.id}
                  asset={asset}
                  directory={directoryLabel(tree, asset.kind, asset.category)}
                  kindText={kindLabel(tree, asset.kind)}
                  onOpen={() => openPreview(asset)}
                  onProcess={() => openProcess(asset)}
                  onDelete={() => void handleDelete(asset)}
                  onCopy={() => void copyLink(asset)}
                />
              ))}
            </div>
            <div className="flex items-center justify-between pt-1">
              <span className="font-mono text-[10px] text-ink-subtle">
                已显示 {assets.length} / {total}
              </span>
              {assets.length < total && (
                <button
                  type="button"
                  onClick={() => void loadPage(page + 1, true)}
                  disabled={loadingMore}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-line/70 px-3 py-1 text-[11px] text-ink-muted hover:text-ink hover:border-flare/40 transition-colors disabled:opacity-60"
                >
                  {loadingMore && <Loader2 size={11} className="animate-spin" />}
                  加载更多
                </button>
              )}
            </div>
          </>
        )}
      </div>

      {preview && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`预览 ${preview.original_name}`}
          className="fixed inset-0 z-50 bg-scrim/70 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={() => setPreview(null)}
        >
          <div
            className="max-w-4xl w-full rounded-card border border-line bg-panel shadow-glass overflow-hidden"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="h-12 px-4 flex items-center gap-3 border-b border-line">
              <span className={cn('rounded-pill border px-2 py-0.5 text-[10px]', KIND_META[preview.kind].chip)}>
                {kindLabel(tree, preview.kind)}
              </span>
              <span className="rounded-pill border border-line/70 bg-panel-2/60 px-2 py-0.5 text-[10px] text-ink-muted">
                {categoryLabel(tree, preview.kind, preview.category)}
              </span>
              <span className="text-[12px] text-ink truncate">{preview.original_name}</span>
              <button
                type="button"
                onClick={() => setPreview(null)}
                aria-label="关闭预览"
                className="ml-auto p-1.5 rounded-lg text-ink-subtle hover:text-ink hover:bg-panel-2 transition-colors"
              >
                <X size={16} />
              </button>
            </header>
            <div className="bg-canvas/60 flex items-center justify-center max-h-[58vh] overflow-hidden">
              <img src={preview.url} alt={preview.original_name} className="max-h-[58vh] w-auto object-contain" />
            </div>

            {/* 移动到别的目录：一级改了会清掉二级，后端已做校验 */}
            <div className="px-4 py-2.5 flex flex-wrap items-center gap-2 border-t border-line/60 bg-panel-2/25">
              <FolderOpen size={12} className="text-ink-subtle" />
              <span className="text-[10px] text-ink-subtle">移动到</span>
              <select
                value={moveKind}
                aria-label="移动到一级目录"
                onChange={(event) => {
                  setMoveKind(event.target.value as MediaKind)
                  setMoveCategory('')
                }}
                className="rounded-lg border border-line/70 bg-panel/70 px-2 py-1 text-[10px] text-ink-muted focus:border-flare/50 focus:outline-none"
              >
                {KIND_ORDER.map((kind) => (
                  <option key={kind} value={kind}>
                    {kindLabel(tree, kind)}
                  </option>
                ))}
              </select>
              <select
                value={moveCategory}
                aria-label="移动到二级目录"
                onChange={(event) =>
                  setMoveCategory(event.target.value === UNCATEGORIZED ? '' : event.target.value)
                }
                className="rounded-lg border border-line/70 bg-panel/70 px-2 py-1 text-[10px] text-ink-muted focus:border-flare/50 focus:outline-none"
              >
                <option value={UNCATEGORIZED}>未归类</option>
                {moveChildren.map((node) => (
                  <option key={node.key} value={node.key}>
                    {node.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void handleMove()}
                disabled={moving}
                className="inline-flex items-center gap-1 rounded-pill border border-flare/40 bg-flare/10 px-2.5 py-1 text-[10px] text-ink hover:border-flare/70 transition-colors disabled:opacity-60"
              >
                {moving ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
                应用
              </button>
            </div>

            <footer className="px-4 py-3 flex flex-wrap items-center gap-3 border-t border-line">
              <span className="font-mono text-[10px] text-ink-subtle">
                {preview.width && preview.height ? `${preview.width}×${preview.height}` : '尺寸未知'} · {formatBytes(preview.size)} ·{' '}
                {preview.source === 'generated' ? '生成' : '上传'}
                {preview.created_at ? ` · ${parseUtc(preview.created_at).toLocaleString('zh-CN')}` : ''}
              </span>
              {preview.note && <span className="text-[11px] text-ink-muted truncate">{preview.note}</span>}
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  data-testid="asset-ai-process"
                  onClick={() => openProcess(preview)}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-flare/40 bg-flare/10 px-3 py-1 text-[11px] text-ink hover:border-flare/70 transition-colors"
                >
                  <Sparkles size={11} /> AI 处理这张图
                </button>
                <button
                  type="button"
                  onClick={() => void copyLink(preview)}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-line/70 px-3 py-1 text-[11px] text-ink-muted hover:text-ink hover:border-line-strong transition-colors"
                >
                  <Copy size={11} /> 复制直链
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete(preview)}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-bad/40 bg-bad/10 px-3 py-1 text-[11px] text-bad hover:border-bad/70 transition-colors"
                >
                  <Trash2 size={11} /> 删除
                </button>
              </div>
            </footer>
          </div>
        </div>
      )}

      {processing && (
        <StudioImageProcessModal
          asset={processing}
          onClose={() => setProcessing(null)}
          onCompleted={onProcessCompleted}
        />
      )}
    </div>
  )
}

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div>
      <p className="font-mono text-[9px] text-ink-subtle uppercase tracking-wider">{label}</p>
      <p className="text-[15px] text-ink leading-tight mt-0.5">
        {value}
        {unit && <span className="text-[10px] text-ink-subtle ml-1">{unit}</span>}
      </p>
    </div>
  )
}

function AssetCard({
  asset,
  directory,
  kindText,
  onOpen,
  onProcess,
  onDelete,
  onCopy,
}: {
  asset: MediaAsset
  directory: string
  kindText: string
  onOpen: () => void
  onProcess: () => void
  onDelete: () => void
  onCopy: () => void
}) {
  // 文件被手工删掉 / 迁移目录后，直链会 404 —— 与其显示破图，不如说清是文件丢了
  const [broken, setBroken] = useState(false)

  return (
    <div className="group rounded-card border border-line/60 bg-panel/60 overflow-hidden hover:border-flare/40 transition-colors h-full flex flex-col">
      <div className="relative aspect-[4/3] bg-panel-2/60">
        <button type="button" onClick={onOpen} className="absolute inset-0" aria-label={`预览 ${asset.original_name}`}>
          {broken ? (
            <span className="w-full h-full flex flex-col items-center justify-center gap-1 text-ink-subtle">
              <ImageOff size={16} />
              <span className="text-[10px]">文件丢失</span>
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
        </button>
        <span className={cn('absolute left-2 top-2 rounded-pill border px-1.5 py-0.5 text-[9px] backdrop-blur-md', KIND_META[asset.kind].chip)}>
          {kindText}
        </span>
        <div className="absolute right-1.5 top-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            data-testid="asset-ai-process-card"
            onClick={onProcess}
            aria-label="AI 处理这张图"
            title="单图即席处理：选动作 + 选端点"
            className="p-1.5 rounded-lg bg-scrim/60 text-ink-muted hover:text-flare backdrop-blur-md transition-colors"
          >
            <Sparkles size={12} />
          </button>
          <button
            type="button"
            onClick={onCopy}
            aria-label="复制直链"
            title="复制直链"
            className="p-1.5 rounded-lg bg-scrim/60 text-ink-muted hover:text-ink backdrop-blur-md transition-colors"
          >
            <Copy size={12} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label="删除素材"
            title="删除"
            className="p-1.5 rounded-lg bg-scrim/60 text-ink-muted hover:text-bad backdrop-blur-md transition-colors"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>
      <div className="px-2.5 py-2">
        <p className="text-[11px] text-ink truncate" title={asset.original_name}>
          {asset.original_name}
        </p>
        <p className="text-[9px] text-ink-subtle truncate mt-0.5" title={directory}>
          {directory}
        </p>
        <p className="font-mono text-[9px] text-ink-subtle mt-0.5 truncate">
          {asset.width && asset.height ? `${asset.width}×${asset.height} · ` : ''}
          {formatBytes(asset.size)}
          {asset.source === 'generated' ? ' · 生成' : ''}
        </p>
      </div>
    </div>
  )
}
