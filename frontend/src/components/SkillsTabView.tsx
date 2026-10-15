/**
 * SkillsTabView — 统一 Skills / MCP 两个页签的管理视图
 *
 * 参考 DataClaw frontend/src/pages/Skills.tsx：
 * - 顶部 2 个 tab：Skills | MCP（Agent 页签由 AgentConfigView 独立管理）
 * - Skills：列表 + 新建/编辑弹窗 + 文件上传（.md / .zip / .tar.gz）+ 来源筛选
 * - MCP：列表 + 自动健康检查（Zustand store 每 60s 轮询）+ headers 字段支持
 */
import React, { useState, useEffect } from 'react'
import {
  Plus, Edit2, Trash2, Save, X, Activity, CheckCircle2, XCircle,
  FileText, Upload, Tag, RefreshCw,
} from 'lucide-react'
import { useToast } from '../contexts/ToastContext'
import ConfirmDialog from './ConfirmDialog'
import {
  listSkills, createSkill, updateSkill, deleteSkill,
  createMcpServer, updateMcpServer, deleteMcpServer,
  type SkillItem, type SkillCreatePayload,
  type McpServer, type McpServerCreatePayload, type McpServerUpdatePayload,
} from '../api'
import { useMcpHealthStore } from '../store/mcpHealthStore'

type TabKey = 'skills' | 'mcp'

interface SkillsTabViewProps {
  projectId?: number | null
}

const SOURCE_LABELS: Record<string, string> = {
  system_builtin: '系统内置',
  backend_generated: '后端生成',
  local_import: '本地导入',
  uploaded_file: '上传文件',
}

const MCP_TYPE_LABELS: Record<string, string> = {
  stdio: 'stdio',
  sse: 'SSE',
  streamableHttp: 'HTTP',
}

const MCP_STATUS_CFG: Record<string, { label: string; color: string; icon: 'check' | 'x' }> = {
  connected: { label: '已连接', color: 'text-green-400 bg-green-900/30', icon: 'check' },
  disconnected: { label: '未连接', color: 'text-gray-400 bg-gray-700/40', icon: 'x' },
  'error: config incomplete': { label: '配置不完整', color: 'text-red-400 bg-red-900/30', icon: 'x' },
}

function getMcpStatusCfg(status: string) {
  return MCP_STATUS_CFG[status] ?? { label: status || '未知', color: 'text-gray-400 bg-gray-700/40', icon: 'x' }
}

// ==================== 主组件 ====================

