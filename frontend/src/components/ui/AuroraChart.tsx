import { useEffect, useState, type ReactNode } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useTheme } from '../../contexts/ThemeContext'
import { cn } from '../../utils'

/** 图表颜色全部取自设计令牌，随明暗主题自动翻转。 */
export interface AuroraColors {
  mint: string
  iris: string
  flare: string
  ok: string
  warn: string
  bad: string
  info: string
  subtle: string
  line: string
  panel: string
  ink: string
}

const FALLBACK: AuroraColors = {
  mint: 'rgb(110 242 197)',
  iris: 'rgb(139 123 255)',
  flare: 'rgb(255 92 168)',
  ok: 'rgb(110 242 197)',
  warn: 'rgb(255 196 107)',
  bad: 'rgb(255 107 138)',
  info: 'rgb(169 155 255)',
  subtle: 'rgb(131 126 174)',
  line: 'rgb(46 43 94)',
  panel: 'rgb(30 28 64)',
  ink: 'rgb(244 242 255)',
}

const SERIES = ['mint', 'iris', 'flare', 'info', 'warn', 'ok', 'bad'] as const

export function useAuroraColors(): AuroraColors {
  const { resolvedTheme } = useTheme()
  const [colors, setColors] = useState<AuroraColors>(FALLBACK)

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const style = getComputedStyle(document.documentElement)
      const read = (name: string, fallback: string) => {
        const raw = style.getPropertyValue(name).trim()
        return raw ? `rgb(${raw})` : fallback
      }
      setColors({
        mint: read('--c-mint', FALLBACK.mint),
        iris: read('--c-iris', FALLBACK.iris),
        flare: read('--c-flare', FALLBACK.flare),
        ok: read('--c-ok', FALLBACK.ok),
        warn: read('--c-warn', FALLBACK.warn),
        bad: read('--c-bad', FALLBACK.bad),
        info: read('--c-info', FALLBACK.info),
        subtle: read('--c-ink-subtle', FALLBACK.subtle),
        line: read('--c-line', FALLBACK.line),
        panel: read('--c-panel-2', FALLBACK.panel),
        ink: read('--c-ink', FALLBACK.ink),
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [resolvedTheme])

  return colors
}

export interface ChartDatum {
  name: string
  value: number
  color?: string
}

interface ChartFrameProps {
  title: string
  subtitle?: string
  aside?: ReactNode
  children: ReactNode
  className?: string
}

/** 统一的图表玻璃容器，标题区 + 固定高度内容区。 */
export function ChartFrame({ title, subtitle, aside, children, className }: ChartFrameProps) {
  return (
    <section className={cn('chart-panel p-5', className)}>
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold tracking-wide text-ink">{title}</h3>
          {subtitle && <p className="mt-1 text-xs text-ink-subtle">{subtitle}</p>}
        </div>
        {aside}
      </header>
      {children}
    </section>
  )
}

function TooltipContent({ active, payload, unit = '' }: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number | string; color?: string }>
  unit?: string
}) {
  if (!active || !payload?.length) return null
  const row = payload[0]
  return (
    <div className="chart-tooltip">
      <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: row.color }} />
      <span className="text-ink-muted">{row.name ?? ''}</span>
      <span className="ml-2 font-mono font-semibold text-ink">{row.value}{unit}</span>
    </div>
  )
}

