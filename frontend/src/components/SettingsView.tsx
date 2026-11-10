// -*- coding: utf-8 -*-
/**
 * SettingsView — 全局工具「设置」：按业务板块选择模型
 *
 * 分层原则（页面里也直接写出来，避免用户以为这里要填 API Key）：
 *   - 密钥 / base_url 只在后端 .env，本页不保存、不回显，只显示「是否已配置」和环境变量名；
 *   - 板块 → provider + 模型名 存在 DB，改完即时生效、不用重启；
 *   - 代码里的默认值是 fallback，空库也能跑。
 *
 * 交互：每行是独立草稿，改完统一保存；可先「测试」再保存，测试用临时配置、不写库。
 */
import { useEffect, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Info,
  KeyRound,
  Loader2,
  Play,
  RotateCcw,
  Save,
  Settings2,
  XCircle,
} from 'lucide-react'
import { cn } from '../utils'
import { useToast } from '../contexts/ToastContext'
import {
  getModelSettings,
  resetModelSetting,
  saveModelSettings,
  testModelSetting,
  type ModelProviderInfo,
  type ModelSettingsResponse,
  type ModelSlot,
  type ModelTestResult,
} from '../api'

interface DraftChoice {
  provider: string
  model: string
}

interface TestState {
  loading: boolean
  result?: ModelTestResult
}

function toDraft(data: ModelSettingsResponse): Record<string, DraftChoice> {
  return Object.fromEntries(
    data.slots.map((slot) => [slot.key, { provider: slot.provider, model: slot.model }]),
  )
}

function providerLabel(providers: ModelProviderInfo[], key: string): string {
  if (key === 'auto') return '自动（按优先级）'
  return providers.find((provider) => provider.key === key)?.label ?? key
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', ok ? 'bg-ok' : 'bg-warn')}
      title={ok ? '已配置密钥' : '未配置密钥'}
    />
  )
}

interface SlotCardProps {
  slot: ModelSlot
  providers: ModelProviderInfo[]
  choice: DraftChoice
  dirty: boolean
  test: TestState | undefined
  saving: boolean
  onChange: (key: string, next: DraftChoice) => void
  onTest: (slot: ModelSlot, choice: DraftChoice) => void
  onReset: (slot: ModelSlot) => void
}

