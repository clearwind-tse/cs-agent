import { useState, useEffect, useRef } from 'react'
import { X, Download, FileJson, Eye, Loader2, Check, Filter, Sparkles, Database, Bot, Clock, Cloud } from 'lucide-react'
import { cn } from '../utils'
import axios from 'axios'

interface ExportViewProps {
  onClose: () => void
}

interface ExportFormat {
  id: string
  name: string
  description: string
  extension: string
}

interface ExportConfig {
  format: string
  min_quality: string
  categories: string[]
  session_ids: string[] | null
  include_system_prompt: boolean
  time_window_seconds: number
  max_turns_per_conversation: number
  use_llm_scoring: boolean
  llm_min_score: number
  deduplicate: boolean
  include_custom: boolean  // 是否包含自定义数据
  rag_mode: string  // rule | llm | distill | raw (RAG 格式专用)
  distill_include_kb: boolean  // distill 模式是否合并手写知识库
  distill_expand_variants: boolean  // distill 模式是否展开 variants
}

interface PreviewData {
  preview: any[]
  statistics: {
    total: number
    previewed?: number
    by_quality?: Record<string, number>
    by_category?: Record<string, number>
    rag_quality?: Record<string, any>
    distill?: {
      input: number
      groups: number
      distilled: number
      skipped_small: number
      failed: number
      manual_entries: number
      output: number
    }
    avg_turns?: number
    avg_length?: number
    message?: string
  }
}

// RAG LLM 后台任务状态
interface RagLLMTask {
  task_id: string
  status: 'running' | 'done' | 'error'
  total: number
  completed: number
  elapsed_seconds: number
  eta_seconds: number | null
  output_count?: number
  stats?: Record<string, any>
  error?: string
}

const FORMATS: ExportFormat[] = [
  { id: 'sharegpt', name: 'ShareGPT', description: '多轮对话，适用于 LLaMA-Factory', extension: 'json' },
  { id: 'alpaca', name: 'Alpaca', description: '指令微调格式', extension: 'json' },
  { id: 'openai', name: 'OpenAI Chat', description: 'OpenAI 微调格式', extension: 'jsonl' },
  { id: 'jsonl', name: 'JSONL', description: '通用格式', extension: 'jsonl' },
  { id: 'rag', name: 'RAG 知识库', description: '问答对 CSV，适用于火山引擎等平台', extension: 'csv' },
]

const QUALITIES = [
  { id: 'high', name: '高质量', description: '完整问答、技术讨论', color: 'text-green-400' },
  { id: 'medium', name: '中等', description: '有价值的内容', color: 'text-yellow-400' },
  { id: 'low', name: '低质量', description: '包含闲聊', color: 'text-orange-400' },
]

const CATEGORIES = [
  { id: 'savings_explain', name: '省钱讲解', icon: '💰' },
  { id: 'rebate_query', name: '返利查询', icon: '🧾' },
  { id: 'coupon_issue', name: '优惠券问题', icon: '🎟️' },
  { id: 'order_problem', name: '订单问题', icon: '📦' },
  { id: 'complaint', name: '投诉处理', icon: '🛡️' },
  { id: 'merchant', name: '到店霸王餐', icon: '🍜' },
  { id: 'brand_promo', name: '品牌活动', icon: '🥤' },
  { id: 'points_box', name: '积分盲盒', icon: '🎁' },
  { id: 'onboarding', name: '新人引导', icon: '📚' },
  { id: 'chitchat', name: '闲聊', icon: '💬' },
]

