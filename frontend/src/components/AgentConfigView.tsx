/**
 * AgentConfigView — Agent & Skill/MCP 配置管理页
 *
 * 左侧：子 Agent 列表（注册 / 编辑 / 启用禁用），调用 /api/agent/list、/register、/update/{id}
 * 右侧：已注册工具（Skill/MCP）列表，只读，调用 /api/agent/tools
 *
 * 创建/编辑弹窗支持绑定 Skill / MCP Server 工具（多选）。
 */
import { useState, useEffect, useCallback } from 'react'
import { Plus, Pencil, Trash2, Play, Pause, RefreshCw, Wrench, Bot } from 'lucide-react'
import { cn } from '../utils'
import { useToast } from '../contexts/ToastContext'
import {
  listAgentConfigs,
  registerAgent,
  updateAgent,
  listTools,
  listAvailableTools,
  type AgentConfig,
  type AgentTool,
  type AvailableSkillOption,
  type AvailableMcpOption,
} from '../api'

// ── 状态颜色 ──────────────────────────────────────────────────────────────────
const STATUS_STYLE: Record<string, { bg: string; text: string; border: string; label: string }> = {
  active:   { bg: 'bg-ok/15',  text: 'text-ok', border: 'border-ok/30', label: '运行中' },
  inactive: { bg: 'bg-panel-2/15',   text: 'text-ink-muted',  border: 'border-line/30',  label: '已停用' },
  draft:    { bg: 'bg-warn/15',  text: 'text-warn', border: 'border-warn/30', label: '草稿' },
}

const AGENT_TYPE_LABEL: Record<string, string> = {
  faq: 'FAQ 问答', dialogue: '多轮对话', ticket: '工单处理', complaint: '投诉安抚',
}

const MCP_STATUS_STYLE: Record<string, { text: string; dot: string }> = {
  connected:  { text: 'text-ok',   dot: 'bg-ok' },
  disconnected: { text: 'text-ink-muted',  dot: 'bg-panel-2' },
  error:      { text: 'text-bad',     dot: 'bg-bad' },
}

// ── 表单字段 ──────────────────────────────────────────────────────────────────
interface AgentForm {
  agent_id: string
  name: string
  description: string
  agent_type: string
  priority: number
  supported_intents: string
  supported_emotions: string
  status: 'active' | 'inactive' | 'draft'
  skill_ids: string[]
  mcp_server_ids: string[]
}

const EMPTY_FORM: AgentForm = {
  agent_id: '', name: '', description: '', agent_type: 'faq',
  priority: 50, supported_intents: '', supported_emotions: '', status: 'active',
  skill_ids: [], mcp_server_ids: [],
}

type ModalMode = 'create' | 'edit' | null