function SlotCard({
  slot, providers, choice, dirty, test, saving, onChange, onTest, onReset,
}: SlotCardProps) {
  const planned = slot.status === 'planned'
  const selectedProvider = choice.provider === 'auto'
    ? providers.find((p) => p.key === slot.effective_provider)
    : providers.find((p) => p.key === choice.provider)
  // 占位符显示「留空后真正会用哪个模型」：auto 时用后端解析出的生效模型，
  // 而不是代码里的静态默认值（例如 ARK_EMBEDDING_MODEL 可被 .env 覆盖）。
  const modelPlaceholder = choice.provider === 'auto'
    ? (slot.effective_model || slot.default_model)
    : (selectedProvider?.default_model || slot.default_model)

  return (
    <div
      data-testid={`model-slot-${slot.key}`}
      className={cn(
        'rounded-xl border px-4 py-3.5 transition-colors',
        dirty ? 'border-flare/50 bg-flare/[0.04]' : 'border-line bg-canvas/40',
      )}
    >
      <div className="flex flex-col lg:flex-row lg:items-start gap-3">
        {/* 左：板块身份 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-[13px] font-medium text-ink">{slot.label}</h4>
            {planned && (
              <span className="rounded-pill border border-line px-2 py-0.5 font-mono text-[9px] text-ink-subtle">
                预留 · 未接模型
              </span>
            )}
            {slot.custom && (
              <span className="rounded-pill border border-flare/30 bg-flare/10 px-2 py-0.5 font-mono text-[9px] text-flare">
                已自定义
              </span>
            )}
            {dirty && (
              <span className="rounded-pill border border-warn/30 bg-warn/10 px-2 py-0.5 font-mono text-[9px] text-warn">
                待保存
              </span>
            )}
          </div>
          <p className="mt-1 text-[11px] text-ink-subtle leading-relaxed">{slot.desc}</p>
          <div className="mt-2 flex items-center gap-1.5 flex-wrap">
            <StatusDot ok={slot.configured} />
            <span className="font-mono text-[10px] text-ink-subtle">
              当前生效 {providerLabel(providers, slot.effective_provider)} / {slot.effective_model || '（未设置）'}
            </span>
          </div>
          {slot.hint && (
            <p className="mt-1.5 flex items-start gap-1 text-[10px] text-warn leading-relaxed">
              <Info size={11} className="mt-0.5 flex-shrink-0" />
              {slot.hint}
            </p>
          )}
        </div>

        {/* 右：编辑区 */}
        <div className="flex-shrink-0 w-full lg:w-[310px] space-y-2">
          <div className="flex gap-2">
            <label className="min-w-0 flex-1">
              <span className="block mb-1 font-mono text-[9px] text-ink-subtle uppercase tracking-wider">Provider</span>
              <select
                data-testid={`model-provider-${slot.key}`}
                value={choice.provider}
                onChange={(event) => onChange(slot.key, { ...choice, provider: event.target.value })}
                className="w-full h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink outline-none focus:border-flare/60"
              >
                {slot.allowed_providers.map((key) => (
                  <option key={key} value={key}>{providerLabel(providers, key)}</option>
                ))}
              </select>
            </label>
            <label className="min-w-0 flex-1">
              <span className="block mb-1 font-mono text-[9px] text-ink-subtle uppercase tracking-wider">模型名</span>
              <input
                data-testid={`model-name-${slot.key}`}
                value={choice.model}
                placeholder={modelPlaceholder || '留空用默认模型'}
                onChange={(event) => onChange(slot.key, { ...choice, model: event.target.value })}
                className="w-full h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink outline-none focus:border-flare/60 placeholder:text-ink-subtle/70"
              />
            </label>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid={`model-test-${slot.key}`}
              disabled={test?.loading || planned}
              onClick={() => onTest(slot, choice)}
              className={cn(
                'inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-line text-[10px] text-ink-subtle hover:text-ink hover:border-iris/40 transition-colors',
                (test?.loading || planned) && 'opacity-50 cursor-not-allowed',
              )}
              title={planned ? '该板块尚未接入真实模型，无需测试' : '用当前草稿发一次最小请求，不写库'}
            >
              {test?.loading ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
              测试
            </button>
            <button
              type="button"
              data-testid={`model-reset-${slot.key}`}
              disabled={saving}
              onClick={() => onReset(slot)}
              className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-line text-[10px] text-ink-subtle hover:text-ink hover:border-iris/40 transition-colors disabled:opacity-50"
              title="恢复代码默认值 + 自动挑 provider"
            >
              <RotateCcw size={11} /> 恢复默认
            </button>
            {slot.source === 'override' && (
              <span className="font-mono text-[9px] text-flare">DB 覆盖中</span>
            )}
          </div>
        </div>
      </div>

      {test?.result && (
        <div
          data-testid={`model-test-result-${slot.key}`}
          className={cn(
            'mt-3 rounded-lg border px-3 py-2 text-[10px] leading-relaxed',
            test.result.ok ? 'border-ok/30 bg-ok/[0.06] text-ok' : 'border-warn/30 bg-warn/[0.06] text-warn',
          )}
        >
          <div className="flex items-center gap-1.5 font-medium">
            {test.result.ok ? <CheckCircle2 size={12} /> : test.result.skipped ? <AlertCircle size={12} /> : <XCircle size={12} />}
            {test.result.ok ? '连通正常' : test.result.skipped ? '已跳过' : '不可用'}
            {test.result.latency_ms != null && (
              <span className="font-mono font-normal opacity-80">· {test.result.latency_ms} ms</span>
            )}
          </div>
          <p className="mt-1 break-all">{test.result.detail}</p>
          {test.result.sample && <p className="mt-0.5 font-mono opacity-80">响应：{test.result.sample}</p>}
        </div>
      )}
    </div>
  )
}

export default function SettingsView() {
  const { showToast } = useToast()
  const [data, setData] = useState<ModelSettingsResponse | null>(null)
  const [draft, setDraft] = useState<Record<string, DraftChoice>>({})
  const [tests, setTests] = useState<Record<string, TestState>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const apply = (response: ModelSettingsResponse) => {
    setData(response)
    setDraft(toDraft(response))
  }

  const load = () => {
    setLoading(true)
    setError('')
    void getModelSettings()
      .then(apply)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '加载模型设置失败'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const original = data ? toDraft(data) : {}
  const dirtyKeys = Object.keys(draft).filter((key) => {
    const before = original[key]
    return before && (before.provider !== draft[key].provider || before.model !== draft[key].model)
  })

  const changeSlot = (key: string, next: DraftChoice) => {
    setDraft((previous) => ({ ...previous, [key]: next }))
    setTests((previous) => {
      const copy = { ...previous }
      delete copy[key]
      return copy
    })
  }

  const save = async () => {
    if (dirtyKeys.length === 0) return
    setSaving(true)
    try {
      const payload = Object.fromEntries(dirtyKeys.map((key) => [key, draft[key]]))
      const response = await saveModelSettings(payload)
      apply(response)
      showToast(`已保存 ${dirtyKeys.length} 个板块，即时生效`, 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const runTest = async (slot: ModelSlot, choice: DraftChoice) => {
    setTests((previous) => ({ ...previous, [slot.key]: { loading: true } }))
    try {
      const result = await testModelSetting({
        slot: slot.key,
        provider: choice.provider,
        model: choice.model,
      })
      setTests((previous) => ({ ...previous, [slot.key]: { loading: false, result } }))
    } catch (err) {
      setTests((previous) => ({
        ...previous,
        [slot.key]: {
          loading: false,
          result: {
            slot: slot.key, provider: choice.provider, model: choice.model,
            ok: false, detail: err instanceof Error ? err.message : '测试请求失败',
          },
        },
      }))
    }
  }

  const resetSlot = async (slot: ModelSlot) => {
    // 只是把草稿改回默认、还没保存过：纯前端复位即可
    if (!slot.custom) {
      changeSlot(slot.key, { provider: 'auto', model: '' })
      showToast(`「${slot.label}」草稿已复位`, 'info')
      return
    }
    try {
      const response = await resetModelSetting(slot.key)
      // 只复位这一个板块；其他板块的未保存草稿不能被一次「恢复默认」清掉
      setData(response)
      setDraft((previous) => ({ ...previous, [slot.key]: { provider: 'auto', model: '' } }))
      showToast(`「${slot.label}」已恢复默认`, 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '恢复默认失败', 'error')
    }
  }

  if (loading) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center bg-panel text-ink-subtle text-xs gap-2">
        <Loader2 size={14} className="animate-spin" /> 正在读取模型配置…
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 bg-panel px-6 text-center">
        <AlertCircle size={22} className="text-warn" />
        <p className="text-sm text-ink">无法读取模型设置</p>
        <p className="text-[11px] text-ink-subtle max-w-md">{error || '后端未返回配置'}</p>
        <button
          type="button"
          onClick={load}
          className="h-8 px-3 rounded-lg border border-line text-[11px] text-ink hover:border-iris/50"
        >
          重试
        </button>
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-panel">
      <header className="h-14 px-5 flex items-center justify-between border-b border-line flex-shrink-0 gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-flare/15 text-flare flex items-center justify-center flex-shrink-0">
            <Settings2 size={16} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-ink leading-tight">设置 <span className="text-ink-subtle font-normal">/ 模型信息</span></h2>
            <p className="text-[11px] text-ink-subtle truncate">按业务板块选择模型 · 共 {data.slots.length} 个板块、{data.providers.length} 个 Provider</p>
          </div>
        </div>
        <button
          type="button"
          data-testid="save-model-settings"
          disabled={saving || dirtyKeys.length === 0}
          onClick={() => void save()}
          className={cn(
            'inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[11px] font-medium flex-shrink-0 transition-colors',
            dirtyKeys.length > 0
              ? 'bg-flare text-white hover:opacity-90'
              : 'border border-line text-ink-subtle cursor-not-allowed',
          )}
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {dirtyKeys.length > 0 ? `保存 ${dirtyKeys.length} 项更改` : '已保存'}
        </button>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-5">
        {/* 分层原则：把「为什么不在这里填 Key」讲清楚 */}
        <section className="rounded-xl border border-iris/25 bg-iris/[0.05] px-4 py-3">
          <div className="flex items-center gap-2">
            <KeyRound size={14} className="text-iris" />
            <h3 className="text-[12px] font-medium text-ink">密钥不在这里配</h3>
          </div>
          <p className="mt-1.5 text-[11px] text-ink-subtle leading-relaxed">
            API Key 与 base_url 只在后端 <code className="font-mono text-ink">.env</code> 里配置，本页不保存也不回显密钥
            （开源自托管：密钥进数据库会随备份泄露、多实例还会不一致）。
            这里只决定「哪个板块用哪个模型」，改动写入数据库，<strong className="text-ink font-medium">保存后即时生效、不用重启</strong>；
            没改过的板块继续用代码默认值。
          </p>
        </section>

        {/* Provider 连接状态 */}
        <section>
          <div className="mb-2.5 flex items-center gap-2">
            <Cpu size={13} className="text-ink-subtle" />
            <h3 className="text-[12px] font-medium text-ink">Provider 连接状态</h3>
            <span className="font-mono text-[10px] text-ink-subtle">来自 .env · 只读</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
            {data.providers.map((provider) => (
              <div key={provider.key} className="rounded-xl border border-line bg-canvas/40 px-3.5 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[12px] font-medium text-ink truncate">{provider.label}</span>
                  <span
                    className={cn(
                      'rounded-pill border px-2 py-0.5 font-mono text-[9px] flex-shrink-0',
                      provider.configured ? 'border-ok/30 bg-ok/10 text-ok' : 'border-warn/30 bg-warn/10 text-warn',
                    )}
                  >
                    {provider.configured ? '已配置' : '未配置'}
                  </span>
                </div>
                <p className="mt-2 font-mono text-[10px] text-ink-subtle break-all">{provider.env_key}</p>
                <p className="mt-0.5 font-mono text-[10px] text-ink-subtle truncate" title={provider.base_url}>
                  {provider.base_url || '（未设置 base_url）'}
                </p>
                <p className="mt-1.5 text-[10px] text-ink-subtle truncate">
                  默认模型 <span className="font-mono text-ink">{provider.default_model || '—'}</span>
                </p>
                {provider.hint && <p className="mt-1 text-[10px] text-iris leading-relaxed">{provider.hint}</p>}
              </div>
            ))}
          </div>
        </section>

        {/* 板块列表：按组分开，跨组没有前后关系 */}
        {data.groups.map((group) => {
          const slots = data.slots.filter((slot) => slot.group === group.id)
          if (slots.length === 0) return null
          return (
            <section key={group.id} data-testid={`model-group-${group.id}`}>
              <div className="mb-2.5 flex items-baseline gap-2">
                <h3 className="text-[12px] font-medium text-ink">{group.label}</h3>
                <span className="text-[10px] text-ink-subtle">{group.hint}</span>
                <span className="flex-1 h-px bg-line/70" />
                <span className="font-mono text-[10px] text-ink-subtle">{slots.length}</span>
              </div>
              <div className="space-y-2.5">
                {slots.map((slot) => (
                  <SlotCard
                    key={slot.key}
                    slot={slot}
                    providers={data.providers}
                    choice={draft[slot.key] ?? { provider: 'auto', model: '' }}
                    dirty={dirtyKeys.includes(slot.key)}
                    test={tests[slot.key]}
                    saving={saving}
                    onChange={changeSlot}
                    onTest={(target, choice) => void runTest(target, choice)}
                    onReset={(target) => void resetSlot(target)}
                  />
                ))}
              </div>
            </section>
          )
        })}
        <div className="h-4" />
      </div>
    </div>
  )
}
