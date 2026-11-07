import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Database, GitCompareArrows, CircleDashed, CheckCircle2 } from 'lucide-react'
import ExportView from './ExportView'
import { StatCard, ChartFrame, StatusDonut, CategoryBars, toChartData } from './ui'
import {
  getSftSamples,
  extractSftSamples,
  exportSftData,
  getDpoPairs,
  getDpoPairDetail,
  generateDpoPairs,
  annotateDpoPair,
  exportDpoData,
  getDpoStatistics,
  getTrainingStatistics,
  type SftSample,
  type DpoPair,
  type DpoPairDetail,
  type TrainingStatistics,
} from '../api'

const TrainingView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'sft' | 'dpo' | 'dataset'>('sft')
  const [stats, setStats] = useState<TrainingStatistics | null>(null)
  const [sftSamples, setSftSamples] = useState<SftSample[]>([])
  const [dpoPairs, setDpoPairs] = useState<DpoPair[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  // DPO 标注相关状态
  const [selectedPair, setSelectedPair] = useState<DpoPairDetail | null>(null)
  const [annotator, setAnnotator] = useState('业务主管')
  const [chosenIdx, setChosenIdx] = useState(0)
  const [annotationNotes, setAnnotationNotes] = useState('')
  const [dpoStats, setDpoStats] = useState<{ total: number; pending: number; annotated: number; by_category: Record<string, number> } | null>(null)

  // 导出面板相关状态
  const [exportKind, setExportKind] = useState<'sft' | 'dpo' | null>(null)
  const [exportFormat, setExportFormat] = useState('sharegpt')
  const [exportPreview, setExportPreview] = useState<any[]>([])
  const [exportCount, setExportCount] = useState(0)
  const [exportLoading, setExportLoading] = useState(false)

  // 每个业务问题生成的 rejected 条数（1 chosen × N rejected）
  const [rejectedPerPair, setRejectedPerPair] = useState(3)

  // 加载统计数据（挂载时同时加载默认 SFT 标签页列表）
  useEffect(() => {
    loadStatistics()
    loadSftSamples()
  }, [])

  const loadStatistics = async () => {
    try {
      const data = await getTrainingStatistics()
      setStats(data)
    } catch (err) {
      console.error('加载统计失败', err)
    }
  }

  // 加载 SFT 样本
  const loadSftSamples = async () => {
    setLoading(true)
    try {
      const data = await getSftSamples({ limit: 50 })
      setSftSamples(data.samples)
    } catch (err) {
      console.error('加载 SFT 样本失败', err)
    } finally {
      setLoading(false)
    }
  }

  // 加载 DPO 偏好对
  const loadDpoPairs = async () => {
    setLoading(true)
    try {
      const data = await getDpoPairs({ limit: 50 })
      setDpoPairs(data.pairs)
    } catch (err) {
      console.error('加载 DPO 偏好对失败', err)
    } finally {
      setLoading(false)
    }
  }

  // 加载 DPO 统计
  const loadDpoStats = async () => {
    try {
      const data = await getDpoStatistics()
      setDpoStats(data)
    } catch (err) {
      console.error('加载 DPO 统计失败', err)
    }
  }

  // 加载 DPO 偏好对详情
  const loadDpoPairDetail = async (pairId: string) => {
    setLoading(true)
    try {
      const detail = await getDpoPairDetail(pairId)
      setSelectedPair(detail)
      setChosenIdx(detail.annotation_status === 'annotated' ? detail.chosen_reply ? 0 : 0 : 0)
      setAnnotationNotes(detail.annotation_notes || '')
      // DPO 详情返回的 chosen_reply 对应候选列表 index 0，rejected_replies 对应其余
      setChosenIdx(0)
    } catch (err: any) {
      setMessage(`加载详情失败: ${err.response?.data?.detail || err.message}`)
    } finally {
      setLoading(false)
    }
  }

  // 提交 DPO 标注
  const handleAnnotate = async (pairId: string) => {
    setLoading(true)
    setMessage('')
    try {
      const result = await annotateDpoPair(pairId, {
        chosen_index: chosenIdx,
        annotated_by: annotator || '业务主管',
        notes: annotationNotes,
      })
      setMessage(result.message)
      setSelectedPair(null)
      loadDpoPairs()
      loadDpoStats()
      loadStatistics()
    } catch (err: any) {
      setMessage(`标注失败: ${err.response?.data?.detail || err.message}`)
    } finally {
      setLoading(false)
    }
  }

  // 提取 SFT 样本
  const handleExtractSft = async () => {
    setLoading(true)
    setMessage('')
    try {
      const result = await extractSftSamples({ min_quality: 'medium', max_samples: 100 })
      setMessage(result.message)
      loadStatistics()
      loadSftSamples()
    } catch (err: any) {
      setMessage(`提取失败: ${err.response?.data?.detail || err.message}`)
    } finally {
      setLoading(false)
    }
  }

  // 生成 DPO 偏好对
  const handleGenerateDpo = async () => {
    setLoading(true)
    setMessage('')
    try {
      const result = await generateDpoPairs({
        min_quality: 'medium',
        max_pairs: 100,
        rejected_per_pair: rejectedPerPair,
      })
      setMessage(`${result.message}（每个问题 ${rejectedPerPair} 条 rejected）`)
      loadStatistics()
      loadDpoPairs()
    } catch (err: any) {
      setMessage(`生成失败: ${err.response?.data?.detail || err.message}`)
    } finally {
      setLoading(false)
    }
  }

  // 打开导出面板并加载预览
  const openExport = async (kind: 'sft' | 'dpo') => {
    const fmt = kind === 'sft' ? 'sharegpt' : 'dpo'
    setExportKind(kind)
    setExportFormat(fmt)
    await refreshExportPreview(kind, fmt)
  }

  // 刷新导出预览数据
  const refreshExportPreview = async (kind: 'sft' | 'dpo', format: string) => {
    setExportLoading(true)
    try {
      const result = kind === 'sft'
        ? await exportSftData({ format })
        : await exportDpoData({ format: 'dpo' })
      setExportPreview(result.data)
      setExportCount(result.count)
    } catch (err: any) {
      setMessage(`预览失败: ${err.response?.data?.detail || err.message}`)
      setExportPreview([])
      setExportCount(0)
    } finally {
      setExportLoading(false)
    }
  }

  // 切换导出格式时刷新预览
  const handleExportFormatChange = (fmt: string) => {
    setExportFormat(fmt)
    if (exportKind) refreshExportPreview(exportKind, fmt)
  }

  // 执行下载
  const downloadExport = () => {
    if (!exportKind) return
    const blob = new Blob([JSON.stringify(exportPreview, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const suffix = exportKind === 'sft' ? `sft_${exportFormat}` : 'dpo'
    a.href = url
    a.download = `training_${suffix}_${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    setMessage(`导出成功，共 ${exportCount} 条${exportKind === 'sft' ? ' SFT 样本' : ' DPO 偏好对'}`)
  }

  return (
    <div className="training-view">
      <div className="training-header">
        <h2>训练数据管理</h2>
        <p className="training-desc">
          支持 SFT（监督微调）和 DPO（直接偏好优化）两阶段训练路径
        </p>
      </div>

      {/* 统计概览 */}
      {stats && (
        <>
          <motion.div
            initial="hidden"
            animate="show"
            transition={{ staggerChildren: 0.05 }}
            className="stats-overview"
          >
            <StatCard
              label="SFT 训练样本"
              value={stats.sft_samples.total}
              hint={`已核准 ${stats.sft_samples.approved}`}
              icon={<Database size={17} />}
              tone="iris"
            />
            <StatCard
              label="DPO 偏好对"
              value={stats.dpo_pairs.total}
              hint="1 chosen × N rejected"
              icon={<GitCompareArrows size={17} />}
              tone="mint"
            />
            <StatCard
              label="待标注"
              value={stats.dpo_pairs.pending ?? 0}
              hint="等待业务主管确认"
              icon={<CircleDashed size={17} />}
              tone="flare"
            />
            <StatCard
              label="已标注"
              value={stats.dpo_pairs.annotated ?? 0}
              hint="已完成偏好确认"
              icon={<CheckCircle2 size={17} />}
              tone="mint"
            />
          </motion.div>

          {/* 分布图：直接来自 /api/training/statistics 当前快照 */}
          <div className="training-charts grid gap-4 lg:grid-cols-2">
            <ChartFrame title="DPO 业务分类分布" subtitle="按偏好对数量 · 当前快照">
              <CategoryBars data={toChartData(stats.dpo_pairs.by_category)} unit=" 对" />
            </ChartFrame>
            <ChartFrame title="偏好标注进度" subtitle="待标注 / 已标注 · 当前快照">
              <StatusDonut
                data={[
                  { name: '已标注', value: stats.dpo_pairs.annotated ?? 0 },
                  { name: '待标注', value: stats.dpo_pairs.pending ?? 0 },
                ]}
                centerLabel="偏好对"
                unit=" 对"
              />
            </ChartFrame>
          </div>
        </>
      )}

      {/* 消息提示 */}
      {message && (
        <div className={`message ${message.startsWith('失败') ? 'error' : 'success'}`}>
          {message}
        </div>
      )}

      {/* 标签页 */}
      <div className="tab-nav">
        <button
          className={activeTab === 'sft' ? 'active' : ''}
          onClick={() => { setActiveTab('sft'); loadSftSamples() }}
        >
          SFT 训练样本
        </button>
        <button
          className={activeTab === 'dpo' ? 'active' : ''}
          onClick={() => { setActiveTab('dpo'); loadDpoPairs(); loadDpoStats() }}
        >
          DPO 偏好对
        </button>
        <button
          className={activeTab === 'dataset' ? 'active' : ''}
          onClick={() => setActiveTab('dataset')}
        >
          生成微调数据集
        </button>
      </div>

      {/* SFT 标签页 */}
      {activeTab === 'sft' && (
        <div className="tab-content">
          <div className="toolbar">
            <button onClick={handleExtractSft} disabled={loading}>
              {loading ? '提取中...' : '从聊天记录提取'}
            </button>
            <button onClick={() => openExport('sft')} disabled={loading}>
              导出训练数据
            </button>
          </div>
          <div className="data-list">
            {loading ? (
              <div className="loading">加载中...</div>
            ) : sftSamples.length === 0 ? (
              <div className="empty">
                <p>暂无 SFT 训练样本</p>
                <p>点击「从聊天记录提取」按钮开始</p>
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>问题</th>
                    <th>回复</th>
                    <th>分类</th>
                    <th>质量分</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {sftSamples.map((sample) => (
                    <tr key={sample.id}>
                      <td>{sample.id.slice(0, 8)}</td>
                      <td>{sample.instruction.slice(0, 50)}...</td>
                      <td>{sample.output.slice(0, 50)}...</td>
                      <td>{sample.category}</td>
                      <td>{sample.quality_score?.toFixed(1)}</td>
                      <td>{new Date(sample.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* DPO 标签页 */}
      {activeTab === 'dpo' && (
        <div className="tab-content">
          <div className="toolbar">
            <button onClick={handleGenerateDpo} disabled={loading}>
              {loading ? '生成中...' : '生成 DPO 偏好对'}
            </button>
            <select
              className="toolbar-select"
              value={rejectedPerPair}
              onChange={(e) => setRejectedPerPair(Number(e.target.value))}
              disabled={loading}
              title="每个业务问题生成的 rejected 数量（1 chosen × N rejected）"
            >
              <option value={1}>每个问题 1 条 rejected（标准 1v1）</option>
              <option value={2}>每个问题 2 条 rejected</option>
              <option value={3}>每个问题 3 条 rejected（类型不同）</option>
            </select>
            <button onClick={() => openExport('dpo')} disabled={loading}>
              导出训练数据
            </button>
          </div>
          <div className="data-list">
            {dpoStats && (
              <div className="dpo-stats">
                <span>总计: {dpoStats.total}</span>
                <span>待标注: {dpoStats.pending}</span>
                <span>已标注: {dpoStats.annotated}</span>
              </div>
            )}
            {loading ? (
              <div className="loading">加载中...</div>
            ) : dpoPairs.length === 0 ? (
              <div className="empty">
                <p>暂无 DPO 偏好对</p>
                <p>点击「生成 DPO 偏好对」按钮开始</p>
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>问题</th>
                    <th>分类</th>
                    <th>状态</th>
                    <th>质量分</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {dpoPairs.map((pair) => (
                    <tr
                      key={pair.id}
                      onClick={() => loadDpoPairDetail(pair.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td>{pair.id.slice(0, 8)}</td>
                      <td>{pair.prompt.slice(0, 50)}...</td>
                      <td>{pair.business_category}</td>
                      <td>
                        <span className={`status-${pair.annotation_status}`}>
                          {pair.annotation_status === 'pending' ? '待标注' : '已标注'}
                        </span>
                      </td>
                      <td>{pair.quality_score?.toFixed(1)}</td>
                      <td>{new Date(pair.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* 生成微调数据集标签页（内嵌「导出训练数据 / 生成客服 AI 微调数据集」） */}
      {activeTab === 'dataset' && (
        <div className="tab-content dataset-tab">
          <ExportView embedded />
        </div>
      )}

      {/* DPO 标注弹窗 */}
      {selectedPair && (
        <div className="modal-overlay" onClick={() => setSelectedPair(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>DPO 偏好对标注</h3>
              <button className="modal-close" onClick={() => setSelectedPair(null)}>×</button>
            </div>

            <div className="modal-body">
              <div className="field">
                <label>业务问题</label>
                <div className="prompt-box">{selectedPair.prompt}</div>
              </div>

              <div className="field">
                <label>业务场景</label>
                <span>{selectedPair.business_category}</span>
                {selectedPair.scenario_description && (
                  <span className="scenario-desc"> — {selectedPair.scenario_description}</span>
                )}
              </div>

              <div className="candidate-list">
                <label>候选回复（请选择最优回复作为 chosen）</label>
                {/* index 0 = chosen_reply, 其余为 rejected_replies */}
                <div
                  className={`candidate ${chosenIdx === 0 ? 'chosen' : 'rejected'}`}
                  onClick={() => setChosenIdx(0)}
                >
                  <div className="candidate-head">
                    <span className="badge">候选 1</span>
                    <span className={`tag ${chosenIdx === 0 ? 'tag-chosen' : 'tag-rejected'}`}>
                      {chosenIdx === 0 ? '✓ chosen' : '✗ rejected'}
                    </span>
                  </div>
                  <div className="candidate-text">{selectedPair.chosen_reply}</div>
                </div>

                {selectedPair.rejected_replies.map((reply, i) => {
                  const errType = selectedPair.rejected_details?.find(d => d.index === i + 1)?.error_type || ''
                  return (
                    <div
                      key={i}
                      className={`candidate ${chosenIdx === i + 1 ? 'chosen' : 'rejected'}`}
                      onClick={() => setChosenIdx(i + 1)}
                    >
                      <div className="candidate-head">
                        <span className="badge">候选 {i + 2}</span>
                        <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          {errType && <span className="tag tag-errtype">{errType}</span>}
                          <span className={`tag ${chosenIdx === i + 1 ? 'tag-chosen' : 'tag-rejected'}`}>
                            {chosenIdx === i + 1 ? '✓ chosen' : '✗ rejected'}
                          </span>
                        </span>
                      </div>
                      <div className="candidate-text">{reply}</div>
                    </div>
                  )
                })}
              </div>

              <div className="field">
                <label>标注人</label>
                <input
                  value={annotator}
                  onChange={(e) => setAnnotator(e.target.value)}
                  placeholder="业务主管姓名"
                />
              </div>

              <div className="field">
                <label>标注备注（可选）</label>
                <textarea
                  value={annotationNotes}
                  onChange={(e) => setAnnotationNotes(e.target.value)}
                  placeholder="如：候选2算错运费、候选3态度生硬..."
                  rows={3}
                />
              </div>
            </div>

            <div className="modal-footer">
              <button onClick={() => setSelectedPair(null)}>取消</button>
              <button
                className="primary"
                onClick={() => handleAnnotate(selectedPair.id)}
                disabled={loading}
              >
                {loading ? '提交中...' : '提交标注'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 导出训练数据面板 */}
      {exportKind && (
        <div className="modal-overlay" onClick={() => setExportKind(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {exportKind === 'sft' ? '导出 SFT 训练数据' : '导出 DPO 偏好对'}
              </h3>
              <button className="modal-close" onClick={() => setExportKind(null)}>×</button>
            </div>

            <div className="modal-body">
              {exportKind === 'sft' && (
                <div className="field">
                  <label>导出格式</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {['sharegpt', 'alpaca', 'openai'].map((fmt) => (
                      <button
                        key={fmt}
                        className={`tab-nav`}
                        style={{
                          border: exportFormat === fmt ? '1px solid rgb(var(--c-iris))' : '1px solid rgb(var(--c-line))',
                          color: exportFormat === fmt ? 'rgb(var(--c-iris))' : 'rgb(var(--c-ink-subtle))',
                          background: 'transparent',
                          padding: '6px 14px',
                          borderRadius: 8,
                        }}
                        onClick={() => handleExportFormatChange(fmt)}
                      >
                        {fmt.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="field">
                <label>
                  预览（共 {exportCount} 条
                  {exportKind === 'sft'
                    ? ` · 格式 ${exportFormat}`
                    : ' · 格式 DPO（chosen / rejected 偏好对）'}
                  ）
                </label>
                <pre
                  style={{
                    background: 'rgb(var(--c-panel-2))',
                    border: '1px solid rgb(var(--c-line))',
                    borderRadius: 8,
                    padding: 12,
                    color: 'rgb(var(--c-ink-muted))',
                    fontSize: 12,
                    maxHeight: 320,
                    overflow: 'auto',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}
                >
{exportLoading
  ? '加载中...'
  : JSON.stringify(exportPreview.slice(0, 2), null, 2)
    + (exportPreview.length > 2 ? `\n\n... 共 ${exportCount} 条（仅显示前 2 条）` : '')}
                </pre>
              </div>
            </div>

            <div className="modal-footer">
              <button onClick={() => setExportKind(null)}>关闭</button>
              <button
                className="primary"
                onClick={downloadExport}
                disabled={exportLoading || exportCount === 0}
              >
                下载 JSON
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default TrainingView