export default function AgentConfigView() {
  const { showSuccess, showError } = useToast()
  const [agents, setAgents] = useState<AgentConfig[]>([])
  const [tools, setTools] = useState<AgentTool[]>([])
  const [loading, setLoading] = useState(true)
  const [modalMode, setModalMode] = useState<ModalMode>(null)
  const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null)
  const [form, setForm] = useState<AgentForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [available, setAvailable] = useState<{ skills: AvailableSkillOption[]; mcp_servers: AvailableMcpOption[] }>({ skills: [], mcp_servers: [] })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [a, t, av] = await Promise.all([listAgentConfigs(), listTools(), listAvailableTools()])
      setAgents(a.agents ?? [])
      setTools(t)
      setAvailable(av)
    } catch (e: any) {
      showError('加载失败：' + (e?.response?.data?.detail ?? e?.message))
    } finally {
      setLoading(false)
    }
  }, [showError])

  useEffect(() => { load() }, [load])

  const openCreate = () => {
    setEditingAgent(null)
    setForm(EMPTY_FORM)
    setModalMode('create')
  }
  const openEdit = (agent: AgentConfig) => {
    setEditingAgent(agent)
    setForm({
      agent_id: agent.agent_id,
      name: agent.name,
      description: agent.description ?? '',
      agent_type: agent.agent_type,
      priority: agent.priority,
      supported_intents: (agent.supported_intents ?? []).join(', '),
      supported_emotions: (agent.supported_emotions ?? []).join(', '),
      status: agent.status,
      skill_ids: agent.skill_ids ?? [],
      mcp_server_ids: agent.mcp_server_ids ?? [],
    })
    setModalMode('edit')
  }
  const closeModal = () => { setModalMode(null); setEditingAgent(null) }

  const handleSave = async () => {
    if (!form.agent_id.trim() || !form.name.trim()) {
      showError('agent_id 和名称为必填项')
      return
    }
    setSaving(true)
    try {
      const payload = {
        name: form.name,
        description: form.description || undefined,
        agent_type: form.agent_type,
        supported_intents: form.supported_intents.split(',').map(s => s.trim()).filter(Boolean),
        supported_emotions: form.supported_emotions.split(',').map(s => s.trim()).filter(Boolean),
        priority: form.priority,
        status: form.status,
        skill_ids: form.skill_ids,
        mcp_server_ids: form.mcp_server_ids,
      }
      if (modalMode === 'create') {
        await registerAgent({ ...payload, agent_id: form.agent_id })
        showSuccess(`Agent "${form.name}" 注册成功`)
      } else {
        await updateAgent(editingAgent!.agent_id, payload)
        showSuccess(`Agent "${form.name}" 已更新`)
      }
      closeModal()
      load()
    } catch (e: any) {
      showError('保存失败：' + (e?.response?.data?.detail ?? e?.message))
    } finally {
      setSaving(false)
    }
  }

  const handleToggleStatus = async (agent: AgentConfig) => {
    const nextStatus = agent.status === 'active' ? 'inactive' : 'active'
    try {
      await updateAgent(agent.agent_id, { status: nextStatus })
      showSuccess(`已${nextStatus === 'active' ? '启用' : '停用'} ${agent.name}`)
      load()
    } catch (e: any) {
      showError('操作失败：' + (e?.response?.data?.detail ?? e?.message))
    }
  }

  const handleDelete = async (agent: AgentConfig) => {
    if (!confirm(`确认注销 Agent「${agent.name}」？`)) return
    try {
      await updateAgent(agent.agent_id, { status: 'inactive' })
      showSuccess(`已注销 ${agent.name}`)
      load()
    } catch (e: any) {
      showError('操作失败：' + (e?.response?.data?.detail ?? e?.message))
    }
  }

  return (
    <div className="flex gap-4 h-full min-h-0">
      {/* 左侧：Agent 管理 */}
      <div className="flex-1 min-w-0 flex flex-col bg-panel-2/50 rounded-xl border border-line overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between border-b border-line flex-shrink-0">
          <div className="flex items-center gap-2">
            <Bot size={16} className="text-info" />
            <span className="font-medium text-ink text-sm">子 Agent 管理</span>
            <span className="text-xs text-ink-subtle">{agents.length} 个</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={load} disabled={loading} className="p-1.5 rounded-lg hover:bg-line text-ink-muted transition-colors" title="刷新">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={openCreate}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-iris hover:bg-iris text-ink rounded-lg transition-colors"
            >
              <Plus size={13} /> 注册 Agent
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading ? (
            <div className="flex justify-center py-12"><RefreshCw size={20} className="animate-spin text-ink-subtle" /></div>
          ) : agents.length === 0 ? (
            <div className="text-center py-12 text-ink-subtle text-sm">暂无 Agent，点击右上角注册</div>
          ) : (
            agents.map((a) => {
              const st = STATUS_STYLE[a.status] ?? STATUS_STYLE.inactive
              return (
                <div key={a.agent_id} className={cn('flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-colors hover:bg-line/50', st.border)}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink text-sm truncate">{a.name}</span>
                      <span className={cn('px-1.5 py-0.5 text-[10px] rounded border', st.bg, st.text, st.border)}>{st.label}</span>
                      <span className="text-[10px] text-ink-subtle">{AGENT_TYPE_LABEL[a.agent_type] ?? a.agent_type}</span>
                    </div>
                    {a.description && (
                      <p className="text-xs text-ink-subtle mt-0.5 truncate">{a.description}</p>
                    )}
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-ink-subtle">
                      {a.supported_intents?.length > 0 && (
                        <span>意图: {a.supported_intents.slice(0, 3).join(', ')}{a.supported_intents.length > 3 ? '…' : ''}</span>
                      )}
                      <span>优先级 {a.priority}</span>
                      {(a.skill_ids?.length ?? 0) > 0 && (
                        <span title={`技能: ${(a.skill_ids ?? []).join(', ')}`}>🔧 {(a.skill_ids ?? []).length}</span>
                      )}
                      {(a.mcp_server_ids?.length ?? 0) > 0 && (
                        <span title={`MCP: ${(a.mcp_server_ids ?? []).join(', ')}`}>📡 {(a.mcp_server_ids ?? []).length}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button onClick={() => openEdit(a)} className="p-1.5 rounded hover:bg-line-strong text-ink-muted hover:text-ink transition-colors" title="编辑">
                      <Pencil size={13} />
                    </button>
                    <button onClick={() => handleToggleStatus(a)} className={cn('p-1.5 rounded hover:bg-line-strong transition-colors', a.status === 'active' ? 'text-warn hover:text-warn' : 'text-ok hover:text-ok')} title={a.status === 'active' ? '停用' : '启用'}>
                      {a.status === 'active' ? <Pause size={13} /> : <Play size={13} />}
                    </button>
                    <button onClick={() => handleDelete(a)} className="p-1.5 rounded hover:bg-bad/20 text-ink-muted hover:text-bad transition-colors" title="注销">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* 右侧：Skill/MCP 工具列表 */}
      <div className="w-80 flex-shrink-0 flex flex-col bg-panel-2/50 rounded-xl border border-line overflow-hidden">
        <div className="px-4 py-3 flex items-center gap-2 border-b border-line flex-shrink-0">
          <Wrench size={16} className="text-warn" />
          <span className="font-medium text-ink text-sm">Skill / MCP 工具</span>
          <span className="text-xs text-ink-subtle ml-auto">{tools.length} 个</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading ? (
            <div className="flex justify-center py-12"><RefreshCw size={20} className="animate-spin text-ink-subtle" /></div>
          ) : tools.length === 0 ? (
            <div className="text-center py-12 text-ink-subtle text-sm">暂无工具</div>
          ) : (
            tools.map((t) => (
              <div key={t.tool_name} className="px-3 py-2.5 rounded-lg border border-line bg-panel/60">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-info bg-iris/10 px-1.5 py-0.5 rounded">{t.tool_name}</span>
                </div>
                {t.description && (
                  <p className="text-[11px] text-ink-subtle mt-1 leading-relaxed">{t.description}</p>
                )}
                {Object.keys(t.parameters ?? {}).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {Object.entries(t.parameters).map(([k, v]: [string, any]) => (
                      <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-line text-ink-subtle font-mono">{k}:{v?.type ?? 'any'}</span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
        <div className="px-4 py-2.5 border-t border-line text-[10px] text-ink-subtle">
          工具由 ToolRegistry 单例管理，Agent 通过 tool_name 按需调用
        </div>
      </div>

      {/* 创建/编辑弹窗 */}
      {modalMode && (
        <AgentFormModal
          mode={modalMode}
          form={form}
          editingAgent={editingAgent}
          availableSkills={available.skills}
          availableMcpServers={available.mcp_servers}
          onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
          onSave={handleSave}
          onClose={closeModal}
          saving={saving}
        />
      )}
    </div>
  )
}

// ── 弹窗 ──────────────────────────────────────────────────────────────────────
function AgentFormModal({
  mode, form, editingAgent, availableSkills, availableMcpServers,
  onChange, onSave, onClose, saving,
}: {
  mode: ModalMode
  form: AgentForm
  editingAgent: AgentConfig | null
  availableSkills: AvailableSkillOption[]
  availableMcpServers: AvailableMcpOption[]
  onChange: (patch: Partial<AgentForm>) => void
  onSave: () => void
  onClose: () => void
  saving: boolean
}) {
  const isCreate = mode === 'create'

  const toggleSkill = (id: string) => {
    const cur = form.skill_ids ?? []
    onChange({ skill_ids: cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id] })
  }
  const toggleMcp = (id: string) => {
    const cur = form.mcp_server_ids ?? []
    onChange({ mcp_server_ids: cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id] })
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-scrim/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-canvas border border-line rounded-2xl shadow-2xl overflow-hidden animate-scale-in mx-4">
        <div className="px-6 py-4 border-b border-line flex items-center justify-between">
          <h3 className="text-base font-bold text-ink">{isCreate ? '注册新 Agent' : `编辑 ${editingAgent?.name}`}</h3>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-line text-ink-muted hover:text-ink transition-colors">
            <span className="text-lg leading-none">×</span>
          </button>
        </div>
        <div className="px-6 py-4 space-y-3 max-h-[65vh] overflow-y-auto">
          {/* 基础信息 */}
          {!isCreate && (
            <div>
              <label className="block text-xs text-ink-subtle mb-1">Agent ID（不可修改）</label>
              <input value={form.agent_id} readOnly className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink-subtle text-sm cursor-not-allowed" />
            </div>
          )}
          {isCreate && (
            <div>
              <label className="block text-xs text-ink-subtle mb-1">Agent ID <span className="text-bad">*</span></label>
              <input value={form.agent_id} onChange={(e) => onChange({ agent_id: e.target.value })} placeholder="如：my_custom_agent"
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm placeholder-ink-subtle focus:outline-none focus:border-iris/50" />
            </div>
          )}
          <div>
            <label className="block text-xs text-ink-subtle mb-1">名称 <span className="text-bad">*</span></label>
            <input value={form.name} onChange={(e) => onChange({ name: e.target.value })} placeholder="如：退款处理专家"
              className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm placeholder-ink-subtle focus:outline-none focus:border-iris/50" />
          </div>
          <div>
            <label className="block text-xs text-ink-subtle mb-1">描述</label>
            <input value={form.description} onChange={(e) => onChange({ description: e.target.value })} placeholder="Agent 职责描述"
              className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm placeholder-ink-subtle focus:outline-none focus:border-iris/50" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-subtle mb-1">类型</label>
              <select value={form.agent_type} onChange={(e) => onChange({ agent_type: e.target.value })}
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm focus:outline-none focus:border-iris/50">
                <option value="faq">FAQ 问答</option>
                <option value="dialogue">多轮对话</option>
                <option value="ticket">工单处理</option>
                <option value="complaint">投诉安抚</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-ink-subtle mb-1">优先级（数字越小越高）</label>
              <input type="number" value={form.priority} onChange={(e) => onChange({ priority: Number(e.target.value) })}
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm focus:outline-none focus:border-iris/50" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-subtle mb-1">支持意图（逗号分隔）</label>
              <input value={form.supported_intents} onChange={(e) => onChange({ supported_intents: e.target.value })} placeholder="order_status,product_info"
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm placeholder-ink-subtle focus:outline-none focus:border-iris/50" />
            </div>
            <div>
              <label className="block text-xs text-ink-subtle mb-1">支持情绪（逗号分隔）</label>
              <input value={form.supported_emotions} onChange={(e) => onChange({ supported_emotions: e.target.value })} placeholder="anger,anxiety"
                className="w-full px-3 py-2 bg-panel-2 border border-line-strong rounded-lg text-ink text-sm placeholder-ink-subtle focus:outline-none focus:border-iris/50" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-ink-subtle mb-1">状态</label>
            <div className="flex gap-2">
              {(['active', 'inactive', 'draft'] as const).map((s) => (
                <button key={s} onClick={() => onChange({ status: s })}
                  className={cn('px-3 py-1.5 rounded-lg text-xs border transition-colors',
                    form.status === s
                      ? 'bg-iris/20 text-info border-iris/40'
                      : 'bg-panel-2 text-ink-subtle border-line-strong hover:text-ink')}>
                  {{ active: '运行中', inactive: '已停用', draft: '草稿' }[s]}
                </button>
              ))}
            </div>
          </div>

          {/* 绑定 Skill 工具 */}
          <div>
            <label className="block text-xs text-ink-subtle mb-1.5">
              绑定 Skill 工具
              <span className="ml-1 text-ink-subtle">（{form.skill_ids?.length ?? 0}/{availableSkills.length}）</span>
            </label>
            {availableSkills.length === 0 ? (
              <p className="text-[11px] text-ink-subtle italic py-1">暂无可用 Skill，请到「技能」页签上传/创建</p>
            ) : (
              <div className="max-h-32 overflow-y-auto border border-line rounded-lg p-2 space-y-1 bg-panel/40">
                {availableSkills.map((sk) => (
                  <label key={sk.id} className="flex items-center gap-2 text-xs text-ink cursor-pointer hover:text-ink py-0.5">
                    <input
                      type="checkbox"
                      checked={(form.skill_ids ?? []).includes(sk.id)}
                      onChange={() => toggleSkill(sk.id)}
                      className="rounded border-line-strong bg-panel-2 text-info focus:ring-iris/30"
                    />
                    <span className="font-mono text-info">{sk.id}</span>
                    <span className="text-ink-subtle truncate">{sk.description}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* 绑定 MCP Server */}
          <div>
            <label className="block text-xs text-ink-subtle mb-1.5">
              绑定 MCP Server
              <span className="ml-1 text-ink-subtle">（{form.mcp_server_ids?.length ?? 0}/{availableMcpServers.length}）</span>
            </label>
            {availableMcpServers.length === 0 ? (
              <p className="text-[11px] text-ink-subtle italic py-1">暂无可用 MCP Server，请到「MCP 配置」页签添加</p>
            ) : (
              <div className="max-h-32 overflow-y-auto border border-line rounded-lg p-2 space-y-1 bg-panel/40">
                {availableMcpServers.map((ms) => {
                  const style = MCP_STATUS_STYLE[ms.status?.startsWith('error') ? 'error' : ms.status] ?? MCP_STATUS_STYLE.disconnected
                  return (
                    <label key={ms.id} className="flex items-center gap-2 text-xs text-ink cursor-pointer hover:text-ink py-0.5">
                      <input
                        type="checkbox"
                        checked={(form.mcp_server_ids ?? []).includes(ms.id)}
                        onChange={() => toggleMcp(ms.id)}
                        className="rounded border-line-strong bg-panel-2 text-info focus:ring-iris/30"
                      />
                      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', style.dot)} />
                      <span className="font-mono text-info">{ms.id}</span>
                      <span className="text-ink-subtle truncate flex-1">{ms.description}</span>
                      <span className={cn('text-[10px]', style.text)}>{ms.status}</span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>
        </div>
        <div className="px-6 py-4 border-t border-line/50 bg-panel/50 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 rounded-xl border border-line-strong text-ink hover:text-ink hover:bg-panel-2/50 transition-all text-sm">
            取消
          </button>
          <button onClick={onSave} disabled={saving}
            className="px-4 py-2 rounded-xl bg-iris hover:bg-iris text-ink text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
            {saving ? '保存中…' : (isCreate ? '注册' : '保存')}
          </button>
        </div>
      </div>
    </div>
  )
}