export default function SkillsTabView({ projectId }: SkillsTabViewProps) {
  const [tab, setTab] = useState<TabKey>('skills')
  const { hasMcpError, startPolling, stopPolling } = useMcpHealthStore()

  useEffect(() => {
    if (tab === 'mcp') {
      startPolling(projectId ?? null)
    } else {
      stopPolling()
    }
    return () => stopPolling()
  }, [tab, projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleTabChange = (t: TabKey) => {
    if (t === 'mcp') {
      startPolling(projectId ?? null)
    } else {
      stopPolling()
    }
    setTab(t)
  }

  return (
    <div className="flex flex-col h-full">
      {/* 页签导航 */}
      <div className="flex gap-1 border-b border-dark-600 mb-4 flex-shrink-0">
        <TabBtn active={tab === 'skills'} onClick={() => handleTabChange('skills')} icon={FileText}>
          Skills
        </TabBtn>
        <TabBtn active={tab === 'mcp'} onClick={() => handleTabChange('mcp')} icon={Activity}>
          MCP
          {hasMcpError && <span className="ml-1 w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />}
        </TabBtn>
      </div>

      {/* 内容区 */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'skills' && <SkillsPanel projectId={projectId} />}
        {tab === 'mcp' && <McpPanel projectId={projectId} />}
      </div>
    </div>
  )
}

// ==================== Tab 按钮 ====================

function TabBtn({
  active, onClick, icon: Icon, children,
}: {
  active: boolean; onClick: () => void; icon: React.ElementType; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
        active
          ? 'bg-dark-700 text-gray-100 border-b-2 border-accent-primary'
          : 'text-gray-500 hover:text-gray-300 hover:bg-dark-700/50'
      }`}
    >
      <Icon size={14} />
      {children}
    </button>
  )
}

// ==================== Skills 面板 ====================

function SkillsPanel({ projectId }: { projectId?: number | null }) {
  const { showSuccess, showError } = useToast()
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [loading, setLoading] = useState(false)
  const [sourceFilter, setSourceFilter] = useState<string>('all')

  const [dialogMode, setDialogMode] = useState<'create' | 'edit' | null>(null)
  const [editSkillId, setEditSkillId] = useState<string | null>(null)
  const [dialogForm, setDialogForm] = useState<SkillCreatePayload>({
    id: '', name: '', description: null, content: '',
    type: 'agentskill', project_id: projectId ?? null,
    source: 'local_import', status: 'safe', file_path: null,
  })

  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean; title: string; message: string; onConfirm: () => void
  }>({ isOpen: false, title: '', message: '', onConfirm: () => {} })

  // 上传相关
  const [uploading, setUploading] = useState(false)
  const fileInputRef = React.useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await listSkills(projectId)
      setSkills(data)
    } catch (e: any) {
      showError(`加载技能列表失败: ${e?.response?.data?.detail ?? e.message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [projectId])

  const filtered = sourceFilter === 'all'
    ? skills
    : skills.filter(s => s.source === sourceFilter)

  const openCreate = () => {
    setDialogMode('create')
    setEditSkillId(null)
    setDialogForm({
      id: '', name: '', description: null, content: '',
      type: 'agentskill', project_id: projectId ?? null,
      source: 'local_import', status: 'safe', file_path: null,
    })
  }

  const openEdit = (skill: SkillItem) => {
    setDialogMode('edit')
    setEditSkillId(skill.id)
    setDialogForm({
      id: skill.id,
      name: skill.name,
      description: skill.description,
      content: skill.content,
      type: skill.type,
      project_id: skill.project_id ?? null,
      source: skill.source as any,
      status: skill.status,
      file_path: null,
    })
  }

  const closeDialog = () => setDialogMode(null)

  const saveCreate = async () => {
    const form = dialogForm as SkillCreatePayload
    if (!form.id?.trim()) { showError('Skill ID 不能为空'); return }
    if (!form.name?.trim()) { showError('名称不能为空'); return }
    try {
      await createSkill(form)
      closeDialog()
      await load()
      showSuccess('技能已创建')
    } catch (e: any) {
      showError(`创建失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const saveEdit = async () => {
    if (!editSkillId) return
    const form = dialogForm as any
    if (!form.name?.trim()) { showError('名称不能为空'); return }
    try {
      await updateSkill(editSkillId, form)
      closeDialog()
      await load()
      showSuccess('技能已更新')
    } catch (e: any) {
      showError(`保存失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const handleDelete = (skill: SkillItem) => {
    setConfirmDialog({
      isOpen: true,
      title: `删除技能「${skill.name}」`,
      message: `确定要删除技能「${skill.name}」吗？此操作不可恢复。`,
      onConfirm: async () => {
        try {
          await deleteSkill(skill.id)
          await load()
          showSuccess('技能已删除')
        } catch (e: any) {
          showError(`删除失败: ${e?.response?.data?.detail ?? e.message}`)
        }
      },
    })
  }

  // 文件上传处理
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!['.md', '.zip', '.tar.gz'].includes(ext)) {
      showError(`不支持的文件类型：${ext}，仅支持 .md / .zip / .tar.gz`)
      return
    }
    setUploading(true)
    try {
      const content = await file.text()
      const timestamp = Date.now()
      const id = `skill_${timestamp}`
      try {
        await createSkill({
          id,
          name: file.name.replace(/\.(md|zip|tar\.gz)$/, '') || `skill_${timestamp}`,
          description: null,
          content,
          type: 'agentskill',
          project_id: projectId ?? null,
          source: 'uploaded_file',
          status: 'safe',
          file_path: null,
        })
        await load()
        showSuccess(`已上传并创建技能：${file.name}`)
      } catch (err: any) {
        showError(`上传失败: ${err?.response?.data?.detail ?? err.message}`)
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <FileText className="text-blue-400" size={18} />
          <span className="text-gray-200 font-semibold">Skills</span>
          <span className="text-xs text-gray-500 bg-dark-700 px-2 py-0.5 rounded-full">{skills.length} 个技能</span>
        </div>
        <div className="flex items-center gap-2">
          {/* 来源筛选 */}
          <select
            value={sourceFilter}
            onChange={e => setSourceFilter(e.target.value)}
            className="px-2 py-1 bg-dark-700 border border-dark-500 rounded text-xs text-gray-300 focus:outline-none"
          >
            <option value="all">全部来源</option>
            <option value="system_builtin">系统内置</option>
            <option value="backend_generated">后端生成</option>
            <option value="local_import">本地导入</option>
            <option value="uploaded_file">上传文件</option>
          </select>
          {/* 上传按钮 */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".md,.zip,.tar.gz"
            className="hidden"
            onChange={handleFileUpload}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-2 py-1 bg-dark-700 hover:bg-dark-600 border border-dark-500 rounded text-xs text-gray-300 flex items-center gap-1 disabled:opacity-50"
            title="上传 .md / .zip / .tar.gz 技能文件"
          >
            <Upload size={12} />
            {uploading ? '上传中...' : '上传'}
          </button>
          <button
            onClick={openCreate}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-md flex items-center gap-1 transition-colors"
          >
            <Plus size={14} />
            新建技能
          </button>
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-500 text-sm">加载中...</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-500 gap-3">
            <FileText size={40} className="opacity-30" />
            <p className="text-sm">
              暂无技能{sourceFilter !== 'all' ? `（${SOURCE_LABELS[sourceFilter] ?? sourceFilter}）` : ''}
            </p>
            <button onClick={openCreate} className="text-blue-400 hover:text-blue-300 text-sm">
              创建第一个技能 →
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map(skill => (
              <SkillRow
                key={skill.id}
                skill={skill}
                onEdit={() => openEdit(skill)}
                onDelete={() => handleDelete(skill)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 新建/编辑弹窗 */}
      {dialogMode && (
        <SkillDialog
          mode={dialogMode}
          form={dialogForm}
          onChange={setDialogForm}
          onSave={dialogMode === 'create' ? saveCreate : saveEdit}
          onCancel={closeDialog}
        />
      )}

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog(p => ({ ...p, isOpen: false }))}
      />
    </div>
  )
}

// ==================== SkillRow ====================

function SkillRow({
  skill, onEdit, onDelete,
}: {
  skill: SkillItem
  onEdit: () => void
  onDelete: () => void
}) {
  const isBuiltin = skill.is_builtin
  return (
    <div className={`p-4 rounded-lg border transition-colors ${
      isBuiltin
        ? 'bg-dark-700/60 border-dark-500 opacity-75'
        : 'bg-dark-700 border-dark-500 hover:border-dark-400'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-gray-200 font-medium text-sm truncate">{skill.name}</span>
          <span className="text-xs text-gray-500 font-mono flex-shrink-0">#{skill.id}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-xs px-1.5 py-0.5 rounded bg-dark-800 text-gray-500">
            {SOURCE_LABELS[skill.source] ?? skill.source}
          </span>
          {isBuiltin && <Tag size={12} className="text-gray-500" aria-label="内置" />}
        </div>
      </div>

      {skill.description ? (
        <p className="text-xs text-gray-400 mb-2 line-clamp-1">{skill.description}</p>
      ) : null}

      <div className="mb-2">
        <pre className="text-xs text-gray-500 font-mono whitespace-pre-wrap max-h-20 overflow-y-auto bg-dark-800/50 rounded px-2 py-1.5">
          {skill.content.slice(0, 200)}{skill.content.length > 200 ? '...' : ''}
        </pre>
      </div>

      <div className="flex items-center justify-between text-xs text-gray-600">
        <span>{skill.installation_time || '未知时间'}</span>
        {!isBuiltin && (
          <div className="flex items-center gap-1">
            <button onClick={onEdit} className="p-1 text-gray-500 hover:text-blue-400 transition-colors rounded" title="编辑">
              <Edit2 size={13} />
            </button>
            <button onClick={onDelete} className="p-1 text-gray-500 hover:text-red-400 transition-colors rounded" title="删除">
              <Trash2 size={13} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== SkillDialog ====================

function SkillDialog({
  mode, form, onChange, onSave, onCancel,
}: {
  mode: 'create' | 'edit'
  form: SkillCreatePayload
  onChange: (f: SkillCreatePayload) => void
  onSave: () => void
  onCancel: () => void
}) {
  const isCreate = mode === 'create'
  const setField = <K extends keyof SkillCreatePayload>(key: K, val: any) => {
    onChange({ ...form, [key]: val })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-dark-700 border border-dark-500 rounded-lg w-full max-w-2xl mx-4 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-dark-600">
          <span className="text-gray-100 font-medium text-sm">
            {isCreate ? '新建技能' : '编辑技能'}
          </span>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-200"><X size={16} /></button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 overflow-y-auto flex-1 space-y-3">
          {isCreate && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Skill ID <span className="text-red-400">*</span></label>
                <input
                  value={form.id ?? ''}
                  onChange={e => setField('id', e.target.value)}
                  placeholder="如：sales-intent"
                  className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">名称 <span className="text-red-400">*</span></label>
                <input
                  value={form.name ?? ''}
                  onChange={e => setField('name', e.target.value)}
                  placeholder="技能显示名称"
                  className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          )}
          {!isCreate && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">名称 <span className="text-red-400">*</span></label>
              <input
                value={form.name ?? ''}
                onChange={e => setField('name', e.target.value)}
                className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          )}
          <div>
            <label className="block text-xs text-gray-400 mb-1">描述</label>
            <input
              value={form.description ?? ''}
              onChange={e => setField('description', e.target.value || null)}
              placeholder="一句话描述技能用途"
              className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">SKILL.md 内容</label>
            <textarea
              value={form.content ?? ''}
              onChange={e => setField('content', e.target.value)}
              rows={8}
              placeholder={"---\nname: 我的技能\ndescription: 技能描述\n---\n\n技能具体内容..."}
              className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 font-mono placeholder-gray-600 focus:outline-none focus:border-blue-500 resize-y"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-dark-600">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200">取消</button>
          <button
            onClick={onSave}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-md flex items-center gap-1"
          >
            <Save size={14} />
            {isCreate ? '创建' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ==================== MCP 面板 ====================

function McpPanel({ projectId }: { projectId?: number | null }) {
  const { showSuccess, showError } = useToast()
  const { servers, hasMcpError, refresh } = useMcpHealthStore()
  const [loading, setLoading] = useState(false)
  const [dialogMode, setDialogMode] = useState<'create' | 'edit' | null>(null)
  const [editServer, setEditServer] = useState<McpServer | null>(null)
  const [dialogForm, setDialogForm] = useState<McpServerCreatePayload>({
    name: '', description: null, type: 'stdio',
    command: null, args: null, url: null,
    headers: null, env: null, project_id: projectId ?? null,
  })
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean; title: string; message: string; onConfirm: () => void
  }>({ isOpen: false, title: '', message: '', onConfirm: () => {} })

  // 初始加载：写入 zustand store（refresh 内部会 set servers）
  useEffect(() => {
    setLoading(true)
    refresh(projectId ?? null)
      .catch((e: any) => showError(`加载 MCP 配置失败: ${e?.response?.data?.detail ?? e.message}`))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const openCreate = () => {
    setDialogMode('create')
    setEditServer(null)
    setDialogForm({
      name: '', description: null, type: 'stdio',
      command: null, args: null, url: null,
      headers: null, env: null, project_id: projectId ?? null,
    })
  }

  const openEdit = (server: McpServer) => {
    setDialogMode('edit')
    setEditServer(server)
    setDialogForm({
      name: server.name,
      description: server.description,
      type: server.type,
      command: server.command,
      args: server.args,
      url: server.url,
      headers: server.headers,
      env: server.env,
    })
  }

  const closeDialog = () => {
    setDialogMode(null)
    setEditServer(null)
  }

  const saveCreate = async () => {
    const form = dialogForm
    if (!form.name?.trim()) { showError('名称不能为空'); return }
    if (form.type === 'stdio' && !form.command) { showError('stdio 模式需要填写 command'); return }
    if (form.type !== 'stdio' && !form.url) { showError(`${form.type} 模式需要填写 url`); return }
    try {
      await createMcpServer(form)
      closeDialog()
      await refresh(projectId ?? undefined)
      showSuccess('MCP Server 已创建')
    } catch (e: any) {
      showError(`创建失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const saveEdit = async () => {
    if (!editServer) return
    const form = dialogForm as McpServerUpdatePayload
    if (!form.name?.trim()) { showError('名称不能为空'); return }
    try {
      await updateMcpServer(editServer.id, form)
      closeDialog()
      await refresh(projectId ?? undefined)
      showSuccess('MCP Server 已更新')
    } catch (e: any) {
      showError(`保存失败: ${e?.response?.data?.detail ?? e.message}`)
    }
  }

  const handleDelete = (server: McpServer) => {
    setConfirmDialog({
      isOpen: true,
      title: `删除 MCP Server「${server.name}」`,
      message: `确定要删除 MCP Server「${server.name}」吗？此操作不可恢复。`,
      onConfirm: async () => {
        try {
          await deleteMcpServer(server.id)
          await refresh(projectId ?? undefined)
          showSuccess('MCP Server 已删除')
        } catch (e: any) {
          showError(`删除失败: ${e?.response?.data?.detail ?? e.message}`)
        }
      },
    })
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Activity className={hasMcpError ? 'text-red-400' : 'text-cyan-400'} size={18} />
          <span className="text-gray-200 font-semibold">MCP Servers</span>
          <span className="text-xs text-gray-500 bg-dark-700 px-2 py-0.5 rounded-full">{servers.length} 个配置</span>
          {hasMcpError && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/30 text-red-400">有异常</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refresh(projectId ?? undefined)}
            className="px-2 py-1 bg-dark-700 hover:bg-dark-600 border border-dark-500 rounded text-xs text-gray-300 flex items-center gap-1"
            title="立即刷新健康状态"
          >
            <RefreshCw size={12} />
            刷新
          </button>
          <button
            onClick={openCreate}
            className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-700 text-white text-sm rounded-md flex items-center gap-1 transition-colors"
          >
            <Plus size={14} />
            新建 MCP Server
          </button>
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-500 text-sm">加载中...</div>
        ) : servers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-500 gap-3">
            <Activity size={40} className="opacity-30" />
            <p className="text-sm">暂无 MCP Server 配置</p>
            <button onClick={openCreate} className="text-cyan-400 hover:text-cyan-300 text-sm">
              创建第一个配置 →
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {servers.map(server => (
              <McpRow
                key={server.id}
                server={server}
                onEdit={() => openEdit(server)}
                onDelete={() => handleDelete(server)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 新建/编辑弹窗 */}
      {dialogMode && (
        <McpDialog
          mode={dialogMode}
          form={dialogForm}
          onChange={setDialogForm}
          onSave={dialogMode === 'create' ? saveCreate : saveEdit}
          onCancel={closeDialog}
        />
      )}

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog(p => ({ ...p, isOpen: false }))}
      />
    </div>
  )
}

// ==================== McpRow ====================

function McpRow({
  server, onEdit, onDelete,
}: {
  server: McpServer
  onEdit: () => void
  onDelete: () => void
}) {
  const cfg = getMcpStatusCfg(server.status)
  return (
    <div className="p-4 rounded-lg border bg-dark-700 border-dark-500 hover:border-dark-400 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-gray-200 font-medium text-sm truncate">{server.name}</span>
          <span className="text-xs text-gray-500 font-mono flex-shrink-0">#{server.id.slice(0, 8)}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className={`text-xs px-1.5 py-0.5 rounded flex items-center gap-1 ${cfg.color}`}>
            {cfg.icon === 'check' ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
            {cfg.label}
          </span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-dark-800 text-gray-500">
            {MCP_TYPE_LABELS[server.type] ?? server.type}
          </span>
        </div>
      </div>

      {server.description ? (
        <p className="text-xs text-gray-400 mb-2 line-clamp-1">{server.description}</p>
      ) : null}

      <div className="mb-2 text-xs text-gray-500 font-mono">
        {server.type === 'stdio' ? (
          <>
            <span>cmd: {server.command ?? '—'}</span>
            {server.args?.length ? <span className="ml-2">args: {server.args.join(' ')}</span> : null}
          </>
        ) : (
          <span>url: {server.url ?? '—'}</span>
        )}
        {server.headers && Object.keys(server.headers).length > 0 && (
          <span className="ml-2 text-gray-600">headers: {Object.keys(server.headers).join(', ')}</span>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-gray-600">
        <span>{server.created_at || '未知时间'}</span>
        <div className="flex items-center gap-1">
          <button onClick={onEdit} className="p-1 text-gray-500 hover:text-cyan-400 transition-colors rounded" title="编辑">
            <Edit2 size={13} />
          </button>
          <button onClick={onDelete} className="p-1 text-gray-500 hover:text-red-400 transition-colors rounded" title="删除">
            <Trash2 size={13} />
          </button>
        </div>
      </div>
    </div>
  )
}

// ==================== McpDialog ====================

function McpDialog({
  mode, form, onChange, onSave, onCancel,
}: {
  mode: 'create' | 'edit'
  form: McpServerCreatePayload
  onChange: (f: McpServerCreatePayload) => void
  onSave: () => void
  onCancel: () => void
}) {
  const isCreate = mode === 'create'
  const st = form.type || 'stdio'

  const setField = <K extends keyof McpServerCreatePayload>(key: K, val: any) => {
    onChange({ ...form, [key]: val })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-dark-700 border border-dark-500 rounded-lg w-full max-w-lg mx-4 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-dark-600">
          <span className="text-gray-100 font-medium text-sm">
            {isCreate ? '新建 MCP Server' : '编辑 MCP Server'}
          </span>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-200"><X size={16} /></button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 overflow-y-auto flex-1 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">名称 <span className="text-red-400">*</span></label>
              <input
                value={form.name ?? ''}
                onChange={e => setField('name', e.target.value)}
                placeholder="如：my-mcp-server"
                className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">描述</label>
              <input
                value={form.description ?? ''}
                onChange={e => setField('description', e.target.value || null)}
                placeholder="一句话描述用途"
                className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>

          {/* 连接模式 */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">连接模式</label>
            <select
              value={st}
              onChange={e => setField('type', e.target.value as McpServerCreatePayload['type'])}
              className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="stdio">stdio（本地命令）</option>
              <option value="sse">SSE（远程服务）</option>
              <option value="streamableHttp">streamableHttp（远程服务）</option>
            </select>
          </div>

          {/* 动态字段 */}
          {st === 'stdio' && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">命令 <span className="text-red-400">*</span></label>
                  <input
                    value={form.command ?? ''}
                    onChange={e => setField('command', e.target.value || null)}
                    placeholder="npx"
                    className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">参数（逗号分隔）</label>
                  <input
                    value={(form.args ?? []).join(', ')}
                    onChange={e => {
                      const arr = e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      setField('args', arr.length ? arr : null)
                    }}
                    placeholder="run, mcp-server-example"
                    className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">环境变量（JSON）</label>
                <textarea
                  value={JSON.stringify(form.env ?? {}, null, 2)}
                  onChange={e => {
                    try { setField('env', e.target.value ? JSON.parse(e.target.value) : null) } catch { /* ignore */ }
                  }}
                  rows={3}
                  placeholder='{"NODE_ENV": "production"}'
                  className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 font-mono placeholder-gray-600 focus:outline-none focus:border-cyan-500 resize-y"
                />
              </div>
            </>
          )}

          {(st === 'sse' || st === 'streamableHttp') && (
            <>
              <div>
                <label className="block text-xs text-gray-400 mb-1">服务地址 URL <span className="text-red-400">*</span></label>
                <input
                  value={form.url ?? ''}
                  onChange={e => setField('url', e.target.value || null)}
                  placeholder="http://localhost:3001/sse"
                  className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">请求头（JSON）</label>
                <textarea
                  value={JSON.stringify(form.headers ?? {}, null, 2)}
                  onChange={e => {
                    try { setField('headers', e.target.value ? JSON.parse(e.target.value) : null) } catch { /* ignore */ }
                  }}
                  rows={3}
                  placeholder='{"Authorization": "Bearer xxx"}'
                  className="w-full px-3 py-1.5 bg-dark-800 border border-dark-500 rounded text-sm text-gray-200 font-mono placeholder-gray-600 focus:outline-none focus:border-cyan-500 resize-y"
                />
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-dark-600">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200">取消</button>
          <button
            onClick={onSave}
            className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-700 text-white text-sm rounded-md flex items-center gap-1"
          >
            <Save size={14} />
            {isCreate ? '创建' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
