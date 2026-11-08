import { useState, useEffect } from 'react'

/** 将秒级时间戳转为 datetime-local 本地时间字符串（YYYY-MM-DDTHH:MM） */
function tsToLocalInput(ts?: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 将 datetime-local 本地时间字符串转为秒级时间戳（本地时区语义，与后端 utcfromtimestamp 对 epoch 的处理一致） */
function localInputToTs(v: string): number | undefined {
  if (!v) return undefined
  const ms = new Date(v).getTime()
  if (Number.isNaN(ms)) return undefined
  return Math.floor(ms / 1000)
}

interface Props {
  /** 当前开始时间（秒级时间戳），用于回填输入框 */
  startTime?: number | null
  /** 当前结束时间（秒级时间戳），用于回填输入框 */
  endTime?: number | null
  /** 时间改变回调：start/end 为秒级时间戳，未设置时传 undefined */
  onChange: (start?: number, end?: number) => void
  /** 是否每次改动立即触发 onChange。默认 false：需点"应用" */
  immediate?: boolean
  /** 容器额外类名 */
  className?: string
}

/**
 * 时间区间筛选控件（开始 ~ 结束），用于清洗/质检/知识提炼列表按创建时间过滤。
 */
export default function TimeRangeFilter({ startTime, endTime, onChange, immediate, className }: Props) {
  const [start, setStart] = useState(tsToLocalInput(startTime))
  const [end, setEnd] = useState(tsToLocalInput(endTime))

  useEffect(() => {
    setStart(tsToLocalInput(startTime))
    setEnd(tsToLocalInput(endTime))
  }, [startTime, endTime])

  const apply = () => onChange(localInputToTs(start), localInputToTs(end))

  const handleStart = (v: string) => {
    setStart(v)
    if (immediate) onChange(localInputToTs(v), localInputToTs(end))
  }
  const handleEnd = (v: string) => {
    setEnd(v)
    if (immediate) onChange(localInputToTs(start), localInputToTs(v))
  }

  const hasValue = !!start || !!end

  return (
    <div className={`flex items-center gap-2 flex-wrap text-sm ${className ?? ''}`}>
      <span className="text-ink-subtle">时间：</span>
      <input
        type="datetime-local"
        value={start}
        onChange={(e) => handleStart(e.target.value)}
        className="bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-sm text-ink focus:outline-none"
        title="开始时间（本地时区，按记录创建时间过滤）"
      />
      <span className="text-ink-subtle">~</span>
      <input
        type="datetime-local"
        value={end}
        onChange={(e) => handleEnd(e.target.value)}
        className="bg-panel-2 border border-line-strong rounded-lg px-3 py-1.5 text-sm text-ink focus:outline-none"
        title="结束时间（本地时区，按记录创建时间过滤）"
      />
      {!immediate && (
        <button
          onClick={apply}
          className="px-3 py-1.5 bg-iris text-ink rounded-lg hover:bg-iris/80 text-sm"
        >
          应用
        </button>
      )}
      {hasValue && (
        <button
          onClick={() => { setStart(''); setEnd(''); onChange(undefined, undefined) }}
          className="px-2 py-1 text-ink-muted hover:text-ink"
          title="清除时间筛选"
        >
          清除
        </button>
      )}
    </div>
  )
}
