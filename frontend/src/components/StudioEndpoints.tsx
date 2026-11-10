// -*- coding: utf-8 -*-
/**
 * StudioEndpoints — AI 创作 · 图像端点
 *
 * 这里管的是「端点池」和「服务绑定」，不是「某个功能选哪个模型」：
 *   - 端点是一等数据，可任意多个，声明能力标签与协议，密钥不回显明文；
 *   - 每个服务绑定一条**有序候选链**（第一个失败就试下一个），不是单选死一个；
 *   - 具体镜头用哪个端点在运行时按能力分派，任务里还能临时覆盖（见 StudioTaskRunner）；
 *   - 内置 mock 端点永远在链尾，没配任何真实端点也能把出图链路跑完。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  Info,
  KeyRound,
  Loader2,
  Pencil,
  Play,
  Plus,
  Save,
  Trash2,
  X,
} from 'lucide-react'
import { cn } from '../utils'
import { useToast } from '../contexts/ToastContext'
import {
  createImageEndpoint,
  deleteImageEndpoint,
  getImageEndpoints,
  setImageBindings,
  testImageEndpoint,
  updateImageEndpoint,
  type ImageEndpoint,
  type ImageEndpointPayload,
  type ImageEndpointTestResult,
  type ImageEndpointsResponse,
} from '../api'

const EMPTY_FORM: ImageEndpointPayload = {
  name: '',
  protocol: 'webhook',
  base_url: '',
  model: '',
  auth_mode: 'none',
  api_key_env: '',
  api_key_inline: '',
  capabilities: ['img2img'],
  params: {},
  max_refs: 4,
  timeout_s: 60,
  enabled: true,
  priority: 100,
  note: '',
}

const PROTOCOL_SHORT: Record<string, string> = {
  webhook: '通用 HTTP',
  openai_images: 'OpenAI 图像',
  volc_ark: '火山方舟',
  mock: '内置占位图',
}

function capLabel(data: ImageEndpointsResponse | null, key: string): string {
  return data?.capabilities.find((c) => c.key === key)?.label ?? key
}

function chainKeys(data: ImageEndpointsResponse | null, service: string, capability = ''): string[] {
  return (data?.bindings ?? [])
    .filter((b) => b.service === service && b.capability === capability)
    .sort((a, b) => a.priority - b.priority)
    .map((b) => b.endpoint_key)
}

interface EndpointModalProps {
  initial: ImageEndpoint | null
  data: ImageEndpointsResponse
  onClose: () => void
  onSaved: (response: ImageEndpointsResponse) => void
}

function EndpointModal({ initial, data, onClose, onSaved }: EndpointModalProps) {
  const { showToast } = useToast()
  const [form, setForm] = useState<ImageEndpointPayload>(() => {
    if (!initial) return { ...EMPTY_FORM }
    return {
      key: initial.key,
      name: initial.name,
      protocol: initial.protocol,
      base_url: initial.base_url,
      model: initial.model,
      auth_mode: initial.auth_mode,
      api_key_env: initial.api_key_env,
      api_key_inline: '',   // 留空 = 不改已有密钥
      capabilities: initial.capabilities,
      params: initial.params,
      max_refs: initial.max_refs,
      timeout_s: initial.timeout_s,
      enabled: initial.enabled,
      priority: initial.priority,
      note: initial.note,
    }
  })
  const [paramsText, setParamsText] = useState(() => JSON.stringify(initial?.params ?? {}, null, 2))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const patch = (next: Partial<ImageEndpointPayload>) => setForm((previous) => ({ ...previous, ...next }))

  const toggleCap = (key: string) => {
    setForm((previous) => ({
      ...previous,
      capabilities: previous.capabilities.includes(key)
        ? previous.capabilities.filter((c) => c !== key)
        : [...previous.capabilities, key],
    }))
  }

  const save = async () => {
    setError('')
    let params: Record<string, unknown> = {}
    try {
      params = paramsText.trim() ? JSON.parse(paramsText) : {}
      if (typeof params !== 'object' || Array.isArray(params)) throw new Error('params 必须是 JSON 对象')
    } catch (err) {
      setError(`参数 JSON 解析失败：${err instanceof Error ? err.message : '格式错误'}`)
      return
    }
    setSaving(true)
    try {
      const payload = { ...form, params }
      const response = initial
        ? await updateImageEndpoint(initial.key, payload)
        : await createImageEndpoint(payload)
      onSaved(response)
      showToast(initial ? '端点已更新' : '端点已添加', 'success')
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message || err?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const field = 'w-full h-8 rounded-lg border border-line bg-panel px-2.5 text-[11px] text-ink outline-none focus:border-flare/60'
  const labelCls = 'block mb-1 font-mono text-[9px] text-ink-subtle uppercase tracking-wider'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onMouseDown={onClose}>
      <div
        className="w-full max-w-2xl max-h-[86vh] overflow-y-auto rounded-2xl border border-line bg-panel shadow-xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-panel px-5 py-3">
          <div>
            <h3 className="text-sm font-medium text-ink">{initial ? '编辑端点' : '添加图像端点'}</h3>
            <p className="text-[10px] text-ink-subtle mt-0.5">密钥推荐用 env 模式只填变量名；inline 会存进数据库但接口不回显明文</p>
          </div>
          <button type="button" onClick={onClose} className="text-ink-subtle hover:text-ink" aria-label="关闭"><X size={16} /></button>
        </header>

        <div className="px-5 py-4 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label>
              <span className={labelCls}>端点 key {initial && '（不可改）'}</span>
              <input
                data-testid="endpoint-key"
                className={cn(field, initial && 'opacity-60')}
                value={form.key ?? ''}
                disabled={!!initial}
                placeholder="例如 seedream-prod"
                onChange={(e) => patch({ key: e.target.value })}
              />
            </label>
            <label>
              <span className={labelCls}>显示名</span>
              <input data-testid="endpoint-name" className={field} value={form.name} placeholder="例如 方舟 · Seedream 4.0" onChange={(e) => patch({ name: e.target.value })} />
            </label>
            <label>
              <span className={labelCls}>协议</span>
              <select data-testid="endpoint-protocol" className={field} value={form.protocol} onChange={(e) => patch({ protocol: e.target.value })}>
                {data.protocols.filter((p) => p.key !== 'mock').map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span className={labelCls}>默认模型名</span>
              <input data-testid="endpoint-model" className={field} value={form.model} placeholder="seedream-4.0 / gpt-image-1" onChange={(e) => patch({ model: e.target.value })} />
            </label>
          </div>

          <label className="block">
            <span className={labelCls}>Base URL</span>
            <input data-testid="endpoint-base-url" className={field} value={form.base_url} placeholder="https://ark.cn-beijing.volces.com/api/v3" onChange={(e) => patch({ base_url: e.target.value })} />
          </label>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label>
              <span className={labelCls}>密钥模式</span>
              <select data-testid="endpoint-auth" className={field} value={form.auth_mode} onChange={(e) => patch({ auth_mode: e.target.value as ImageEndpointPayload['auth_mode'] })}>
                <option value="none">none · 无需认证</option>
                <option value="env">env · 只读环境变量（推荐）</option>
                <option value="inline">inline · 存数据库</option>
              </select>
            </label>
            {form.auth_mode === 'env' ? (
              <label>
                <span className={labelCls}>环境变量名</span>
                <input data-testid="endpoint-key-env" className={field} value={form.api_key_env} placeholder="ARK_API_KEY" onChange={(e) => patch({ api_key_env: e.target.value })} />
              </label>
            ) : form.auth_mode === 'inline' ? (
              <label>
                <span className={labelCls}>API Key {initial && '（留空 = 不改）'}</span>
                <input data-testid="endpoint-key-inline" type="password" className={field} value={form.api_key_inline} placeholder="sk-…" onChange={(e) => patch({ api_key_inline: e.target.value })} />
              </label>
            ) : (
              <div className="flex items-end pb-1 text-[10px] text-ink-subtle">本地自托管服务，请求不带 Authorization 头</div>
            )}
          </div>

          <div>
            <span className={labelCls}>能力标签 · 端点能做什么动作</span>
            <div className="flex flex-wrap gap-1.5">
              {data.capabilities.map((cap) => {
                const active = form.capabilities.includes(cap.key)
                return (
                  <button
                    key={cap.key}
                    type="button"
                    data-testid={`endpoint-cap-${cap.key}`}
                    onClick={() => toggleCap(cap.key)}
                    className={cn(
                      'rounded-pill border px-2.5 py-1 text-[10px] transition-colors',
                      active ? 'border-flare/40 bg-flare/10 text-flare' : 'border-line text-ink-subtle hover:text-ink',
                    )}
                  >
                    {active && <Check size={10} className="inline mr-1" />}{cap.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label>
              <span className={labelCls}>最多参考图</span>
              <input type="number" min={0} max={8} className={field} value={form.max_refs} onChange={(e) => patch({ max_refs: Number(e.target.value) })} />
            </label>
            <label>
              <span className={labelCls}>超时（秒）</span>
              <input type="number" min={3} max={300} className={field} value={form.timeout_s} onChange={(e) => patch({ timeout_s: Number(e.target.value) })} />
            </label>
            <label>
              <span className={labelCls}>优先级（小者先试）</span>
              <input type="number" min={0} max={9998} className={field} value={form.priority} onChange={(e) => patch({ priority: Number(e.target.value) })} />
            </label>
          </div>

          <label className="block">
            <span className={labelCls}>默认参数（JSON，会与任务里的参数合并，任务优先）</span>
            <textarea className="w-full h-20 rounded-lg border border-line bg-panel px-2.5 py-2 font-mono text-[10px] text-ink outline-none focus:border-flare/60" value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
          </label>

          <label className="flex items-center gap-2 text-[11px] text-ink">
            <input type="checkbox" checked={form.enabled} onChange={(e) => patch({ enabled: e.target.checked })} />
            启用（关掉后不会被任何绑定链选中）
          </label>

          {error && (
            <p className="rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-[11px] text-bad">{error}</p>
          )}
        </div>

        <footer className="sticky bottom-0 flex items-center justify-end gap-2 border-t border-line bg-panel px-5 py-3">
          <button type="button" onClick={onClose} className="h-8 px-3 rounded-lg border border-line text-[11px] text-ink-subtle hover:text-ink">取消</button>
          <button
            type="button"
            data-testid="endpoint-save"
            disabled={saving}
            onClick={() => void save()}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-flare text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-50"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            保存端点
          </button>
        </footer>
      </div>
    </div>
  )
}

interface BindingRowProps {
  service: { key: string; label: string }
  capability: string
  data: ImageEndpointsResponse
  draft: string[]
  onChange: (keys: string[]) => void
  onSave: () => void
  saving: boolean
}

function BindingRow({ service, capability, data, draft, onChange, onSave, saving }: BindingRowProps) {
  const available = data.endpoints.filter((e) => e.protocol !== 'mock' && !draft.includes(e.key))
  const dirty = draft.join('|') !== chainKeys(data, service.key, capability).join('|')
  const move = (index: number, delta: number) => {
    const next = [...draft]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }

  return (
    <div data-testid={`binding-${service.key}-${capability || 'default'}`} className="rounded-xl border border-line bg-canvas/40 px-3.5 py-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[12px] font-medium text-ink">{service.label}</span>
        {capability && <span className="rounded-pill border border-iris/30 bg-iris/10 px-2 py-0.5 font-mono text-[9px] text-iris">{capLabel(data, capability)}</span>}
        <span className="font-mono text-[10px] text-ink-subtle">{draft.length} 个候选</span>
        <div className="flex-1" />
        {dirty && (
          <button
            type="button"
            data-testid={`binding-save-${service.key}-${capability || 'default'}`}
            disabled={saving}
            onClick={onSave}
            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-flare text-white text-[10px] hover:opacity-90 disabled:opacity-50"
          >
            <Save size={10} /> 保存链
          </button>
        )}
      </div>

      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        {draft.length === 0 && <span className="text-[10px] text-ink-subtle">未绑定真实端点 → 全部镜头回落占位图</span>}
        {draft.map((key, index) => {
          const ep = data.endpoints.find((e) => e.key === key)
          return (
            <span key={key} className="inline-flex items-center gap-1 rounded-pill border border-flare/30 bg-flare/[0.06] pl-2 pr-1 py-1 text-[10px] text-ink">
              <span className="font-mono text-flare">{index + 1}</span>
              <span className="max-w-[140px] truncate">{ep?.name ?? key}</span>
              <button type="button" aria-label="上移" onClick={() => move(index, -1)} className="text-ink-subtle hover:text-ink"><ArrowUp size={10} /></button>
              <button type="button" aria-label="下移" onClick={() => move(index, 1)} className="text-ink-subtle hover:text-ink"><ArrowDown size={10} /></button>
              <button type="button" aria-label="移除" onClick={() => onChange(draft.filter((k) => k !== key))} className="text-ink-subtle hover:text-bad"><X size={11} /></button>
            </span>
          )
        })}
        {available.length > 0 && (
          <select
            data-testid={`binding-add-${service.key}-${capability || 'default'}`}
            value=""
            onChange={(e) => { if (e.target.value) onChange([...draft, e.target.value]) }}
            className="h-7 rounded-pill border border-line bg-panel px-2 text-[10px] text-ink-subtle outline-none"
          >
            <option value="">+ 添加端点</option>
            {available.map((ep) => <option key={ep.key} value={ep.key}>{ep.name}</option>)}
          </select>
        )}
      </div>
    </div>
  )
}

export default function StudioEndpoints() {
  const { showToast } = useToast()
  const [data, setData] = useState<ImageEndpointsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<ImageEndpoint | 'new' | null>(null)
  const [tests, setTests] = useState<Record<string, ImageEndpointTestResult | 'loading'>>({})
  const [draft, setDraft] = useState<Record<string, string[]>>({})
  const [savingKey, setSavingKey] = useState('')
  const [overrideService, setOverrideService] = useState('retouch')
  const [overrideCap, setOverrideCap] = useState('')

  const load = () => {
    setLoading(true)
    void getImageEndpoints()
      .then((response) => { setData(response); setError('') })
      .catch((err) => setError(err instanceof Error ? err.message : '加载端点失败'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  useEffect(() => {
    if (!data) return
    const next: Record<string, string[]> = {}
    for (const service of data.services) {
      next[`${service.key}|`] = chainKeys(data, service.key)
      for (const cap of data.capabilities) {
        const keys = chainKeys(data, service.key, cap.key)
        if (keys.length) next[`${service.key}|${cap.key}`] = keys
      }
    }
    if (overrideCap) {
      const key = `${overrideService}|${overrideCap}`
      if (!next[key]) next[key] = chainKeys(data, overrideService, overrideCap)
    }
    setDraft(next)
  }, [data, overrideService, overrideCap])

  const realEndpoints = useMemo(
    () => (data?.endpoints ?? []).filter((e) => e.protocol !== 'mock'),
    [data],
  )

  const apply = (response: ImageEndpointsResponse) => setData(response)

  const runTest = async (key: string) => {
    setTests((previous) => ({ ...previous, [key]: 'loading' }))
    try {
      const result = await testImageEndpoint(key)
      setTests((previous) => ({ ...previous, [key]: result }))
      showToast(result.ok ? '端点连通正常' : result.detail, result.ok ? 'success' : 'warning')
    } catch (err: any) {
      const result: ImageEndpointTestResult = {
        ok: false, key, detail: err?.response?.data?.detail?.message || err?.message || '测试失败',
      }
      setTests((previous) => ({ ...previous, [key]: result }))
    }
  }

  const remove = async (endpoint: ImageEndpoint) => {
    if (!window.confirm(`删除端点「${endpoint.name}」？相关服务绑定也会一并移除。`)) return
    try {
      apply(await deleteImageEndpoint(endpoint.key))
      showToast('端点已删除', 'success')
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '删除失败', 'error')
    }
  }

  const saveChain = async (service: string, capability: string) => {
    const key = `${service}|${capability}`
    setSavingKey(key)
    try {
      apply(await setImageBindings(service, draft[key] ?? [], capability))
      showToast('候选链已保存，下一次出图即按新链分派', 'success')
    } catch (err: any) {
      showToast(err?.response?.data?.detail?.message || '保存失败', 'error')
    } finally {
      setSavingKey('')
    }
  }

  const setChain = (service: string, capability: string, keys: string[]) => {
    setDraft((previous) => ({ ...previous, [`${service}|${capability}`]: keys }))
  }

  if (loading) {
    return <div className="flex-1 min-h-0 flex items-center justify-center gap-2 bg-panel text-ink-subtle text-xs"><Loader2 size={14} className="animate-spin" /> 正在读取端点池…</div>
  }
  if (error || !data) {
    return (
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 bg-panel">
        <AlertCircle size={22} className="text-warn" />
        <p className="text-sm text-ink">无法读取图像端点</p>
        <p className="text-[11px] text-ink-subtle">{error}</p>
        <button type="button" onClick={load} className="h-8 px-3 rounded-lg border border-line text-[11px] text-ink">重试</button>
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-panel">
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-5">
        <section className="rounded-xl border border-iris/25 bg-iris/[0.05] px-4 py-3">
          <div className="flex items-center gap-2"><KeyRound size={14} className="text-iris" /><h3 className="text-[12px] font-medium text-ink">端点不是「一个功能配一个模型」</h3></div>
          <p className="mt-1.5 text-[11px] text-ink-subtle leading-relaxed">
            当前 {realEndpoints.length} 个真实端点 · 8 类图片处理能力 · 内置占位图永远兜底。
            端点池里可以有任意多个服务，每个声明自己能做什么（抠图 / 换背景 / 超分 / 风格迁移…）；
            下面每个服务绑定一条<strong className="text-ink font-medium">有序候选链</strong>，第一个失败就自动试下一个。
            真正用哪个在运行时定：镜头的能力标签决定去找哪类端点，出图任务里还能临时指定、但不砍掉 fallback。
            密钥推荐 env 模式只存变量名，本页不回显明文。
          </p>
        </section>

        <section>
          <div className="mb-2.5 flex items-baseline gap-2">
            <h3 className="text-[12px] font-medium text-ink">端点池</h3>
            <span className="text-[10px] text-ink-subtle">按优先级排，数字小的先试</span>
            <span className="flex-1 h-px bg-line/70" />
            <span className="font-mono text-[10px] text-ink-subtle">{data.endpoints.length}</span>
            <button
              type="button"
              data-testid="endpoint-add"
              onClick={() => setEditing('new')}
              className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-lg bg-flare text-white text-[10px] font-medium hover:opacity-90 flex-shrink-0"
            >
              <Plus size={11} /> 添加端点
            </button>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
            {data.endpoints.map((endpoint) => {
              const isMock = endpoint.protocol === 'mock'
              const test = tests[endpoint.key]
              return (
                <div key={endpoint.key} data-testid={`endpoint-card-${endpoint.key}`} className={cn('rounded-xl border px-3.5 py-3', isMock ? 'border-line bg-canvas/30' : 'border-line bg-canvas/40')}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <h4 className="text-[12px] font-medium text-ink truncate">{endpoint.name}</h4>
                        <span className="rounded-pill border border-line px-2 py-0.5 font-mono text-[9px] text-ink-subtle">{PROTOCOL_SHORT[endpoint.protocol] ?? endpoint.protocol}</span>
                        {!endpoint.enabled && <span className="rounded-pill border border-warn/30 bg-warn/10 px-2 py-0.5 font-mono text-[9px] text-warn">已停用</span>}
                      </div>
                      <p className="mt-1 font-mono text-[10px] text-ink-subtle truncate" title={endpoint.base_url}>{endpoint.base_url || '（内置）'} {endpoint.model && `· ${endpoint.model}`}</p>
                    </div>
                    <span className={cn('rounded-pill border px-2 py-0.5 font-mono text-[9px] flex-shrink-0', endpoint.secret_ready ? 'border-ok/30 bg-ok/10 text-ok' : 'border-warn/30 bg-warn/10 text-warn')}>
                      {isMock ? '兜底' : endpoint.secret_ready ? '密钥就绪' : '密钥缺失'}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {endpoint.capabilities.map((cap) => (
                      <span key={cap} className="rounded-md bg-panel-2/70 px-1.5 py-0.5 text-[9px] text-ink-subtle">{capLabel(data, cap)}</span>
                    ))}
                  </div>
                  <div className="mt-2 flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[9px] text-ink-subtle">密钥 {endpoint.secret_source} {endpoint.secret_masked}</span>
                    <div className="flex-1" />
                    {!isMock && (
                      <>
                        <button type="button" data-testid={`endpoint-test-${endpoint.key}`} disabled={test === 'loading'} onClick={() => void runTest(endpoint.key)} className="inline-flex items-center gap-1 text-[10px] text-ink-subtle hover:text-ink">
                          {test === 'loading' ? <Loader2 size={10} className="animate-spin" /> : <Play size={10} />} 测试
                        </button>
                        <button type="button" data-testid={`endpoint-edit-${endpoint.key}`} onClick={() => setEditing(endpoint)} className="inline-flex items-center gap-1 text-[10px] text-ink-subtle hover:text-ink"><Pencil size={10} /> 编辑</button>
                        <button type="button" data-testid={`endpoint-delete-${endpoint.key}`} onClick={() => void remove(endpoint)} className="inline-flex items-center gap-1 text-[10px] text-ink-subtle hover:text-bad"><Trash2 size={10} /> 删除</button>
                      </>
                    )}
                  </div>
                  {test && test !== 'loading' && (
                    <p className={cn('mt-2 rounded-lg border px-2.5 py-1.5 text-[10px]', test.ok ? 'border-ok/30 bg-ok/[0.06] text-ok' : 'border-warn/30 bg-warn/[0.06] text-warn')}>
                      {test.ok ? `连通正常${test.latency_ms != null ? ` · ${test.latency_ms} ms` : ''}` : test.detail}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </section>

        <section>
          <div className="mb-2.5 flex items-baseline gap-2">
            <h3 className="text-[12px] font-medium text-ink">服务绑定 · 默认候选链</h3>
            <span className="text-[10px] text-ink-subtle">顺序即 fallback 顺序，链尾自动接内置占位图</span>
          </div>
          <div className="space-y-2">
            {data.services.map((service) => (
              <BindingRow
                key={service.key}
                service={service}
                capability=""
                data={data}
                draft={draft[`${service.key}|`] ?? []}
                onChange={(keys) => setChain(service.key, '', keys)}
                onSave={() => void saveChain(service.key, '')}
                saving={savingKey === `${service.key}|`}
              />
            ))}
          </div>
        </section>

        <section>
          <div className="mb-2.5 flex items-baseline gap-2">
            <h3 className="text-[12px] font-medium text-ink">按能力覆盖（可选）</h3>
            <span className="text-[10px] text-ink-subtle">给某个动作单独配链，优先于默认链</span>
          </div>
          <div className="flex items-center gap-2 mb-2">
            <select data-testid="override-service" className="h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink" value={overrideService} onChange={(e) => setOverrideService(e.target.value)}>
              {data.services.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <select data-testid="override-capability" className="h-8 rounded-lg border border-line bg-panel px-2 text-[11px] text-ink" value={overrideCap} onChange={(e) => setOverrideCap(e.target.value)}>
              <option value="">选择动作</option>
              {data.capabilities.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
            <span className="inline-flex items-center gap-1 text-[10px] text-ink-subtle"><Info size={11} /> 例如「精修 / 换背景」单独走抠图端点</span>
          </div>
          {overrideCap ? (
            <BindingRow
              service={data.services.find((s) => s.key === overrideService) ?? data.services[0]}
              capability={overrideCap}
              data={data}
              draft={draft[`${overrideService}|${overrideCap}`] ?? []}
              onChange={(keys) => setChain(overrideService, overrideCap, keys)}
              onSave={() => void saveChain(overrideService, overrideCap)}
              saving={savingKey === `${overrideService}|${overrideCap}`}
            />
          ) : (
            <p className="rounded-xl border border-dashed border-line px-4 py-4 text-center text-[11px] text-ink-subtle">选一个动作，为它单独配候选链；留空时所有动作都用上面的默认链</p>
          )}
        </section>
        <div className="h-4" />
      </div>

      {editing && (
        <EndpointModal
          initial={editing === 'new' ? null : editing}
          data={data}
          onClose={() => setEditing(null)}
          onSaved={apply}
        />
      )}
    </div>
  )
}
