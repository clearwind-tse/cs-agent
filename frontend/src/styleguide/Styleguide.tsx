import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import {
  Accessibility,
  Activity,
  ArrowUpRight,
  Check,
  CircleDot,
  Database,
  Gauge,
  Layers,
  MousePointer2,
  Palette,
  Sparkles,
  Type,
  Zap,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  AuroraBackground,
  Badge,
  Button,
  GlassCard,
  Progress,
  Skeleton,
  StatCard,
  Tabs,
  ThemeToggle,
} from '../components/ui'
import { useTheme } from '../contexts/ThemeContext'
import { cn } from '../utils'

/* ------------------------------------------------------------------ */
/* 图表配色：从 CSS 变量实时读取，保证明暗两套都准确                      */
/* ------------------------------------------------------------------ */

interface AuroraColors {
  mint: string
  iris: string
  flare: string
  line: string
  inkSubtle: string
  panel: string
  ink: string
}

const FALLBACK_COLORS: AuroraColors = {
  mint: 'rgb(110 242 197)',
  iris: 'rgb(139 123 255)',
  flare: 'rgb(255 92 168)',
  line: 'rgb(46 43 94)',
  inkSubtle: 'rgb(131 126 174)',
  panel: 'rgb(21 20 49)',
  ink: 'rgb(244 242 255)',
}