/** 环形占比图，适合状态分布（待审核 / 已通过 / 已拒绝…）。 */
export function StatusDonut({
  data,
  height = 190,
  centerLabel,
  unit = '条',
}: {
  data: ChartDatum[]
  height?: number
  centerLabel?: string
  unit?: string
}) {
  const colors = useAuroraColors()
  const total = data.reduce((sum, d) => sum + d.value, 0)
  const withColor = data.map((d, i) => ({
    ...d,
    color: d.color ?? colors[SERIES[i % SERIES.length]],
  }))

  return (
    <div className="flex flex-wrap items-center gap-4" style={{ minHeight: height }}>
      <div className="relative shrink-0" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={withColor}
              dataKey="value"
              nameKey="name"
              innerRadius="66%"
              outerRadius="88%"
              paddingAngle={total > 0 ? 3 : 0}
              stroke="none"
              isAnimationActive={false}
            >
              {withColor.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
            </Pie>
            <Tooltip content={<TooltipContent unit={unit} />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-display text-2xl font-bold leading-none text-ink tabular-nums">{total}</span>
          <span className="mt-1 text-[10px] uppercase tracking-[0.16em] text-ink-subtle">
            {centerLabel ?? '总计'}
          </span>
        </div>
      </div>
      <ul className="min-w-[110px] max-w-[190px] flex-1 space-y-2">
        {withColor.map((d) => (
          <li key={d.name} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-2 text-ink-muted">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: d.color }} />
              <span className="truncate">{d.name}</span>
            </span>
            <span className="font-mono font-semibold text-ink tabular-nums">{d.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * 中文长标签友好的水平条形图（纯 DOM，不依赖容器测量）。
 * 用于业务分类 / 违规类型 / 维度分布等 Record<string, number> 字段。
 */
export function CategoryBars({
  data,
  unit = '',
  max = 8,
  emptyHint = '暂无分布数据',
}: {
  data: ChartDatum[]
  unit?: string
  max?: number
  emptyHint?: string
}) {
  const colors = useAuroraColors()
  const sorted = [...data].filter((d) => d.value > 0).sort((a, b) => b.value - a.value).slice(0, max)
  const peak = sorted.length ? Math.max(...sorted.map((d) => d.value)) : 0
  const total = sorted.reduce((sum, d) => sum + d.value, 0)

  if (!sorted.length) {
    return <p className="py-8 text-center text-xs text-ink-subtle">{emptyHint}</p>
  }

  return (
    <ul className="space-y-3">
      {sorted.map((d, i) => {
        const color = d.color ?? colors[SERIES[i % SERIES.length]]
        const pct = total > 0 ? (d.value / total) * 100 : 0
        return (
          <li key={d.name}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-xs">
              <span className="truncate text-ink-muted" title={d.name}>{d.name}</span>
              <span className="shrink-0 font-mono font-semibold text-ink tabular-nums">
                {d.value}{unit}
                <span className="ml-1.5 text-ink-subtle">{pct.toFixed(0)}%</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-line/60">
              <div
                className="h-full rounded-full transition-[width] duration-700 ease-out"
                style={{
                  width: `${peak > 0 ? (d.value / peak) * 100 : 0}%`,
                  background: `linear-gradient(90deg, ${color}, ${colors.iris})`,
                }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** 纵向柱状图，适合分数分布 / 逐题得分等有序数值。 */
export function ScoreHistogram({
  data,
  height = 190,
  unit = '',
  color,
}: {
  data: ChartDatum[]
  height?: number
  unit?: string
  color?: string
}) {
  const colors = useAuroraColors()
  const fill = color ?? colors.iris

  if (!data.length) {
    return <p className="py-8 text-center text-xs text-ink-subtle">暂无分布数据</p>
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: colors.subtle, fontSize: 11 }}
            axisLine={{ stroke: colors.line }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: colors.subtle, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip cursor={{ fill: `${colors.iris}22` }} content={<TooltipContent unit={unit} />} />
          <Bar dataKey="value" name="数量" radius={[6, 6, 0, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.name} fill={d.color ?? fill} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** StatCard 里的微型趋势线（只画相对形状，不编造时间轴）。 */
export function MiniTrend({ data, color }: { data: number[]; color?: string }) {
  const colors = useAuroraColors()
  const stroke = color ?? colors.mint
  if (data.length < 2) return null
  const points = data.map((value, index) => ({ index, value }))

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="miniTrendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.45} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke={stroke}
          strokeWidth={2}
          fill="url(#miniTrendFill)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Record<string, number> → ChartDatum[]，顺序稳定（按值降序）。 */
export function toChartData(source: Record<string, number> | undefined, labels?: Record<string, string>): ChartDatum[] {
  if (!source) return []
  return Object.entries(source)
    .map(([name, value]) => ({ name: labels?.[name] ?? name, value: Number(value) || 0 }))
    .sort((a, b) => b.value - a.value)
}
