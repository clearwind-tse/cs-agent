import { useState, useEffect } from 'react'
import { X, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react'
import {
  getCurrentQcConfig, addCalibrationItem,
  type CalibrationGroup, type QcDimension,
} from '../api'
import { maskSessionId } from '../sessionDisplay'

interface Props {
  groups: CalibrationGroup[]
  /** 从清洗列表进入时预填的会话信息 */
  defaultSessionId?: string
  defaultStartTime?: number | null
  defaultEndTime?: number | null
  defaultAgentName?: string | null
  onClose: () => void
  onCreated: () => void
}

/**
 * 「标记为标注数据」弹窗：把一条会话的人工真值（总分 + 各维度）冻结进校准分组。
 * 时间窗随会话一并冻结（重跑时用同一窗口，保证与人工判定的是同一段对话）。
 */
export default function QcCalibrationItemDialog({
  groups, defaultSessionId, defaultStartTime, defaultEndTime, defaultAgentName,
  onClose, onCreated,
}: Props) {
  const [groupId, setGroupId] = useState<number | ''>(groups[0]?.id ?? '')
  const [sessionId, setSessionId] = useState(defaultSessionId || '')
  // 从清洗列表进入时已确定会话，展示脱敏标识即可（真实 ID 仍用于提交）；
  // 仅在校准页手动添加时才需要用户自行填写。
  const lockedSessionId = (defaultSessionId || '').trim()
  const [goldTotal, setGoldTotal] = useState('')
  const [dimScores, setDimScores] = useState<Record<string, string>>({})
  const [note, setNote] = useState('')
  const [dims, setDims] = useState<QcDimension[]>([])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    getCurrentQcConfig()
      .then((res) => {
        const cfg = res.current?.config || res.default
        setDims(cfg.dimensions || [])
      })
      .catch(() => { /* 拉取失败则不展示维度输入 */ })
  }, [])

  // 分组列表是异步到达的（弹窗可能在列表加载完成前就已挂载），到达后补选默认项，
  // 否则 groupId 会一直停在空串，提交时被「请先选择分组」拦下。
  useEffect(() => {
    if (groupId === '' && groups.length > 0) setGroupId(groups[0].id)
  }, [groups, groupId])

  const handleSubmit = async () => {
    setErr('')
    if (!groupId) { setErr('请先选择分组'); return }
    if (!sessionId.trim()) { setErr('请输入会话 ID'); return }
    const total = Number(goldTotal)
    if (goldTotal === '' || Number.isNaN(total) || total < 0 || total > 100) {
      setErr('人工总分需为 0-100')
      return
    }
    const scores: Record<string, number> = {}
    for (const d of dims) {
      const raw = dimScores[d.key]
      if (raw === undefined || raw === '') continue
      const v = Number(raw)
      if (Number.isNaN(v) || v < 0 || v > 100) {
        setErr(`维度「${d.name}」分值需为 0-100`)
        return
      }
      scores[d.key] = v
    }
    setSaving(true)
    try {
      await addCalibrationItem(groupId, {
        session_id: sessionId.trim(),
        gold_total: total,
        gold_scores: scores,
        start_time: defaultStartTime ?? undefined,
        end_time: defaultEndTime ?? undefined,
        agent_name: defaultAgentName ?? undefined,
        note: note.trim() || undefined,
      })
      onCreated()
      onClose()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-scrim/50 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg max-h-[90vh] overflow-y-auto bg-canvas border border-line rounded-xl p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink flex items-center gap-2">
            <CheckCircle2 size={20} className="text-iris" /> 标记为标注数据
          </h2>
          <button onClick={onClose} className="p-2 rounded-lg hover:bg-panel-2 text-ink-muted">
            <X size={18} />
          </button>
        </div>

        <p className="text-xs text-ink-subtle">
          人工分数将作为该会话的「真值」冻结，用于校准 AI 质检的准确度。
        </p>

        {groups.length === 0 ? (
          <div className="px-4 py-3 bg-warn/10 border border-warn/30 rounded-lg text-warn text-sm">
            还没有校准分组，请先在「校准对比」中新建一个分组。
          </div>
        ) : (
          <>
            <div>
              <label className="text-sm text-ink-muted mb-1 block">校准分组</label>
              <select
                value={groupId}
                onChange={(e) => setGroupId(Number(e.target.value))}
                className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-2 text-ink text-sm focus:outline-none"
              >
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}（{g.item_count} 条）</option>)}
              </select>
            </div>

            <div>
              <label className="text-sm text-ink-muted mb-1 block">
                {lockedSessionId ? '会话' : '会话 ID (session_id)'}
              </label>
              {lockedSessionId ? (
                <div className="w-full bg-canvas/40 border border-line rounded-lg px-3 py-2 text-ink text-sm font-mono">
                  {maskSessionId(sessionId)}
                </div>
              ) : (
                <input
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                  placeholder="微信会话 session_id"
                  className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-2 text-ink text-sm focus:outline-none"
                />
              )}
              {(defaultStartTime || defaultEndTime) && (
                <p className="text-xs text-ink-subtle mt-1">
                  已冻结时间窗：{defaultStartTime ?? '-'} ~ {defaultEndTime ?? '-'}（重跑将使用同一段对话）
                </p>
              )}
            </div>

            <div className="w-40">
              <label className="text-sm text-ink-muted mb-1 block">人工总分 (0-100)</label>
              <input
                type="number" min={0} max={100}
                value={goldTotal}
                onChange={(e) => setGoldTotal(e.target.value)}
                className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-2 text-ink text-sm focus:outline-none"
              />
            </div>

            {dims.length > 0 && (
              <div className="space-y-2">
                <label className="text-sm text-ink-muted block">各维度人工分（可选，留空则不计入维度偏差）</label>
                <div className="grid grid-cols-2 gap-2">
                  {dims.map((d) => (
                    <div key={d.key} className="flex items-center gap-2 bg-panel rounded-lg px-3 py-2">
                      <span className="text-xs text-ink-muted flex-1 truncate" title={d.name}>{d.name}</span>
                      <input
                        type="number" min={0} max={100}
                        value={dimScores[d.key] ?? ''}
                        onChange={(e) => setDimScores((p) => ({ ...p, [d.key]: e.target.value }))}
                        className="w-20 bg-panel-2 border border-line-strong rounded px-2 py-1 text-ink text-xs focus:outline-none"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className="text-sm text-ink-muted mb-1 block">备注（可选）</label>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                className="w-full bg-panel-2 border border-line-strong rounded-lg px-3 py-2 text-ink text-sm focus:outline-none resize-none"
              />
            </div>

            {err && (
              <div className="px-3 py-2 bg-bad/10 border border-bad/30 rounded-lg text-bad text-sm flex items-center gap-2">
                <AlertCircle size={16} /> {err}
              </div>
            )}

            <div className="flex justify-end gap-3 pt-1">
              <button onClick={onClose} className="px-4 py-2 bg-panel-2 text-ink rounded-lg hover:bg-line text-sm">
                取消
              </button>
              <button
                onClick={handleSubmit}
                disabled={saving}
                className="px-4 py-2 bg-iris text-ink rounded-lg hover:bg-iris/80 disabled:opacity-50 text-sm font-medium flex items-center gap-1"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} 保存标注
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