function useAuroraColors(): AuroraColors {
  const { resolvedTheme } = useTheme()
  const [colors, setColors] = useState<AuroraColors>(FALLBACK_COLORS)

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const style = getComputedStyle(document.documentElement)
      const read = (name: string, fallback: string) => {
        const raw = style.getPropertyValue(name).trim()
        return raw ? `rgb(${raw})` : fallback
      }
      setColors({
        mint: read('--c-mint', FALLBACK_COLORS.mint),
        iris: read('--c-iris', FALLBACK_COLORS.iris),
        flare: read('--c-flare', FALLBACK_COLORS.flare),
        line: read('--c-line', FALLBACK_COLORS.line),
        inkSubtle: read('--c-ink-subtle', FALLBACK_COLORS.inkSubtle),
        panel: read('--c-panel', FALLBACK_COLORS.panel),
        ink: read('--c-ink', FALLBACK_COLORS.ink),
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [resolvedTheme])

  return colors
}

/* ------------------------------------------------------------------ */
/* 示例数据（仅用于组件演示，不代表任何业务指标）                         */
/* ------------------------------------------------------------------ */

const trendData = [
  { label: '01', value: 38 },
  { label: '02', value: 52 },
  { label: '03', value: 47 },
  { label: '04', value: 68 },
  { label: '05', value: 61 },
  { label: '06', value: 79 },
  { label: '07', value: 74 },
  { label: '08', value: 91 },
]

const dimensionData = [
  { name: '合规', score: 91 },
  { name: '语气', score: 86 },
  { name: '算账', score: 72 },
  { name: '时效', score: 64 },
  { name: '共情', score: 58 },
]

const swatches = [
  { name: 'Canvas', hex: '#0B0A1F', lightHex: '#F6F4FF', role: '页面基底', dark: true },
  { name: 'Panel', hex: '#151431', lightHex: '#FFFFFF', role: '玻璃卡片', dark: true },
  { name: 'Panel 2', hex: '#1E1C40', lightHex: '#F0EDFF', role: '悬浮 / 凸起', dark: true },
  { name: 'Line', hex: '#2E2B5E', lightHex: '#DED8F5', role: '分隔与描边', dark: true },
  { name: 'Ink', hex: '#F4F2FF', lightHex: '#1A1733', role: '正文 ≈15:1', dark: false },
  { name: 'Ink muted', hex: '#C3BEE6', lightHex: '#4B4670', role: '次级 ≈7:1', dark: false },
]

const accents = [
  { name: 'Mint', hex: '#6EF2C5', variable: '--c-mint', role: '主 CTA / 成功' },
  { name: 'Flare', hex: '#FF5CA8', variable: '--c-flare', role: '强调 / 危险' },
  { name: 'Iris', hex: '#8B7BFF', variable: '--c-iris', role: '链接 / 信息' },
]

/* ------------------------------------------------------------------ */
/* 小组件                                                              */
/* ------------------------------------------------------------------ */

function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: reduce ? 0 : delay, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

function SectionHeading({
  index,
  kicker,
  title,
  description,
  icon,
}: {
  index: string
  kicker: string
  title: string
  description: string
  icon: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-col gap-5 border-t border-line/60 pt-8 md:flex-row md:items-end md:justify-between">
      <div>
        <div className="sg-mono flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-ink-subtle">
          <span className="text-iris">{index}</span>
          <span className="h-px w-6 bg-line-strong" />
          {kicker}
        </div>
        <h2 className="sg-display mt-3 text-3xl font-bold tracking-tight text-ink md:text-4xl">{title}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-muted">{description}</p>
      </div>
      <div className="hidden h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-line/70 bg-panel-2/50 text-iris md:flex">
        {icon}
      </div>
    </div>
  )
}

function Sparkline({ points, color }: { points: number[]; color: string }) {
  const path = useMemo(() => {
    const max = Math.max(...points)
    const min = Math.min(...points)
    const span = max - min || 1
    return points
      .map((point, index) => {
        const x = (index / (points.length - 1)) * 100
        const y = 29 - ((point - min) / span) * 25
        return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
      })
      .join(' ')
  }, [points])

  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" className="h-full w-full" aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* 主体                                                                */
/* ------------------------------------------------------------------ */

export function Styleguide() {
  const { resolvedTheme } = useTheme()
  const colors = useAuroraColors()
  const [tab, setTab] = useState('overview')
  const [reduceDemo, setReduceDemo] = useState(false)
  const [showSkeleton, setShowSkeleton] = useState(false)
  const reduce = useReducedMotion()

  const axisStyle = { fill: colors.inkSubtle, fontSize: 11, fontFamily: 'JetBrains Mono Variable, monospace' }
  const tooltipStyle = {
    background: colors.panel,
    border: `1px solid ${colors.line}`,
    borderRadius: 16,
    color: colors.ink,
    fontSize: 12,
    boxShadow: '0 18px 40px -18px rgb(0 0 0 / 0.6)',
  }

  return (
    <div className={cn('relative min-h-screen overflow-hidden bg-canvas text-ink', reduceDemo && 'sg-reduce-motion')}>
      <AuroraBackground variant="login" className="fixed inset-0" />
      <div className="sg-grain" />

      <div className="relative z-10 mx-auto max-w-[1240px] px-5 pb-24 pt-7 md:px-10">
        {/* ── 顶栏 ─────────────────────────────────────────────── */}
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div
              className="relative h-9 w-9 rounded-xl"
              style={{ background: 'conic-gradient(from 210deg, rgb(var(--c-mint)), rgb(var(--c-iris)), rgb(var(--c-flare)), rgb(var(--c-mint)))' }}
            >
              <div className="absolute inset-[3px] rounded-[9px] bg-canvas/85 backdrop-blur-md" />
              <Sparkles size={15} className="absolute inset-0 m-auto text-ink" strokeWidth={1.6} />
            </div>
            <div>
              <div className="sg-display text-sm font-bold tracking-[0.08em] text-ink">AURORA / DESIGN LAB</div>
              <div className="sg-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle">AiWxChat · v0.1 · S0 preview</div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Badge tone="iris" dot>
              组件预览 · 非产品页面
            </Badge>
            <ThemeToggle showLabel />
          </div>
        </header>

        {/* ── Hero ─────────────────────────────────────────────── */}
        <section className="mt-16 grid items-center gap-10 lg:mt-24 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <motion.div
              initial={{ opacity: 0, y: reduce ? 0 : 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
              className="sg-mono flex items-center gap-3 text-[11px] uppercase tracking-[0.28em] text-ink-subtle"
            >
              <CircleDot size={13} className="text-mint" />
              Design system / 01 — Fluid aurora
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: reduce ? 0 : 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.75, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
              className="sg-display mt-6 text-[clamp(2.9rem,7vw,5.6rem)] font-extrabold leading-[0.98] tracking-[-0.045em] text-ink"
            >
              让数据，
              <br />
              <span className="aurora-text">在光里流动。</span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: reduce ? 0 : 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.18 }}
              className="mt-7 max-w-xl text-[15px] leading-[1.85] text-ink-muted"
            >
              深靛基底、薄荷与洋红的光晕、玻璃层次与精密排印。
              为客服质检与智能客服工作台做的一套<span className="text-ink">超前卫但耐看</span>的视觉语言。
              本页只陈列组件与材质，不含任何业务数据。
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: reduce ? 0 : 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.28 }}
              className="mt-9 flex flex-wrap items-center gap-3"
            >
              <Button variant="primary" size="lg" icon={<ArrowUpRight size={17} />}>
                向下探索组件
              </Button>
              <Button variant="ghost" size="lg" onClick={() => setReduceDemo((value) => !value)}>
                {reduceDemo ? '恢复动效' : '演示降低动效'}
              </Button>
            </motion.div>

            <div className="sg-mono mt-10 flex flex-wrap gap-x-7 gap-y-2 text-[10px] uppercase tracking-[0.16em] text-ink-subtle">
              <span>2 themes</span>
              <span>0 remote assets</span>
              <span>self-hosted type</span>
              <span>reduced-motion ready</span>
            </div>
          </div>

          {/* 材质标本卡 */}
          <motion.div
            initial={{ opacity: 0, scale: reduce ? 1 : 0.96, y: reduce ? 0 : 18 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
          >
            <GlassCard className="p-6" glow>
              <div className="flex items-center justify-between">
                <span className="sg-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle">Material specimen / 001</span>
                <Zap size={15} className="text-mint" />
              </div>

              <div className="relative mt-6 h-40 overflow-hidden rounded-2xl border border-line/60 bg-canvas/20">
                <div className="aurora-grid absolute inset-0 opacity-80" />
                <div className="aurora-orb absolute -left-8 -top-10 h-40 w-40" style={{ background: 'rgb(var(--c-mint))', opacity: 0.9, filter: 'blur(40px)' }} />
                <div className="aurora-orb aurora-orb-slow absolute -right-6 top-0 h-36 w-36" style={{ background: 'rgb(var(--c-flare))', opacity: 0.8, filter: 'blur(40px)' }} />
                <div className="aurora-orb absolute -bottom-10 left-1/3 h-36 w-36" style={{ background: 'rgb(var(--c-iris))', opacity: 0.85, filter: 'blur(40px)' }} />
                <div className="absolute inset-0 flex items-end justify-between p-4">
                  <span className="sg-mono text-[10px] uppercase tracking-widest text-ink/80">blur 40px · 28s drift</span>
                  <span className="sg-mono text-[10px] text-ink/80">rgba / mesh</span>
                </div>
              </div>

              <div className="mt-5 space-y-2.5">
                {[
                  ['Radius', '24px / card'],
                  ['Backdrop', 'blur(24px) saturate(150%)'],
                  ['Border', '1px · line / 55%'],
                  ['Type', 'Syne · DM Sans · JetBrains Mono'],
                ].map(([key, value]) => (
                  <div key={key} className="flex items-baseline justify-between gap-4 border-b border-line/40 pb-2 last:border-0">
                    <span className="sg-mono text-[10px] uppercase tracking-widest text-ink-subtle">{key}</span>
                    <span className="sg-mono truncate text-[11px] text-ink">{value}</span>
                  </div>
                ))}
              </div>

              <div className="mt-5 flex items-center gap-2">
                <Badge tone="mint" dot size="sm">active theme</Badge>
                <Badge tone="neutral" size="sm">{resolvedTheme === 'dark' ? 'aurora dark' : 'aurora light'}</Badge>
              </div>
            </GlassCard>
          </motion.div>
        </section>

        {/* ── 01 色彩 ───────────────────────────────────────────── */}
        <section className="mt-28">
          <Reveal>
            <SectionHeading
              index="01"
              kicker="Color system"
              title="有主次，才够前卫"
              description="一套语义色负责可读性，三束装饰光负责记忆点。所有值都是 CSS 变量，明暗主题共用同一套类名，组件不需要写 dark: 判断。"
              icon={<Palette size={19} />}
            />
          </Reveal>

          <Reveal delay={0.08}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {swatches.map((swatch) => (
                <div key={swatch.name} className="glass overflow-hidden rounded-2xl">
                  <div className="h-20 w-full border-b border-line/60" style={{ background: resolvedTheme === 'dark' ? swatch.hex : swatch.lightHex }} />
                  <div className="p-3">
                    <div className="text-xs font-medium text-ink">{swatch.name}</div>
                    <div className="sg-mono mt-1 text-[10px] text-ink-subtle">
                      {resolvedTheme === 'dark' ? swatch.hex : swatch.lightHex}
                    </div>
                    <div className="mt-2 text-[10px] text-ink-subtle">{swatch.role}</div>
                  </div>
                </div>
              ))}
            </div>
          </Reveal>

          <Reveal delay={0.14}>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {accents.map((accent) => (
                <div key={accent.name} className="glass flex items-center gap-4 rounded-2xl p-4">
                  <div
                    className="h-12 w-12 shrink-0 rounded-2xl"
                    style={{ background: accent.hex, boxShadow: `0 0 34px -6px ${accent.hex}` }}
                  />
                  <div className="min-w-0">
                    <div className="sg-display text-sm font-bold text-ink">{accent.name}</div>
                    <div className="sg-mono mt-0.5 truncate text-[10px] text-ink-subtle">{accent.variable} · {accent.hex}</div>
                    <div className="mt-1 text-[11px] text-ink-muted">{accent.role}</div>
                  </div>
                </div>
              ))}
            </div>
            <p className="sg-mono mt-4 text-[10px] uppercase tracking-widest text-ink-subtle">
              对比度：正文 ≥ 15:1 · 次级 ≥ 7:1 · 弱文本 ≥ 4.8:1 · UI 描边 ≥ 3:1
            </p>
          </Reveal>
        </section>

        {/* ── 02 排印 ───────────────────────────────────────────── */}
        <section className="mt-24">
          <Reveal>
            <SectionHeading
              index="02"
              kicker="Typography"
              title="字形就是态度"
              description="Syne 的几何张力做标题，DM Sans 承担长文阅读，JetBrains Mono 让所有数字对齐。全部自托管，内网与离线部署不降级、无 CLS。"
              icon={<Type size={19} />}
            />
          </Reveal>

          <div className="grid gap-4 lg:grid-cols-2">
            <Reveal>
              <GlassCard className="p-7">
                <div className="sg-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle">Display / Syne Variable</div>
                <div className="sg-display mt-4 text-5xl font-extrabold leading-none tracking-[-0.05em] text-ink">Ag 光学</div>
                <div className="sg-display mt-3 text-2xl font-bold tracking-tight text-ink-muted">0123456789 —— Flux</div>
                <div className="aurora-hairline mt-6 h-px w-full opacity-70" />
                <div className="sg-mono mt-4 text-[11px] leading-relaxed text-ink-subtle">
                  WEIGHT 400 → 800 · TIGHT TRACKING · GEOMETRIC TERMINALS
                </div>
              </GlassCard>
            </Reveal>

            <Reveal delay={0.08}>
              <GlassCard className="p-7">
                <div className="sg-mono text-[10px] uppercase tracking-[0.2em] text-ink-subtle">Body / DM Sans + CJK system stack</div>
                <p className="mt-4 text-[15px] leading-[1.9] text-ink">
                  客服主管在质检台前停留的时间，比任何一屏都长。
                  所以字号、行高与对比度不是装饰，是效率本身。
                </p>
                <p className="mt-3 text-[13px] leading-[1.8] text-ink-muted">
                  Legibility is not a decoration. It is the interface.
                </p>
                <div className="mt-6 grid grid-cols-3 gap-2">
                  {['128.40', '94.2%', '00:42:17'].map((value) => (
                    <div key={value} className="rounded-xl border border-line/60 bg-panel-2/50 px-3 py-2.5">
                      <div className="sg-mono text-sm tabular-nums text-ink">{value}</div>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </Reveal>
          </div>
        </section>

        {/* ── 03 数据 ───────────────────────────────────────────── */}
        <section className="mt-24">
          <Reveal>
            <SectionHeading
              index="03"
              kicker="Data surfaces"
              title="密集，但不拥挤"
              description="玻璃卡片承载信息层级，图表只用真实字段着色。下面是组件演示数据，不代表任何业务指标。"
              icon={<Database size={19} />}
            />
          </Reveal>

          <motion.div
            initial="hidden"
            animate="show"
            transition={{ staggerChildren: reduce ? 0 : 0.08 }}
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
          >
            <StatCard label="Total sessions" value="284" delta="+12.4%" deltaTone="up" icon={<Layers size={17} />} tone="mint" hint="较上一周期" chart={<Sparkline points={[3, 5, 4, 7, 6, 9, 8, 11]} color={colors.mint} />} />
            <StatCard label="Avg. score" value="86.4" delta="+3.1" deltaTone="up" icon={<Gauge size={17} />} tone="iris" hint="满分 100" chart={<Sparkline points={[7, 6, 8, 7, 9, 8, 10, 9]} color={colors.iris} />} />
            <StatCard label="Pass rate" value="94.2%" delta="−0.8%" deltaTone="down" icon={<Activity size={17} />} tone="flare" hint="阈值 80" chart={<Sparkline points={[10, 9, 10, 8, 9, 7, 8, 7]} color={colors.flare} />} />
            <StatCard label="Pending review" value="19" delta="需人工" deltaTone="flat" icon={<Database size={17} />} hint="主管复核队列" chart={<Sparkline points={[4, 6, 5, 4, 3, 4, 2, 3]} color={colors.inkSubtle} />} />
          </motion.div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
            <Reveal>
              <GlassCard className="p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="sg-display text-lg font-bold text-ink">趋势 / Trend</div>
                    <div className="sg-mono mt-1 text-[10px] uppercase tracking-widest text-ink-subtle">示例数据 · 仅用于组件演示</div>
                  </div>
                  <Badge tone="mint" dot size="sm">Area chart</Badge>
                </div>
                <div className="mt-5 h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trendData} margin={{ top: 8, right: 6, left: -24, bottom: 0 }}>
                      <defs>
                        <linearGradient id="sgArea" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={colors.mint} stopOpacity={0.5} />
                          <stop offset="55%" stopColor={colors.iris} stopOpacity={0.22} />
                          <stop offset="100%" stopColor={colors.iris} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke={colors.line} strokeDasharray="3 6" vertical={false} />
                      <XAxis dataKey="label" tick={axisStyle} axisLine={false} tickLine={false} />
                      <YAxis tick={axisStyle} axisLine={false} tickLine={false} domain={[0, 100]} />
                      <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: colors.iris, strokeDasharray: '4 4' }} />
                      <Area type="monotone" dataKey="value" stroke={colors.mint} strokeWidth={2.4} fill="url(#sgArea)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </GlassCard>
            </Reveal>

            <Reveal delay={0.08}>
              <GlassCard className="p-6">
                <div className="sg-display text-lg font-bold text-ink">维度 / Dimensions</div>
                <div className="sg-mono mt-1 text-[10px] uppercase tracking-widest text-ink-subtle">示例数据 · ≥80 / ≥60 阈值</div>
                <div className="mt-5 h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dimensionData} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
                      <CartesianGrid stroke={colors.line} strokeDasharray="3 6" horizontal={false} />
                      <XAxis type="number" domain={[0, 100]} tick={axisStyle} axisLine={false} tickLine={false} />
                      <YAxis type="category" dataKey="name" width={44} tick={axisStyle} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={tooltipStyle} cursor={{ fill: colors.iris, fillOpacity: 0.1 }} />
                      <Bar dataKey="score" radius={[0, 8, 8, 0]} barSize={14}>
                        {dimensionData.map((item) => (
                          <Cell key={item.name} fill={item.score >= 80 ? colors.mint : item.score >= 60 ? colors.iris : colors.flare} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </GlassCard>
            </Reveal>
          </div>
        </section>

        {/* ── 04 组件 ───────────────────────────────────────────── */}
        <section className="mt-24">
          <Reveal>
            <SectionHeading
              index="04"
              kicker="Components"
              title="同一套零件，全站复用"
              description="把散落在 30 个组件里的重复实现收成受控 primitives。这里每个控件都可交互，切换主题后可立即检查两套表现。"
              icon={<Layers size={19} />}
            />
          </Reveal>

          <Reveal>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <Tabs
                items={[
                  { key: 'overview', label: '按钮与徽章' },
                  { key: 'components', label: '进度与表格' },
                  { key: 'motion', label: '加载骨架' },
                ]}
                value={tab}
                onChange={setTab}
              />
              <span className="sg-mono text-[10px] uppercase tracking-widest text-ink-subtle">tab: {tab}</span>
            </div>
          </Reveal>

          <div className="grid gap-4 lg:grid-cols-2">
            <Reveal>
              <GlassCard className="p-6">
                <div className="sg-display text-base font-bold text-ink">Buttons</div>
                <div className="mt-5 flex flex-wrap items-center gap-2.5">
                  <Button variant="primary">主要操作</Button>
                  <Button variant="secondary">次要操作</Button>
                  <Button variant="outline">描边</Button>
                  <Button variant="ghost">幽灵</Button>
                  <Button variant="danger">危险</Button>
                </div>
                <div className="mt-5 flex flex-wrap items-center gap-2.5">
                  <Button size="sm" variant="primary" icon={<ArrowUpRight size={14} />}>小尺寸</Button>
                  <Button size="lg" variant="secondary" leading={<Sparkles size={15} />}>大尺寸</Button>
                  <Button variant="outline" disabled>禁用态</Button>
                </div>

                <div className="mt-7 border-t border-line/50 pt-6">
                  <div className="sg-display text-base font-bold text-ink">Badges</div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Badge tone="mint" dot>已通过</Badge>
                    <Badge tone="flare" dot>待复核</Badge>
                    <Badge tone="iris" dot>AI 生成</Badge>
                    <Badge tone="ok">合规</Badge>
                    <Badge tone="warn">注意</Badge>
                    <Badge tone="bad">违规</Badge>
                    <Badge tone="neutral">草稿</Badge>
                  </div>
                </div>

                <div className="mt-7 border-t border-line/50 pt-6">
                  <div className="sg-display text-base font-bold text-ink">Tabs / underline</div>
                  <div className="mt-4">
                    <Tabs
                      variant="underline"
                      items={[{ key: 'a', label: '概览' }, { key: 'b', label: '明细' }, { key: 'c', label: '设置' }]}
                      value={tab === 'overview' ? 'a' : tab === 'components' ? 'b' : 'c'}
                      onChange={(key) => setTab(key === 'a' ? 'overview' : key === 'b' ? 'components' : 'motion')}
                    />
                  </div>
                </div>
              </GlassCard>
            </Reveal>

            <Reveal delay={0.08}>
              <GlassCard className="p-6">
                <div className="flex items-center justify-between gap-3">
                  <div className="sg-display text-base font-bold text-ink">Progress & data</div>
                  <Button size="sm" variant="ghost" onClick={() => setShowSkeleton((value) => !value)}>
                    {showSkeleton ? '显示内容' : '显示骨架'}
                  </Button>
                </div>

                {showSkeleton ? (
                  <div className="mt-5 space-y-4">
                    <Skeleton variant="stat" />
                    <Skeleton variant="table" lines={4} />
                  </div>
                ) : (
                  <>
                    <div className="mt-6 space-y-4">
                      <Progress value={86} tone="mint" showLabel label="合规率" />
                      <Progress value={64} tone="iris" showLabel label="标注进度" />
                      <Progress value={38} tone="flare" showLabel label="待处理" />
                      <Progress value={18} tone="bad" showLabel label="超时工单" />
                    </div>

                    <div className="mt-7 overflow-hidden rounded-2xl border border-line/60">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-panel-2/60 text-ink-subtle">
                          <tr>
                            <th className="px-4 py-3 font-medium">样本</th>
                            <th className="px-4 py-3 font-medium">状态</th>
                            <th className="px-4 py-3 text-right font-medium">得分</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-line/50">
                          {[
                            ['GM20250803-1287', '已通过', 92],
                            ['GM20250804-0431', '待复核', 74],
                            ['GM20250804-1102', '已通过', 88],
                            ['GM20250805-0093', '违规', 46],
                          ].map(([id, status, score]) => (
                            <tr key={String(id)} className="text-ink-muted transition-colors hover:bg-panel-2/40">
                              <td className="sg-mono px-4 py-3 text-[11px] text-ink">{id}</td>
                              <td className="px-4 py-3">
                                <Badge tone={status === '已通过' ? 'mint' : status === '待复核' ? 'iris' : 'bad'} size="sm" dot>
                                  {status}
                                </Badge>
                              </td>
                              <td className="sg-mono px-4 py-3 text-right tabular-nums text-ink">{score}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </GlassCard>
            </Reveal>
          </div>
        </section>

        {/* ── 05 动效与可访问性 ───────────────────────────────────── */}
        <section className="mt-24">
          <Reveal>
            <SectionHeading
              index="05"
              kicker="Motion & a11y"
              title="动得克制，用得明白"
              description="光晕用 CSS 合成层长时间漂移，入场用一次性交错揭示，微交互只做 2px 位移。prefers-reduced-motion 与键盘焦点是高优先级门禁，不是补丁。"
              icon={<MousePointer2 size={19} />}
            />
          </Reveal>

          <div className="grid gap-4 lg:grid-cols-2">
            <Reveal>
              <GlassCard className="p-6">
                <div className="flex items-center gap-2 text-ink">
                  <Zap size={17} className="text-mint" />
                  <span className="sg-display text-base font-bold">Motion spec</span>
                </div>
                <div className="mt-5 space-y-3">
                  {[
                    ['Orb drift', '28–38s · CSS transform · GPU'],
                    ['Page / section reveal', '0.6s · stagger 0.08s'],
                    ['Card stagger', '0.35s · y 14px → 0'],
                    ['Hover micro', '−3px · 200ms ease-out'],
                    ['Progress fill', '0.9s · expo-out'],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-baseline justify-between gap-4 border-b border-line/40 pb-2.5 last:border-0">
                      <span className="text-xs text-ink-muted">{label}</span>
                      <span className="sg-mono text-right text-[10px] text-ink-subtle">{value}</span>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </Reveal>

            <Reveal delay={0.08}>
              <GlassCard className="p-6">
                <div className="flex items-center gap-2 text-ink">
                  <Accessibility size={17} className="text-iris" />
                  <span className="sg-display text-base font-bold">Accessibility gates</span>
                </div>
                <div className="mt-5 space-y-3">
                  {[
                    '正文对比度 ≥ 4.5:1，大字与 UI ≥ 3:1',
                    '所有可聚焦元素有可见 focus-visible 环',
                    'prefers-reduced-motion 关闭全部动效',
                    '状态不只靠颜色：徽章带圆点与文字',
                    '每屏一个主 CTA，键盘可完整操作',
                    '320px 起无横向滚动，表格行内横滚',
                  ].map((item) => (
                    <div key={item} className="flex items-start gap-3 text-xs leading-relaxed text-ink-muted">
                      <Check size={14} className="mt-0.5 shrink-0 text-mint" />
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </Reveal>
          </div>
        </section>

        {/* 页尾补一层低强度光晕，避免长页下半段变成纯色死区 */}
        <div aria-hidden="true" className="pointer-events-none absolute bottom-0 left-0 right-0 h-[820px] overflow-hidden">
          <div
            className="aurora-orb absolute -bottom-40 left-[6%] h-[420px] w-[420px]"
            style={{ background: 'rgb(var(--c-iris))', filter: 'blur(100px)' }}
          />
          <div
            className="aurora-orb aurora-orb-slow absolute -bottom-48 right-[4%] h-[460px] w-[460px]"
            style={{ background: 'rgb(var(--c-mint))', filter: 'blur(110px)' }}
          />
        </div>

        {/* ── 页脚 ─────────────────────────────────────────────── */}
        <footer className="relative z-10 mt-24 border-t border-line/60 pt-8">
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <div className="sg-display text-2xl font-bold tracking-tight text-ink">
                Aurora <span className="aurora-text">/ 流体极光</span>
              </div>
              <p className="mt-2 max-w-lg text-xs leading-relaxed text-ink-subtle">
                S0 设计预览页。确认这套审美后，S1 会把令牌接进现有应用，S2–S4 逐页铺开，S5 清理收口。
                本页是独立 Vite 入口，不改动主应用路由与业务逻辑。
              </p>
            </div>
            <div className="sg-mono text-right text-[10px] uppercase leading-relaxed tracking-widest text-ink-subtle">
              <div>framer-motion · recharts</div>
              <div>syne / dm sans / jetbrains mono</div>
              <div className="mt-1 text-iris">zero remote assets</div>
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}