export default function ExportView({ onClose }: ExportViewProps) {
  // 数据来源: all = 全部(标注+自定义), generated = 仅AI生成
  const [dataSource, setDataSource] = useState<'all' | 'generated'>('all')

  const [config, setConfig] = useState<ExportConfig>({
    format: 'sharegpt',
    min_quality: 'medium',
    categories: [],
    session_ids: null,
    include_system_prompt: true,
    time_window_seconds: 300,
    max_turns_per_conversation: 20,
    use_llm_scoring: false,
    llm_min_score: 6.0,
    deduplicate: false,
    include_custom: true,
    rag_mode: 'rule',
    distill_include_kb: true,
    distill_expand_variants: true,
  })

  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState<'config' | 'preview'>('config')
  const [tosResult, setTosResult] = useState<{ key: string; success: boolean } | null>(null)

  // RAG LLM 后台任务状态
  const [llmTask, setLlmTask] = useState<RagLLMTask | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 清理定时器
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const handlePreview = async () => {
    setLoading(true)
    setError(null)
    try {
      let response
      if (dataSource === 'generated') {
        response = await axios.post('/api/export/generated/preview', {
          format: config.format,
          include_system_prompt: config.include_system_prompt,
          categories: config.categories.length > 0 ? config.categories : null,
        }, { params: { limit: 10 } })
      } else {
        response = await axios.post('/api/export/labeled/preview', {
          format: config.format,
          include_system_prompt: config.include_system_prompt,
          categories: config.categories.length > 0 ? config.categories : null,
          include_custom: config.include_custom,
          rag_mode: config.format === 'rag' ? config.rag_mode : undefined,
          distill_include_kb: config.format === 'rag' && config.rag_mode === 'distill' ? config.distill_include_kb : undefined,
          distill_expand_variants: config.format === 'rag' && config.rag_mode === 'distill' ? config.distill_expand_variants : undefined,
        }, { params: { limit: 10 } })
      }
      setPreview(response.data)
      setStep('preview')
    } catch (err: any) {
      const detail = err.response?.data?.detail
      if (err.response?.status === 404) {
        setError(dataSource === 'generated'
          ? '没有AI生成的数据。请先在「自定义数据」中使用AI批量生成。'
          : '没有找到已通过的标注数据。请先在数据质检中心的「会话清洗与审核」里审核通过数据。')
      } else if (detail) {
        setError(`预览失败: ${detail}`)
      } else {
        setError('预览失败，请检查后端服务是否正常运行')
      }
      console.error('Preview error:', err)
    } finally {
      setLoading(false)
    }
  }

  // 启动 RAG LLM 后台任务
  const startRagLLMTask = async () => {
    setExporting(true)
    setError(null)
    setLlmTask(null)
    setStep('config')  // 切回配置页显示进度

    try {
      const response = await axios.post('/api/export/rag-llm/start', {
        categories: config.categories.length > 0 ? config.categories : null,
        exclude_price_data: true,
        include_custom: config.include_custom,
        rag_min_confidence: 0.4,
        rag_filter_noise: true,
      })

      const taskId = response.data.task_id
      setLlmTask({
        task_id: taskId,
        status: 'running',
        total: response.data.total,
        completed: 0,
        elapsed_seconds: 0,
        eta_seconds: null,
      })

      // 开始轮询进度
      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await axios.get(`/api/export/rag-llm/status/${taskId}`)
          const taskStatus: RagLLMTask = statusRes.data

          setLlmTask(taskStatus)

          if (taskStatus.status === 'done') {
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = null
            setExporting(false)
          } else if (taskStatus.status === 'error') {
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = null
            setExporting(false)
            setError(taskStatus.error || 'LLM 改写任务失败')
          }
        } catch {
          // 轮询失败不中断
        }
      }, 2000)  // 每 2 秒轮询一次

    } catch (err: any) {
      setExporting(false)
      const detail = err.response?.data?.detail
      setError(detail || 'LLM 改写任务启动失败')
    }
  }

  // 下载 LLM 改写结果
  const downloadLLMResult = async () => {
    if (!llmTask?.task_id) return

    setTosResult(null)
    try {
      const response = await axios.get(`/api/export/rag-llm/download/${llmTask.task_id}`, {
        responseType: 'blob',
      })

      // 读取 TOS 上传结果
      const tosKey = response.headers['x-tos-key']
      if (tosKey) {
        setTosResult({ key: tosKey, success: true })
      }

      const contentDisposition = response.headers['content-disposition']
      let filename = 'rag_llm_rewritten.csv'
      if (contentDisposition) {
        const match = contentDisposition.match(/filename=(.+)/)
        if (match) filename = match[1]
      }

      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('下载失败')
    }
  }

  const handleExport = async () => {
    // RAG + LLM 模式走后台任务
    if (config.format === 'rag' && config.rag_mode === 'llm') {
      await startRagLLMTask()
      return
    }

    setExporting(true)
    setError(null)
    setTosResult(null)
    try {
      const endpoint = dataSource === 'generated'
        ? '/api/export/generated/dataset'
        : '/api/export/labeled/dataset'

      const body = dataSource === 'generated'
        ? {
            format: config.format,
            include_system_prompt: config.include_system_prompt,
            categories: config.categories.length > 0 ? config.categories : null,
          }
        : {
            format: config.format,
            include_system_prompt: config.include_system_prompt,
            categories: config.categories.length > 0 ? config.categories : null,
            include_custom: config.include_custom,
            rag_mode: config.format === 'rag' ? config.rag_mode : undefined,
            distill_include_kb: config.format === 'rag' && config.rag_mode === 'distill' ? config.distill_include_kb : undefined,
            distill_expand_variants: config.format === 'rag' && config.rag_mode === 'distill' ? config.distill_expand_variants : undefined,
          }

      const response = await axios.post(endpoint, body, { responseType: 'blob' })

      // 读取 TOS 上传结果
      const tosKey = response.headers['x-tos-key']
      if (tosKey) {
        setTosResult({ key: tosKey, success: true })
      }

      const contentDisposition = response.headers['content-disposition']
      let filename = `training_data.${config.format === 'rag' ? 'csv' : config.format === 'openai' || config.format === 'jsonl' ? 'jsonl' : 'json'}`
      if (contentDisposition) {
        const match = contentDisposition.match(/filename=(.+)/)
        if (match) filename = match[1]
      }

      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(dataSource === 'generated'
        ? '导出失败，请确保有AI生成的数据'
        : '导出失败，请确保有已通过的标注数据')
    } finally {
      setExporting(false)
    }
  }

  const toggleCategory = (id: string) => {
    setConfig(prev => ({
      ...prev,
      categories: prev.categories.includes(id)
        ? prev.categories.filter(c => c !== id)
        : [...prev.categories, id]
    }))
  }

  // 格式化秒数为 mm:ss
  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-dark-800 animate-fade-in">
      {/* 头部 */}
      <header className="h-16 px-6 flex items-center justify-between border-b border-dark-600 bg-dark-800/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
            <Download size={20} className="text-white" />
          </div>
          <div>
            <h2 className="font-medium text-white">导出训练数据</h2>
            <p className="text-xs text-gray-500">生成客服 AI 微调数据集</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>
      </header>

      {/* 主体内容 */}
      <div className="flex-1 overflow-y-auto p-6">
        {step === 'config' ? (
          <div className="max-w-2xl mx-auto space-y-6">
            {/* LLM 任务进度 */}
            {llmTask && (
              <div className={cn(
                "p-4 rounded-xl border",
                llmTask.status === 'running' ? "bg-yellow-500/10 border-yellow-500/30" :
                llmTask.status === 'done' ? "bg-green-500/10 border-green-500/30" :
                "bg-red-500/10 border-red-500/30"
              )}>
                {llmTask.status === 'running' && (
                  <>
                    <div className="flex items-center gap-2 mb-3">
                      <Loader2 size={16} className="animate-spin text-yellow-400" />
                      <span className="text-yellow-400 font-medium text-sm">LLM 改写进行中...</span>
                      <span className="text-gray-500 text-xs ml-auto flex items-center gap-1">
                        <Clock size={12} />
                        已用 {formatTime(llmTask.elapsed_seconds)}
                        {llmTask.eta_seconds && ` · 预计剩余 ${formatTime(llmTask.eta_seconds)}`}
                      </span>
                    </div>
                    <div className="w-full bg-dark-600 rounded-full h-2 mb-2">
                      <div
                        className="bg-gradient-to-r from-yellow-500 to-amber-400 h-2 rounded-full transition-all duration-500"
                        style={{ width: `${llmTask.total > 0 ? (llmTask.completed / llmTask.total * 100) : 0}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-400">
                      {llmTask.completed} / {llmTask.total} 条 ({llmTask.total > 0 ? Math.round(llmTask.completed / llmTask.total * 100) : 0}%)
                    </p>
                  </>
                )}

                {llmTask.status === 'done' && (
                  <>
                    <div className="flex items-center gap-2 mb-3">
                      <Check size={16} className="text-green-400" />
                      <span className="text-green-400 font-medium text-sm">LLM 改写完成！</span>
                      <span className="text-gray-500 text-xs ml-auto">
                        共 {llmTask.output_count} 条有效数据 · 耗时 {formatTime(llmTask.elapsed_seconds)}
                      </span>
                    </div>
                    {llmTask.stats && (
                      <div className="grid grid-cols-4 gap-2 mb-3">
                        <div className="bg-dark-700 rounded-lg p-2 text-center">
                          <p className="text-white font-bold text-sm">{llmTask.stats.input}</p>
                          <p className="text-xs text-gray-500">输入</p>
                        </div>
                        <div className="bg-dark-700 rounded-lg p-2 text-center">
                          <p className="text-green-400 font-bold text-sm">{llmTask.stats.rewritten}</p>
                          <p className="text-xs text-gray-500">改写成功</p>
                        </div>
                        <div className="bg-dark-700 rounded-lg p-2 text-center">
                          <p className="text-yellow-400 font-bold text-sm">{llmTask.stats.noise_filtered + (llmTask.stats.noise_post_filtered || 0)}</p>
                          <p className="text-xs text-gray-500">噪声过滤</p>
                        </div>
                        <div className="bg-dark-700 rounded-lg p-2 text-center">
                          <p className="text-red-400 font-bold text-sm">{llmTask.stats.failed}</p>
                          <p className="text-xs text-gray-500">失败</p>
                        </div>
                      </div>
                    )}
                    <button
                      onClick={downloadLLMResult}
                      className="w-full py-2.5 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors flex items-center justify-center gap-2 font-medium"
                    >
                      <Download size={16} />
                      下载 CSV ({llmTask.output_count} 条)
                    </button>
                    {tosResult && tosResult.success && (
                      <div className="mt-2 flex items-center gap-2 text-xs text-emerald-400">
                        <Cloud size={14} />
                        <span>已同步上传 TOS: <span className="font-mono text-gray-500">{tosResult.key}</span></span>
                      </div>
                    )}
                  </>
                )}

                {llmTask.status === 'error' && (
                  <div className="flex items-center gap-2">
                    <X size={16} className="text-red-400" />
                    <span className="text-red-400 text-sm">{llmTask.error || '任务失败'}</span>
                  </div>
                )}
              </div>
            )}

            {/* 数据来源 */}
            <section>
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Database size={16} className="text-accent-primary" />
                数据来源
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setDataSource('all')}
                  className={cn(
                    'p-4 rounded-xl border text-left transition-all',
                    dataSource === 'all'
                      ? 'border-accent-primary bg-accent-primary/10'
                      : 'border-dark-500 hover:border-dark-400 bg-dark-700'
                  )}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Database size={16} className="text-blue-400" />
                      <span className="font-medium text-white">全部数据</span>
                    </div>
                    {dataSource === 'all' && <Check size={16} className="text-accent-primary" />}
                  </div>
                  <p className="text-xs text-gray-500">标注数据 + 自定义/AI生成数据</p>
                </button>
                <button
                  onClick={() => setDataSource('generated')}
                  className={cn(
                    'p-4 rounded-xl border text-left transition-all',
                    dataSource === 'generated'
                      ? 'border-purple-500 bg-purple-500/10'
                      : 'border-dark-500 hover:border-dark-400 bg-dark-700'
                  )}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Bot size={16} className="text-purple-400" />
                      <span className="font-medium text-white">仅AI生成</span>
                    </div>
                    {dataSource === 'generated' && <Check size={16} className="text-purple-400" />}
                  </div>
                  <p className="text-xs text-gray-500">仅导出AI生成的高质量数据</p>
                </button>
              </div>
            </section>

            {/* 导出格式 */}
            <section>
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <FileJson size={16} className="text-accent-primary" />
                导出格式
              </h3>
              <div className="grid grid-cols-2 gap-3">
                {FORMATS.map(format => (
                  <button
                    key={format.id}
                    onClick={() => setConfig(prev => ({ ...prev, format: format.id }))}
                    className={cn(
                      'p-4 rounded-xl border text-left transition-all',
                      config.format === format.id
                        ? 'border-accent-primary bg-accent-primary/10'
                        : 'border-dark-500 hover:border-dark-400 bg-dark-700'
                    )}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-white">{format.name}</span>
                      {config.format === format.id && (
                        <Check size={16} className="text-accent-primary" />
                      )}
                    </div>
                    <p className="text-xs text-gray-500">{format.description}</p>
                    <span className="text-xs text-gray-600 mt-1 inline-block">.{format.extension}</span>
                  </button>
                ))}
              </div>
            </section>

            {/* RAG 知识库清洗模式 (仅 RAG 格式显示) */}
            {config.format === 'rag' && (
              <section>
                <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                  <Sparkles size={16} className="text-emerald-400" />
                  知识库清洗模式
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { id: 'distill', name: '🧪 知识蒸馏', desc: '按意图聚合→LLM蒸馏标准知识→合并手写知识库（推荐）', color: 'text-blue-400' },
                    { id: 'rule', name: '📏 规则清洗', desc: '去重+过滤+补元数据，快速免费', color: 'text-emerald-400' },
                    { id: 'llm', name: '✨ LLM 改写', desc: 'AI逐条改写为知识条目（后台异步）', color: 'text-yellow-400' },
                    { id: 'raw', name: '📄 原始数据', desc: '不做任何清洗', color: 'text-gray-400' },
                  ].map(mode => (
                    <button
                      key={mode.id}
                      onClick={() => setConfig(prev => ({ ...prev, rag_mode: mode.id }))}
                      className={cn(
                        'p-3 rounded-xl border text-left transition-all',
                        config.rag_mode === mode.id
                          ? mode.id === 'distill' ? 'border-blue-500 bg-blue-500/10' : 'border-emerald-500 bg-emerald-500/10'
                          : 'border-dark-500 hover:border-dark-400 bg-dark-700'
                      )}
                    >
                      <span className={cn('font-medium text-sm', mode.color)}>{mode.name}</span>
                      <p className="text-xs text-gray-500 mt-1">{mode.desc}</p>
                    </button>
                  ))}
                </div>
                {config.rag_mode === 'distill' && (
                  <div className="mt-3 space-y-3 bg-blue-500/5 border border-blue-500/20 p-3 rounded-lg">
                    <p className="text-xs text-blue-400/80">
                      🧪 蒸馏模式：将同类对话按意图分组，LLM 从多段对话中提炼出标准化知识条目，并与手写知识库合并
                    </p>
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-white">合并手写知识库</p>
                        <p className="text-xs text-gray-500">将 KNOWLEDGE_BASE 中的高质量条目合并（优先）</p>
                      </div>
                      <button
                        onClick={() => setConfig(prev => ({ ...prev, distill_include_kb: !prev.distill_include_kb }))}
                        className={cn(
                          'w-10 h-5 rounded-full transition-colors relative',
                          config.distill_include_kb ? 'bg-blue-500' : 'bg-dark-500'
                        )}
                      >
                        <div className={cn(
                          'w-4 h-4 rounded-full bg-white absolute top-0.5 transition-transform',
                          config.distill_include_kb ? 'translate-x-5' : 'translate-x-0.5'
                        )} />
                      </button>
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-white">展开问法变体</p>
                        <p className="text-xs text-gray-500">每个 variant 独立一行（火山引擎兼容）</p>
                      </div>
                      <button
                        onClick={() => setConfig(prev => ({ ...prev, distill_expand_variants: !prev.distill_expand_variants }))}
                        className={cn(
                          'w-10 h-5 rounded-full transition-colors relative',
                          config.distill_expand_variants ? 'bg-blue-500' : 'bg-dark-500'
                        )}
                      >
                        <div className={cn(
                          'w-4 h-4 rounded-full bg-white absolute top-0.5 transition-transform',
                          config.distill_expand_variants ? 'translate-x-5' : 'translate-x-0.5'
                        )} />
                      </button>
                    </div>
                  </div>
                )}
                {config.rag_mode === 'llm' && (
                  <p className="text-xs text-yellow-400/80 mt-2 bg-yellow-400/5 p-2 rounded-lg">
                    ⚠️ LLM 改写为后台异步任务，点击导出后会启动任务并显示实时进度，完成后可直接下载
                  </p>
                )}
              </section>
            )}

            {/* 质量筛选 */}
            <section>
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Sparkles size={16} className="text-accent-primary" />
                最低质量要求
              </h3>
              <div className="flex gap-3">
                {QUALITIES.map(q => (
                  <button
                    key={q.id}
                    onClick={() => setConfig(prev => ({ ...prev, min_quality: q.id }))}
                    className={cn(
                      'flex-1 p-3 rounded-xl border text-center transition-all',
                      config.min_quality === q.id
                        ? 'border-accent-primary bg-accent-primary/10'
                        : 'border-dark-500 hover:border-dark-400 bg-dark-700'
                    )}
                  >
                    <span className={cn('font-medium', q.color)}>{q.name}</span>
                    <p className="text-xs text-gray-500 mt-1">{q.description}</p>
                  </button>
                ))}
              </div>
            </section>

            {/* 内容分类 */}
            <section>
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Filter size={16} className="text-accent-primary" />
                内容分类筛选
                <span className="text-xs text-gray-500 font-normal">（不选则导出全部）</span>
              </h3>
              <div className="flex flex-wrap gap-2">
                {CATEGORIES.map(cat => (
                  <button
                    key={cat.id}
                    onClick={() => toggleCategory(cat.id)}
                    className={cn(
                      'px-4 py-2 rounded-lg border transition-all flex items-center gap-2',
                      config.categories.includes(cat.id)
                        ? 'border-accent-primary bg-accent-primary/10 text-white'
                        : 'border-dark-500 hover:border-dark-400 bg-dark-700 text-gray-400'
                    )}
                  >
                    <span>{cat.icon}</span>
                    <span className="text-sm">{cat.name}</span>
                  </button>
                ))}
              </div>
            </section>

            {/* 高级设置 */}
            <section>
              <h3 className="text-sm font-medium text-gray-300 mb-3">高级设置</h3>
              <div className="space-y-4 bg-dark-700 rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-white">包含 System Prompt</p>
                    <p className="text-xs text-gray-500">在对话开头添加系统提示</p>
                  </div>
                  <button
                    onClick={() => setConfig(prev => ({ ...prev, include_system_prompt: !prev.include_system_prompt }))}
                    className={cn(
                      'w-12 h-6 rounded-full transition-colors relative',
                      config.include_system_prompt ? 'bg-accent-primary' : 'bg-dark-500'
                    )}
                  >
                    <div className={cn(
                      'w-5 h-5 rounded-full bg-white absolute top-0.5 transition-transform',
                      config.include_system_prompt ? 'translate-x-6' : 'translate-x-0.5'
                    )} />
                  </button>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm text-white">对话切分时间窗口</p>
                    <span className="text-sm text-accent-primary">{config.time_window_seconds}秒</span>
                  </div>
                  <input
                    type="range"
                    min={60}
                    max={1800}
                    step={60}
                    value={config.time_window_seconds}
                    onChange={e => setConfig(prev => ({ ...prev, time_window_seconds: parseInt(e.target.value) }))}
                    className="w-full accent-accent-primary"
                  />
                  <p className="text-xs text-gray-500 mt-1">超过此时间间隔的消息将被切分为不同对话</p>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm text-white">单对话最大轮次</p>
                    <span className="text-sm text-accent-primary">{config.max_turns_per_conversation}轮</span>
                  </div>
                  <input
                    type="range"
                    min={5}
                    max={50}
                    step={5}
                    value={config.max_turns_per_conversation}
                    onChange={e => setConfig(prev => ({ ...prev, max_turns_per_conversation: parseInt(e.target.value) }))}
                    className="w-full accent-accent-primary"
                  />
                </div>
              </div>
            </section>

            {/* AI 增强 */}
            <section>
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Sparkles size={16} className="text-yellow-400" />
                AI 增强
                <span className="text-xs text-yellow-400 bg-yellow-400/10 px-2 py-0.5 rounded">推荐</span>
              </h3>
              <div className="space-y-4 bg-dark-700 rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-white">LLM 质量评分</p>
                    <p className="text-xs text-gray-500">用大模型评估每段对话质量，过滤低质量数据</p>
                  </div>
                  <button
                    onClick={() => setConfig(prev => ({ ...prev, use_llm_scoring: !prev.use_llm_scoring }))}
                    className={cn(
                      'w-12 h-6 rounded-full transition-colors relative',
                      config.use_llm_scoring ? 'bg-yellow-500' : 'bg-dark-500'
                    )}
                  >
                    <div className={cn(
                      'w-5 h-5 rounded-full bg-white absolute top-0.5 transition-transform',
                      config.use_llm_scoring ? 'translate-x-6' : 'translate-x-0.5'
                    )} />
                  </button>
                </div>

                {config.use_llm_scoring && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-sm text-white">最低评分</p>
                      <span className="text-sm text-yellow-400">{config.llm_min_score} 分</span>
                    </div>
                    <input
                      type="range"
                      min={1}
                      max={10}
                      step={0.5}
                      value={config.llm_min_score}
                      onChange={e => setConfig(prev => ({ ...prev, llm_min_score: parseFloat(e.target.value) }))}
                      className="w-full accent-yellow-500"
                    />
                    <p className="text-xs text-gray-500 mt-1">低于此分数的对话将被过滤（需要配置 LLM API）</p>
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-white">智能去重</p>
                    <p className="text-xs text-gray-500">移除相似度过高的重复对话</p>
                  </div>
                  <button
                    onClick={() => setConfig(prev => ({ ...prev, deduplicate: !prev.deduplicate }))}
                    className={cn(
                      'w-12 h-6 rounded-full transition-colors relative',
                      config.deduplicate ? 'bg-yellow-500' : 'bg-dark-500'
                    )}
                  >
                    <div className={cn(
                      'w-5 h-5 rounded-full bg-white absolute top-0.5 transition-transform',
                      config.deduplicate ? 'translate-x-6' : 'translate-x-0.5'
                    )} />
                  </button>
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-white">包含自定义数据</p>
                    <p className="text-xs text-gray-500">导出手动添加的自定义对话数据</p>
                  </div>
                  <button
                    onClick={() => setConfig(prev => ({ ...prev, include_custom: !prev.include_custom }))}
                    className={cn(
                      'w-12 h-6 rounded-full transition-colors relative',
                      config.include_custom ? 'bg-blue-500' : 'bg-dark-500'
                    )}
                  >
                    <div className={cn(
                      'w-5 h-5 rounded-full bg-white absolute top-0.5 transition-transform',
                      config.include_custom ? 'translate-x-6' : 'translate-x-0.5'
                    )} />
                  </button>
                </div>
              </div>
            </section>

            {error && (
              <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* TOS 上传成功提示 */}
            {tosResult && tosResult.success && (
              <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-start gap-3">
                <Cloud size={18} className="text-emerald-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-emerald-400 text-sm font-medium">已同步上传到 TOS 对象存储</p>
                  <p className="text-gray-500 text-xs mt-1 font-mono break-all">{tosResult.key}</p>
                  <p className="text-gray-600 text-xs mt-1">火山引擎知识库可直接导入此文件</p>
                </div>
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex gap-3 pt-4">
              <button
                onClick={handlePreview}
                disabled={loading}
                className="flex-1 py-3 px-4 bg-dark-600 hover:bg-dark-500 text-white rounded-xl transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Eye size={18} />
                )}
                预览数据
              </button>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="flex-1 py-3 px-4 bg-accent-primary hover:bg-accent-secondary text-white rounded-xl transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {exporting ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Download size={18} />
                )}
                {config.format === 'rag' && config.rag_mode === 'llm' ? '启动 LLM 改写' : config.format === 'rag' && config.rag_mode === 'distill' ? '🧪 启动知识蒸馏' : '直接导出'}
              </button>
            </div>
          </div>
        ) : (
          /* 预览页面 */
          <div className="max-w-4xl mx-auto">
            <button
              onClick={() => setStep('config')}
              className="mb-4 text-sm text-gray-400 hover:text-white transition-colors"
            >
              ← 返回配置
            </button>

            {preview && (
              <>
                {/* 空数据提示 */}
                {preview.statistics.total === 0 && (
                  <div className="mb-6 p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-xl">
                    <p className="text-yellow-400 text-sm">
                      {preview.statistics.message || '没有找到符合条件的训练数据。'}
                    </p>
                    <p className="text-gray-500 text-xs mt-2">
                      建议：降低"最低质量要求"到"低质量"，或取消分类筛选后重试。
                    </p>
                  </div>
                )}

                {/* 统计信息 */}
                <div className="grid grid-cols-3 gap-4 mb-6">
                  <StatCard label="已标注样本" value={preview.statistics.total} />
                  <StatCard label="已预览" value={preview.statistics.previewed || 0} />
                  <StatCard label="数据质量" value="高质量" suffix="" />
                </div>

                {/* 蒸馏统计 */}
                {preview.statistics.distill && (
                  <div className="bg-dark-700 rounded-xl p-4 mb-6">
                    <h4 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                      <Sparkles size={14} className="text-blue-400" />
                      知识蒸馏统计
                    </h4>
                    <div className="grid grid-cols-5 gap-2">
                      <div className="bg-dark-600 rounded-lg p-2 text-center">
                        <p className="text-white font-bold text-sm">{preview.statistics.distill.input}</p>
                        <p className="text-xs text-gray-500">输入</p>
                      </div>
                      <div className="bg-dark-600 rounded-lg p-2 text-center">
                        <p className="text-blue-400 font-bold text-sm">{preview.statistics.distill.groups}</p>
                        <p className="text-xs text-gray-500">分组</p>
                      </div>
                      <div className="bg-dark-600 rounded-lg p-2 text-center">
                        <p className="text-green-400 font-bold text-sm">{preview.statistics.distill.distilled}</p>
                        <p className="text-xs text-gray-500">蒸馏</p>
                      </div>
                      <div className="bg-dark-600 rounded-lg p-2 text-center">
                        <p className="text-purple-400 font-bold text-sm">{preview.statistics.distill.manual_entries}</p>
                        <p className="text-xs text-gray-500">手写</p>
                      </div>
                      <div className="bg-dark-600 rounded-lg p-2 text-center">
                        <p className="text-emerald-400 font-bold text-sm">{preview.statistics.distill.output}</p>
                        <p className="text-xs text-gray-500">输出</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* RAG 质量分析 */}
                {preview.statistics.rag_quality && (
                  <div className="bg-dark-700 rounded-xl p-4 mb-6">
                    <h4 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                      <Sparkles size={14} className="text-emerald-400" />
                      RAG 质量分析
                    </h4>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-xs text-gray-500 mb-2">内容形态</p>
                        <div className="space-y-1">
                          {Object.entries(preview.statistics.rag_quality.by_content_type || {}).map(([key, val]) => (
                            <div key={key} className="flex items-center justify-between text-xs">
                              <span className={cn(
                                key === 'knowledge' ? 'text-green-400' :
                                key === 'script' ? 'text-yellow-400' : 'text-gray-500'
                              )}>{key}</span>
                              <span className="text-white">{val as number}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500 mb-2">置信度分桶</p>
                        <div className="space-y-1">
                          {Object.entries(preview.statistics.rag_quality.by_confidence || {}).map(([key, val]) => (
                            <div key={key} className="flex items-center justify-between text-xs">
                              <span className="text-gray-400">{key}</span>
                              <span className="text-white">{val as number}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 pt-3 border-t border-dark-500 flex gap-4 text-xs">
                      <span className="text-gray-400">Source覆盖: <span className="text-white">{preview.statistics.rag_quality.source_coverage}</span></span>
                      <span className="text-gray-400">Tags覆盖: <span className="text-white">{preview.statistics.rag_quality.tags_coverage}</span></span>
                    </div>
                  </div>
                )}

                {/* 类别分布 */}
                {preview.statistics.by_category && Object.keys(preview.statistics.by_category).length > 0 && (
                  <div className="bg-dark-700 rounded-xl p-4 mb-6">
                    <h4 className="text-sm font-medium text-gray-300 mb-3">类别分布</h4>
                    <div className="space-y-2">
                      {Object.entries(preview.statistics.by_category).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between text-sm">
                          <span className="text-gray-400">{CATEGORIES.find(c => c.id === key)?.name || key}</span>
                          <span className="text-white">{value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 样本预览 */}
                <div className="bg-dark-700 rounded-xl p-4">
                  <h4 className="text-sm font-medium text-gray-300 mb-3">样本预览</h4>
                  <div className="space-y-4 max-h-96 overflow-y-auto">
                    {preview.preview.map((item, index) => (
                      <div key={index} className="bg-dark-600 rounded-lg p-3 text-sm">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="px-2 py-0.5 bg-accent-primary/20 text-accent-primary rounded text-xs">
                            {item.category || 'unknown'}
                          </span>
                          {item.content_type && (
                            <span className={cn(
                              'px-2 py-0.5 rounded text-xs',
                              item.content_type === 'knowledge' ? 'bg-green-500/20 text-green-400' :
                              item.content_type === 'script' ? 'bg-yellow-500/20 text-yellow-400' :
                              'bg-gray-500/20 text-gray-400'
                            )}>
                              {item.content_type}
                            </span>
                          )}
                          {item.confidence && (
                            <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">
                              {item.confidence}
                            </span>
                          )}
                          <span className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">
                            {item.quality || 'medium'}
                          </span>
                        </div>
                        <pre className="text-gray-300 whitespace-pre-wrap text-xs overflow-x-auto">
                          {JSON.stringify(item.question ? { question: item.question, answer: item.answer, category: item.category } : item.conversations?.slice(0, 3) || item, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 导出按钮 */}
                <div className="mt-6">
                  <button
                    onClick={handleExport}
                    disabled={exporting}
                    className="w-full py-4 bg-accent-primary hover:bg-accent-secondary text-white rounded-xl transition-colors flex items-center justify-center gap-2 disabled:opacity-50 text-lg font-medium"
                  >
                    {exporting ? (
                      <Loader2 size={20} className="animate-spin" />
                    ) : (
                      <Download size={20} />
                    )}
                    {config.format === 'rag' && config.rag_mode === 'llm'
                      ? '启动 LLM 改写'
                      : config.format === 'rag' && config.rag_mode === 'distill'
                        ? `🧪 蒸馏导出 ${preview.statistics.total} 条知识`
                        : `导出 ${preview.statistics.total} 条训练数据`}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, suffix = '' }: { label: string; value: number | string; suffix?: string }) {
  return (
    <div className="bg-dark-700 rounded-xl p-4 text-center">
      <p className="text-2xl font-bold text-white">{value}{suffix}</p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  )
}
