import axios from 'axios'
import type { Session, Message, SearchResult, PaginatedResponse } from './types'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动带上 token
api.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：处理 401 退出登录
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      // Token 过期或无效，清除并派发事件（AuthContext 会监听）
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      window.dispatchEvent(new Event('auth:unauthorized'))
    }
    return Promise.reject(error)
  }
)

// 会话相关
export async function getSessions(params: {
  page?: number
  page_size?: number
  search?: string
  session_type?: 'all' | 'private' | 'chatroom'  // 新参数：会话类型
  exclude_chatroom?: boolean  // 是否排除群聊（默认true）
}): Promise<PaginatedResponse<Session>> {
  const { data } = await api.get('/chats/sessions', { params })
  return data
}

export async function getSession(sessionId: string): Promise<Session> {
  const { data } = await api.get(`/chats/sessions/${encodeURIComponent(sessionId)}`)
  return data
}

// 聊天历史
export async function getChatHistory(
  sessionId: string,
  params: {
    page?: number
    page_size?: number
    before_time?: number
    after_time?: number
    msg_type?: number
  }
): Promise<PaginatedResponse<Message>> {
  const { data } = await api.get(`/chats/history/${encodeURIComponent(sessionId)}`, { params })
  return data
}

// 消息上下文（搜索跳转定位用）
export async function getMessageContext(
  messageId: number,
  contextSize: number = 25
): Promise<{
  target_message_id: number
  session_id: string
  items: Message[]
  total: number
}> {
  const { data } = await api.get(`/chats/context/${messageId}`, {
    params: { context_size: contextSize }
  })
  return data
}

// 搜索相关
export async function searchMessages(params: {
  q: string
  page?: number
  page_size?: number
  session_id?: string
  start_time?: number
  end_time?: number
}): Promise<{
  items: SearchResult[]
  total: number
  query: string
  page: number
  page_size: number
  has_more: boolean
}> {
  const { data } = await api.get('/search/messages', { params })
  return data
}

export async function searchSessions(q: string, limit = 10): Promise<{
  session_id: string
  display_name: string
  is_chatroom: boolean
  message_count: number
}[]> {
  const { data } = await api.get('/search/sessions', { params: { q, limit } })
  return data
}

// 后台管理相关
export interface StagingQc {
  id: number
  agent_name?: string | null
  config_name?: string | null
  overall_score: number | null          // 0-100
  scores: Record<string, number> | null // {维度key: 0-100}
  violations: QcViolation[] | null
  scored: boolean                        // false = LLM不可用/未评分
  status: string
  summary?: string | null
  suggestions?: string | null
  created_at?: string | null
}

export interface StagingConversation {
  id: number
  session_id: string
  original_text: string
  cleaned_text: string
  conversation_json: Array<{ role: string; content: string; sender_name?: string; msg_id: number; timestamp: number }>
  auto_question?: string
  auto_answer?: string
  human_question?: string
  human_answer?: string
  auto_category?: string
  human_category?: string
  auto_quality_score?: number
  auto_flags?: Record<string, any>
  qc?: StagingQc | null
  human_notes?: string
  status: string
  start_time: number
  end_time: number
  source_message_ids: number[]
  created_at?: string
}

export interface AdminStats {
  raw_chats: {
    total: number
    pending: number
    approved: number
    rejected: number
  }
  sessions: {
    total: number
    processed: number
    unprocessed: number
  }
  staging_conversations: {
    total: number
    pending: number
    approved: number
    rejected: number
  }
}

export async function getAdminStats(): Promise<AdminStats> {
  const { data } = await api.get('/admin/stats')
  return data
}

export async function preprocessSessions(params: {
  session_ids?: string[]
  window_seconds?: number
  limit?: number
  process_all?: boolean
}): Promise<{ total_created: number; results: Array<{ session_id: string; created?: number; error?: string }>; processed: number; total: number; has_more: boolean }> {
  const timeout = params.process_all ? 300000 : 30000
  const { data } = await api.post('/admin/preprocess', params, { timeout })
  return data
}

export async function getStagingConversations(params: {
  status?: string
  session_id?: string
  category?: string
  min_quality?: number
  page?: number
  page_size?: number
}): Promise<{ total: number; page: number; page_size: number; items: StagingConversation[] }> {
  const { data } = await api.get('/admin/staging/list', { params })
  return data
}

export async function getStagingDetail(stagingId: number): Promise<{
  staging: StagingConversation
  original_messages: Array<{
    id: number
    sender_name?: string
    content: string
    clean_content?: string
    timestamp: number
    msg_type: number
    is_sender: boolean
    status: string
    auto_category?: string
  }>
}> {
  const { data } = await api.get(`/admin/staging/${stagingId}`)
  return data
}

export async function updateStaging(stagingId: number, params: {
  cleaned_text?: string
  human_question?: string
  human_answer?: string
  human_category?: string
  human_notes?: string
}): Promise<{ success: boolean; message: string }> {
  const { data } = await api.put(`/admin/staging/${stagingId}`, params)
  return data
}

export async function approveStaging(stagingId: number, category?: string): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post(`/admin/staging/${stagingId}/approve`, null, { params: { category } })
  return data
}

export async function rejectStaging(stagingId: number, notes?: string): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post(`/admin/staging/${stagingId}/reject`, null, { params: { notes } })
  return data
}

export async function batchActionStaging(params: {
  staging_ids: number[]
  action: 'approve' | 'reject' | 'delete'
  category?: string
  notes?: string
}): Promise<{ success: boolean; updated: number; deleted: number }> {
  const { data } = await api.post('/admin/staging/batch', params)
  return data
}

export async function mergeMessages(messageIds: number[]): Promise<{ success: boolean; staging_id: number; message: string }> {
  const { data } = await api.post('/admin/messages/merge', { message_ids: messageIds })
  return data
}

export async function bulkFilter(params: {
  keyword: string
  action: 'reject' | 'approve'
  session_ids?: string[]
}): Promise<{ success: boolean; updated: number; keyword: string }> {
  const { data } = await api.post('/admin/bulk-filter', params)
  return data
}

export async function publishStaging(stagingId: number): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post(`/admin/staging/${stagingId}/publish`)
  return data
}

export async function cleanOldData(): Promise<{ success: boolean; deleted_old_time: number; deleted_chatroom: number; total_deleted: number; message: string }> {
  const { data } = await api.post('/admin/clean-old-data')
  return data
}

// 知识库相关
export async function buildKnowledgeFromLabeled(clearExisting: boolean = true): Promise<{
  success: boolean
  message: string
  stats: {
    total_approved: number
    chunks_created: number
    deleted_old: number
  }
}> {
  const { data } = await api.post('/knowledge/build-from-labeled', null, {
    params: { clear_existing: clearExisting }
  })
  return data
}

export async function getKnowledgeStats(): Promise<{
  total_chunks: number
  total_sessions: number
  sessions_with_chunks: number
  avg_chunks_per_session: number
}> {
  const { data } = await api.get('/knowledge/stats')
  return data
}

// 已标注数据导出相关
export async function previewLabeledExport(config: {
  format?: string
  include_system_prompt?: boolean
  categories?: string[]
}, limit: number = 10): Promise<{
  preview: any[]
  statistics: {
    total: number
    previewed?: number
    by_category?: Record<string, number>
    message?: string
  }
  config: any
}> {
  const { data } = await api.post('/export/labeled/preview', config, {
    params: { limit }
  })
  return data
}

export async function exportLabeledDataset(config: {
  format?: string
  include_system_prompt?: boolean
  categories?: string[]
}): Promise<Blob> {
  const response = await api.post('/export/labeled/dataset', config, {
    responseType: 'blob'
  })
  return response.data
}

// ==================== 知识提炼（Extractor） ====================

export interface KnowledgeArticleData {
  id: number
  scene: string
  scene_category: string | null
  customer_says: string | null
  recommended_response: string | null
  key_points: string[] | null
  source_chunk_id: number | null
  source_session_id: string | null
  source_type: string | null
  confidence: number
  is_verified: boolean
  created_at: string | null
}

export interface ExtractorStats {
  total_articles: number
  verified_articles: number
  unverified_articles: number
  avg_confidence: number
  by_category: Record<string, number>
}

/** 触发知识提炼（后台异步执行） */
export async function triggerExtraction(source: string = 'both'): Promise<{
  message: string
  source: string
  status: string
}> {
  const { data } = await api.post('/extractor/extract', { source })
  return data
}

/** 获取提炼的知识条目列表 */
export async function getArticles(params: {
  category?: string
  verified?: boolean
  skip?: number
  limit?: number
}): Promise<KnowledgeArticleData[]> {
  const { data } = await api.get('/extractor/articles', { params })
  return data
}

/** 更新知识条目 */
export async function updateArticle(articleId: number, payload: {
  scene?: string
  scene_category?: string
  customer_says?: string
  recommended_response?: string
  key_points?: string[]
  is_verified?: boolean
}): Promise<KnowledgeArticleData> {
  const { data } = await api.put(`/extractor/articles/${articleId}`, payload)
  return data
}

/** 删除知识条目 */
export async function deleteArticle(articleId: number): Promise<{ message: string }> {
  const { data } = await api.delete(`/extractor/articles/${articleId}`)
  return data
}

/** 获取提炼统计信息 */
export async function getExtractorStats(): Promise<ExtractorStats> {
  const { data } = await api.get('/extractor/stats')
  return data
}

// ==================== AI 考核 ====================

export interface QuizQuestion {
  id: number
  question: string
  reference_answer: string
  category: string
  difficulty: string
}

export interface QuizData {
  id: number
  title: string
  category: string
  question_count: number
  questions: QuizQuestion[]
  status: string
  attempt_count?: number
  created_at: string | null
}

export interface QuizAttemptData {
  id: number
  quiz_id: number
  quiz_title: string | null
  quiz_category?: string | null
  questions?: QuizQuestion[]
  user_answers: { question_id: number; answer: string }[] | null
  ai_evaluation: { question_id: number; score: number; feedback: string; is_reasonable: boolean }[] | null
  ai_total_score: number | null
  human_score: number | null
  human_feedback: string | null
  status: string
  created_at: string | null
  submitted_at: string | null
  graded_at: string | null
}

export async function generateQuiz(params: {
  category?: string
  count?: number
  title?: string
}): Promise<{ id: number; title: string; category: string; question_count: number; questions: QuizQuestion[] }> {
  const { data } = await api.post('/quiz/generate', params, { timeout: 60000 })
  return data
}

export async function getQuizList(params?: {
  category?: string
  skip?: number
  limit?: number
}): Promise<{ total: number; items: QuizData[] }> {
  const { data } = await api.get('/quiz/list', { params })
  return data
}

export async function getQuiz(quizId: number): Promise<QuizData> {
  const { data } = await api.get(`/quiz/${quizId}`)
  return data
}

export async function deleteQuiz(quizId: number): Promise<{ message: string }> {
  const { data } = await api.delete(`/quiz/${quizId}`)
  return data
}

export async function startQuizAttempt(quizId: number): Promise<{ attempt_id: number }> {
  const { data } = await api.post(`/quiz/${quizId}/start`)
  return data
}

export async function submitQuizAnswers(attemptId: number, answers: { question_id: number; answer: string }[]): Promise<{ message: string; attempt_id: number }> {
  const { data } = await api.post(`/quiz/attempt/${attemptId}/submit`, { answers })
  return data
}

export async function aiGradeAttempt(attemptId: number): Promise<{
  attempt_id: number
  evaluations: { question_id: number; score: number; feedback: string; is_reasonable: boolean }[]
  ai_total_score: number
}> {
  const { data } = await api.post(`/quiz/attempt/${attemptId}/ai-grade`, null, { timeout: 60000 })
  return data
}

export async function humanReviewAttempt(attemptId: number, params: {
  human_score: number
  human_feedback: string
}): Promise<{ attempt_id: number; human_score: number }> {
  const { data } = await api.put(`/quiz/attempt/${attemptId}/human-review`, params)
  return data
}

export async function getQuizAttempt(attemptId: number): Promise<QuizAttemptData> {
  const { data } = await api.get(`/quiz/attempt/${attemptId}`)
  return data
}

export async function getQuizAttempts(params?: {
  quiz_id?: number
  status?: string
  skip?: number
  limit?: number
}): Promise<{ total: number; items: QuizAttemptData[] }> {
  const { data } = await api.get('/quiz/attempts/list', { params })
  return data
}

// ==================== 多轮对话实训 ====================

/** 情景所绑定的真实对话（1:1 提炼的来源，仅溯源信息，不含对话内容） */
export interface DialogueSource {
  conversation_id: number
  session_id: string
  quality_score?: number | null
  turn_count?: number
}

export interface DialogueScenario {
  id: number
  category: string
  difficulty: string
  customer_persona: string
  customer_background: string
  opening_line: string
  hidden_needs: string
  expected_points: string
  /** 来源真实对话（旧情景可能没有） */
  source?: DialogueSource | null
  session?: { id: number; status: string; turn_count: number } | null
  // 注意：参考答案 / 原始真实对话（reference_replies / source_transcript）刻意不在此类型内，
  // 它们只在会话结束后的回看页出现（DialogueSessionData），绝不进入练习链路。
}

export interface DialogueSetData {
  id: number
  title: string
  category: string
  scenario_count: number
  status?: string
  session_count?: number
  finished_count?: number
  scenarios?: DialogueScenario[]
  created_at: string | null
}

export interface DialogueTurn {
  role: 'customer' | 'agent'
  content: string
}

export interface DialogueSessionData {
  id: number
  set_id: number
  set_title: string | null
  scenario_id: number
  category: string | null
  scenario?: DialogueScenario
  status: string
  turn_count: number
  transcript: DialogueTurn[]
  customer_persona?: string | null
  opening_line?: string | null
  created_at: string | null
  finished_at: string | null
  /** 以下三项仅当 status === 'finished' 时后端才下发（参考答案，用于回看页） */
  reference_replies?: string[]
  source_transcript?: DialogueTurn[]
  source?: DialogueSource | null
}

export async function generateDialogueSet(params: {
  category?: string
  count?: number
  title?: string
}): Promise<{
  id: number
  title: string
  category: string
  scenario_count: number
  scenarios: DialogueScenario[]
  source_stats?: {
    requested: number
    produced: number
    failed: number
    available: number
    matched: number
  }
}> {
  // 逐条真实对话各调用一次 LLM，count 较大时耗时较长，故放宽超时
  const { data } = await api.post('/dialogue/generate', params, { timeout: 300000 })
  return data
}

export async function getDialogueSets(params?: {
  category?: string
  skip?: number
  limit?: number
}): Promise<{ total: number; items: DialogueSetData[] }> {
  const { data } = await api.get('/dialogue/sets', { params })
  return data
}

export async function getDialogueSet(setId: number): Promise<DialogueSetData> {
  const { data } = await api.get(`/dialogue/sets/${setId}`)
  return data
}

export async function deleteDialogueSet(setId: number): Promise<{ message: string }> {
  const { data } = await api.delete(`/dialogue/sets/${setId}`)
  return data
}

export async function startDialogueSession(setId: number, scenarioId: number): Promise<{
  session_id: number
  set_id: number
  scenario_id: number
  transcript: DialogueTurn[]
  turn_count: number
  max_turns: number
  status: string
}> {
  const { data } = await api.post(`/dialogue/sets/${setId}/sessions`, { scenario_id: scenarioId })
  return data
}

export async function replyDialogue(sessionId: number, content: string): Promise<{
  customer_reply: string
  is_end: boolean
  turn_count: number
  max_turns: number
  status: string
}> {
  const { data } = await api.post(`/dialogue/sessions/${sessionId}/reply`, { content }, { timeout: 60000 })
  return data
}

export async function finishDialogue(sessionId: number): Promise<{ session_id: number; status: string; turn_count: number }> {
  const { data } = await api.post(`/dialogue/sessions/${sessionId}/finish`)
  return data
}

export async function getDialogueSessions(params?: {
  set_id?: number
  status?: string
  skip?: number
  limit?: number
}): Promise<{ total: number; items: DialogueSessionData[] }> {
  const { data } = await api.get('/dialogue/sessions', { params })
  return data
}

export async function getDialogueSession(sessionId: number): Promise<DialogueSessionData> {
  const { data } = await api.get(`/dialogue/sessions/${sessionId}`)
  return data
}

// ==================== 客服质检（会话质检） ====================

export interface QcDimension {
  key: string
  name: string
  weight: number
  description?: string
  scale?: number
}

export interface QcViolationType {
  key: string
  name: string
  severity?: string
  description?: string
}

export interface QcConfigSchema {
  name: string
  description?: string
  business_persona?: string
  model?: string
  dimensions: QcDimension[]
  violations: QcViolationType[]
  pass_threshold?: number
  timeout_seconds?: number
  max_retries?: number
  language?: string
}

/** 当前配置 + 默认值，供表单初始化（系统中只维护一份配置） */
export interface QcCurrentConfig {
  current: {
    id: number
    name: string
    description: string | null
    is_default: boolean
    is_active: boolean
    config: QcConfigSchema
    updated_at: string | null
  } | null
  default: QcConfigSchema
}

export interface QcViolation {
  type: string
  severity?: string
  evidence?: string
  suggestion?: string
}

export interface QcInspection {
  id: number
  session_id: string
  agent_name: string | null
  config_id: number | null
  config_name: string | null
  overall_score: number | null
  scores: Record<string, number> | null
  violations: QcViolation[] | null
  scored: boolean
  status: string
  human_override_score: number | null
  human_notes: string | null
  reviewer: string | null
  created_at: string | null
  reviewed_at: string | null
}

export interface QcInspectionDetail extends QcInspection {
  conversation_snapshot: any[] | null
  summary: string | null
  suggestions: string | null
  llm_raw: string | null
  start_time: number | null
  end_time: number | null
}

export interface QcStats {
  total: number
  avg_score: number | null
  pass_rate: number | null
  threshold: number
  score_distribution: Record<string, number>
  top_violations: { type: string; count: number }[]
  agent_leaderboard: { agent_name: string; avg_score: number; count: number }[]
  by_status: Record<string, number>
}

export async function getCurrentQcConfig(): Promise<QcCurrentConfig> {
  const { data } = await api.get('/qc/config')
  return data
}

export async function seedDefaultQcConfig(): Promise<{ id: number; message: string }> {
  const { data } = await api.post('/qc/config/seed-default')
  return data
}

export async function saveQcConfig(payload: QcConfigSchema): Promise<{ id: number; message: string }> {
  const { data } = await api.put('/qc/config', payload)
  return data
}

export async function inspectSession(sessionId: string): Promise<QcInspectionDetail> {
  const { data } = await api.post('/qc/inspect', { session_id: sessionId }, { timeout: 120000 })
  return data
}

export async function batchInspect(sessionIds: string[]): Promise<{ message: string; accepted: number }> {
  const { data } = await api.post('/qc/batch', { session_ids: sessionIds })
  return data
}

export async function listInspections(params: {
  session_id?: string
  agent_name?: string
  min_score?: number
  max_score?: number
  violation_type?: string
  status?: string
  config_id?: number
  scored?: boolean
  page?: number
  page_size?: number
}): Promise<{ total: number; page: number; page_size: number; items: QcInspection[] }> {
  const { data } = await api.get('/qc/list', { params })
  return data
}

export async function getInspection(id: number): Promise<QcInspectionDetail> {
  const { data } = await api.get(`/qc/${id}`)
  return data
}

export async function reviewInspection(id: number, params: { human_override_score?: number; human_notes?: string }): Promise<QcInspectionDetail> {
  const { data } = await api.post(`/qc/${id}/review`, params)
  return data
}

export async function getQcStats(): Promise<QcStats> {
  const { data } = await api.get('/qc/stats/summary')
  return data
}

/** 数据回流 / 反向优化数据包 */
export interface QcFeedback {
  total: number
  threshold: number
  weak_dimensions: { key: string; name: string; avg: number; sample_count: number }[]
  top_violations: { type: string; count: number }[]
  wrong_cases: {
    inspection_id: number
    session_id: string
    agent_name: string | null
    overall_score: number | null
    weak_dimension: string | null
    violations: string[]
    summary: string | null
  }[]
  supervisor_corrections: {
    inspection_id: number
    session_id: string
    ai_score: number | null
    human_score: number
    delta: number | null
    human_notes: string | null
  }[]
  training_topics: string[]
  optimization: {
    training_materials: string[]
    scripts: string[]
    knowledge_slices: string[]
    content_direction: string[]
  }
}

export async function getQcFeedback(): Promise<QcFeedback> {
  const { data } = await api.get('/qc/feedback')
  return data
}

// ==================== 质检校准（人工标注 / 分组 / 版本对比） ====================

/** 质检配置版本（保存配置时按内容去重生成） */
export interface QcConfigVersionInfo {
  id: number
  config_id: number | null
  version: number
  name: string | null
  note: string | null
  content_hash: string | null
  is_current: boolean
  created_at: string | null
}

/** 校准分组 */
export interface CalibrationGroup {
  id: number
  name: string
  description: string | null
  item_count: number
  run_count: number
  created_at: string | null
  updated_at: string | null
}

/** 校准集条目（人工标注真值，冻结） */
export interface CalibrationItem {
  id: number
  group_id: number
  session_id: string
  agent_name: string | null
  gold_total: number | null
  gold_scores: Record<string, number>
  start_time: number | null
  end_time: number | null
  note: string | null
  added_config_version_id: number | null
  created_at: string | null
}

/** 校准聚合指标（null 表示样本不足，非 0） */
export interface CalibrationMetrics {
  item_count: number
  scored_count: number
  unscored_count: number
  empty_count: number
  llm_error_count: number
  missing_dim_count: number
  threshold: number | null
  mae_total: number | null
  rmse: number | null
  bias: number | null
  severe_count: number
  severe_delta: number
  pass_agree_rate: number | null
  pass_compared: number
  false_pass: number
  false_fail: number
  ai_dim_mean: number | null
  gold_dim_mean: number | null
  dim_mean_bias: number | null
  mae_by_dim: Record<string, number | null>
  dim_bias: Record<string, number | null>
  dim_keys: string[]
  dims_compared: string[]
  dims_missing_in_ai: string[]
  dims_missing_in_gold: string[]
  gold_dim_keys: string[]
  dim_set_changed: boolean
}

/** 校准运行（一次重跑） */
export interface CalibrationRun {
  id: number
  group_id: number
  config_version_id: number | null
  config_version: number | null
  config_name: string | null
  pass_threshold: number | null
  status: 'pending' | 'running' | 'done' | 'failed' | string
  total: number
  done_count: number
  failed_count: number
  metrics: CalibrationMetrics | null
  error: string | null
  created_at: string | null
  finished_at: string | null
}

/** 校准运行的逐条对比结果 */
export interface CalibrationRunItem {
  id: number
  session_id: string
  ai_total: number | null
  ai_scores: Record<string, number> | null
  ai_scored: boolean
  ai_missing_dims: string[] | null
  ai_error: string | null
  gold_total: number | null
  gold_scores: Record<string, number> | null
  delta_total: number | null
  per_dim_delta: Record<string, number> | null
  pass_agree: boolean | null
  violations: QcViolation[] | null
  summary: string | null
}

/** 跨版本对比行 */
export interface CalibrationCompareRow {
  run_id: number
  config_version: number | null
  config_name: string | null
  pass_threshold: number | null
  item_count: number | null
  mae_total: number | null
  bias: number | null
  rmse: number | null
  pass_agree_rate: number | null
  false_pass: number | null
  false_fail: number | null
  ai_dim_mean: number | null
  gold_dim_mean: number | null
  dim_set_changed: boolean | null
  created_at: string | null
}

export async function listQcConfigVersions(): Promise<{ items: QcConfigVersionInfo[] }> {
  const { data } = await api.get('/qc/config/versions')
  return data
}

export async function listCalibrationGroups(): Promise<{ items: CalibrationGroup[] }> {
  const { data } = await api.get('/qc/calibration/groups')
  return data
}

export async function createCalibrationGroup(payload: { name: string; description?: string }): Promise<CalibrationGroup> {
  const { data } = await api.post('/qc/calibration/groups', payload)
  return data
}

export async function deleteCalibrationGroup(groupId: number): Promise<{ message: string; id: number }> {
  const { data } = await api.delete(`/qc/calibration/groups/${groupId}`)
  return data
}

export async function listCalibrationItems(groupId: number): Promise<{ items: CalibrationItem[]; total: number }> {
  const { data } = await api.get(`/qc/calibration/groups/${groupId}/items`)
  return data
}

export async function addCalibrationItem(groupId: number, payload: {
  session_id: string
  gold_total: number
  gold_scores?: Record<string, number>
  start_time?: number
  end_time?: number
  agent_name?: string
  note?: string
}): Promise<CalibrationItem> {
  const { data } = await api.post(`/qc/calibration/groups/${groupId}/items`, payload)
  return data
}

export async function updateCalibrationItem(itemId: number, payload: {
  gold_total?: number
  gold_scores?: Record<string, number>
  note?: string
}): Promise<CalibrationItem> {
  const { data } = await api.put(`/qc/calibration/items/${itemId}`, payload)
  return data
}

export async function deleteCalibrationItem(itemId: number): Promise<{ message: string; id: number }> {
  const { data } = await api.delete(`/qc/calibration/items/${itemId}`)
  return data
}

export async function runCalibration(groupId: number, configVersionId?: number): Promise<{
  run_id: number
  status: string
  total: number
  config_version: number | null
}> {
  const { data } = await api.post(`/qc/calibration/groups/${groupId}/run`, {
    config_version_id: configVersionId ?? null,
  })
  return data
}

export async function listCalibrationRuns(groupId: number): Promise<{ items: CalibrationRun[]; total: number }> {
  const { data } = await api.get(`/qc/calibration/groups/${groupId}/runs`)
  return data
}

export async function getCalibrationCompare(groupId: number): Promise<{ items: CalibrationCompareRow[] }> {
  const { data } = await api.get(`/qc/calibration/groups/${groupId}/compare`)
  return data
}

export async function getCalibrationRun(runId: number, page = 1, pageSize = 20): Promise<{
  run: CalibrationRun
  items: CalibrationRunItem[]
  total: number
  page: number
  page_size: number
}> {
  const { data } = await api.get(`/qc/calibration/runs/${runId}`, {
    params: { page, page_size: pageSize },
  })
  return data
}

// ─── Agent 与 Skill/MCP 配置 ───────────────────────────────────────────────────

export interface AgentConfig {
  id?: number
  agent_id: string
  name: string
  description?: string | null
  agent_type: 'faq' | 'dialogue' | 'ticket' | 'complaint' | string
  status: 'active' | 'inactive' | 'draft'
  priority: number
  supported_intents: string[]
  supported_emotions: string[]
  skill_ids: string[]
  mcp_server_ids: string[]
  config_json?: Record<string, any> | null
  created_at?: string
  updated_at?: string
}

export interface AgentTool {
  tool_name: string
  description: string
  parameters: Record<string, any>
}

export interface AgentListResponse {
  agents: AgentConfig[]
}

export interface AgentRegisterPayload {
  agent_id: string
  name: string
  description?: string
  agent_type: string
  supported_intents: string[]
  supported_emotions: string[]
  priority?: number
  config?: Record<string, any>
  skill_ids?: string[]
  mcp_server_ids?: string[]
}

export interface AgentUpdatePayload {
  name?: string
  description?: string
  status?: 'active' | 'inactive' | 'draft'
  priority?: number
  supported_intents?: string[]
  supported_emotions?: string[]
  config?: Record<string, any>
  skill_ids?: string[]
  mcp_server_ids?: string[]
}

export interface AvailableSkillOption {
  id: string
  name: string
  description?: string | null
}

export interface AvailableMcpOption {
  id: string
  name: string
  description?: string | null
  status: string
}

export interface AvailableToolsResponse {
  skills: AvailableSkillOption[]
  mcp_servers: AvailableMcpOption[]
}

export async function listAgentConfigs(): Promise<AgentListResponse> {
  const { data } = await api.get('/agent/list')
  return data
}

export async function registerAgent(payload: AgentRegisterPayload): Promise<{ message: string; agent_id: string }> {
  const { data } = await api.post('/agent/register', payload)
  return data
}

export async function updateAgent(agentId: string, payload: AgentUpdatePayload): Promise<{ message: string; agent_id: string }> {
  const { data } = await api.put(`/agent/update/${encodeURIComponent(agentId)}`, payload)
  return data
}

export async function listTools(): Promise<AgentTool[]> {
  const { data } = await api.get('/agent/tools')
  return data.tools ?? []
}

export async function listAvailableTools(): Promise<AvailableToolsResponse> {
  const { data } = await api.get('/agent/tools/available')
  return data
}

// ==================== Agent 会话管理 ====================

export interface AgentSessionData {
  session_id: string
  user_id: string | null
  display_name: string | null
  last_message: string | null
  message_count: number
  created_at: string | null
  updated_at: string | null
}

export interface AgentSessionCreatePayload {
  session_id: string
  user_id?: string | null
  display_name?: string | null
}

export async function listAgentSessions(params?: {
  user_id?: string
  limit?: number
}): Promise<{ sessions: AgentSessionData[] }> {
  const { data } = await api.get('/agent/sessions', { params })
  return data
}

export async function getAgentSession(sessionId: string): Promise<AgentSessionData> {
  const { data } = await api.get(`/agent/sessions/${encodeURIComponent(sessionId)}`)
  return data
}

export async function createAgentSession(payload: AgentSessionCreatePayload): Promise<AgentSessionData> {
  const { data } = await api.post('/agent/sessions', payload)
  return data
}

export async function deleteAgentSession(sessionId: string): Promise<{ message: string }> {
  const { data } = await api.delete(`/agent/sessions/${encodeURIComponent(sessionId)}`)
  return data
}

// ==================== Agent 消息历史 ====================

export interface AgentMessage {
  id?: number
  session_id: string
  turn_number: number
  role: 'user' | 'assistant'
  content: string
  intent?: string | null
  confidence?: number | null
  emotion?: string | null
  emotion_intensity?: number | null
  needs_transfer?: boolean | null
  ticket_no?: string | null
  created_at?: string | null
}

export async function listAgentMessages(
  sessionId: string,
  limit: number = 100
): Promise<{ messages: AgentMessage[] }> {
  const { data } = await api.get(`/agent/sessions/${encodeURIComponent(sessionId)}/messages`, {
    params: { limit },
  })
  return data
}

// ==================== Skills 管理 ====================

export interface SkillItem {
  id: string
  name: string
  description: string | null
  content: string
  type: string
  project_id: number | null
  source: string
  installation_time: string
  status: string
  file_path: string | null
  is_builtin: boolean
}

export type SkillSource = 'local_import' | 'backend_generated' | 'system_builtin' | 'uploaded_file'

export interface SkillCreatePayload {
  id: string
  name: string
  description?: string | null
  content: string
  type?: string
  project_id?: number | null
  source?: SkillSource
  status?: string
  file_path?: string | null
}

export interface SkillUpdatePayload {
  name?: string
  description?: string | null
  content?: string
  type?: string
  project_id?: number | null
  status?: string
}

export async function listSkills(projectId?: number | null): Promise<SkillItem[]> {
  const { data } = await api.get('/skills', { params: projectId ? { project_id: projectId } : {} })
  return data
}

export async function getSkill(skillId: string): Promise<SkillItem> {
  const { data } = await api.get(`/skills/${encodeURIComponent(skillId)}`)
  return data
}

export async function createSkill(payload: SkillCreatePayload): Promise<SkillItem> {
  const { data } = await api.post('/skills', payload)
  return data
}

export async function updateSkill(skillId: string, payload: SkillUpdatePayload): Promise<SkillItem> {
  const { data } = await api.put(`/skills/${encodeURIComponent(skillId)}`, payload)
  return data
}

export async function deleteSkill(skillId: string): Promise<{ message: string }> {
  const { data } = await api.delete(`/skills/${encodeURIComponent(skillId)}`)
  return data
}

export async function uploadSkill(skillId: string, content: string, projectId?: number | null): Promise<SkillItem> {
  const { data } = await api.post('/skills/upload', null, {
    params: { skill_id: skillId, project_id: projectId ?? undefined },
    data: { file_content: content },
  })
  return data
}

// ==================== MCP Server 管理 ====================

export type McpServerType = 'stdio' | 'sse' | 'streamableHttp'
export type McpServerStatus = string  // connected / disconnected / error:...

export interface McpServer {
  id: string
  name: string
  description: string | null
  type: McpServerType
  command: string | null
  args: string[] | null
  url: string | null
  headers: Record<string, string> | null
  env: Record<string, string> | null
  project_id: number | null
  status: McpServerStatus
  created_at: string
  updated_at: string
}

export interface McpServerCreatePayload {
  name: string
  description?: string | null
  type: McpServerType
  command?: string | null
  args?: string[] | null
  url?: string | null
  headers?: Record<string, string> | null
  env?: Record<string, string> | null
  project_id?: number | null
}

export interface McpServerUpdatePayload {
  name?: string
  description?: string | null
  type?: McpServerType
  command?: string | null
  args?: string[] | null
  url?: string | null
  headers?: Record<string, string> | null
  env?: Record<string, string> | null
  status?: McpServerStatus
}

export async function listMcpServers(projectId?: number | null): Promise<McpServer[]> {
  const { data } = await api.get('/mcp/servers', { params: projectId ? { project_id: projectId } : {} })
  return data
}

export async function getMcpServer(serverId: string): Promise<McpServer> {
  const { data } = await api.get(`/mcp/servers/${encodeURIComponent(serverId)}`)
  return data
}

export async function createMcpServer(payload: McpServerCreatePayload): Promise<McpServer> {
  const { data } = await api.post('/mcp/servers', payload)
  return data
}

export async function updateMcpServer(serverId: string, payload: McpServerUpdatePayload): Promise<McpServer> {
  const { data } = await api.put(`/mcp/servers/${encodeURIComponent(serverId)}`, payload)
  return data
}

export async function deleteMcpServer(serverId: string): Promise<{ message: string }> {
  const { data } = await api.delete(`/mcp/servers/${encodeURIComponent(serverId)}`)
  return data
}

// ==================== 工单 Ticket ====================

export interface TicketPendingAction {
  awaiting?: boolean
  type?: string
  tool?: string
  title?: string
  args?: Record<string, unknown>
  reason?: string
  order_id?: string
  amount?: number
  thread_id?: string
  interrupt_id?: string
  requested_at?: string
  allowed_decisions?: string[]
  decision?: string
  decided_by?: string
  decided_at?: string
  result?: Record<string, unknown>
}

export interface TicketItem {
  id: number
  ticket_no: string
  session_id?: string | null
  intent?: string | null
  category?: string | null
  priority: number
  status: string
  source?: string | null
  summary?: string | null
  extracted_fields?: Record<string, unknown> | null
  transfer_reason?: string | null
  assigned_to?: string | null
  sla_due_at?: string | null
  resolved_at?: string | null
  resolution?: string | null
  pending_action?: TicketPendingAction | null
  sla_breached?: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface TicketEventItem {
  id: number
  ticket_id: number
  event_type: string
  content?: string | null
  operator?: string | null
  created_at?: string | null
}

export interface TicketDetail extends TicketItem {
  events: TicketEventItem[]
}

export interface TicketListResponse {
  items: TicketItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface TicketStats {
  by_status: Record<string, number>
  by_category: Record<string, number>
  total: number
  sla_breached: number
  open_total: number
  resolved_total: number
}

export async function listTickets(params?: {
  status?: string
  category?: string
  keyword?: string
  /** 只看某个会话产生的工单（会话列表 → 工单 跳转） */
  session_id?: string
  page?: number
  page_size?: number
}): Promise<TicketListResponse> {
  const { data } = await api.get('/ticket/list', { params: params ?? {} })
  return data
}

export async function getTicket(ticketId: number): Promise<TicketDetail> {
  const { data } = await api.get(`/ticket/${ticketId}`)
  return data
}

export async function ticketStats(): Promise<TicketStats> {
  const { data } = await api.get('/ticket/stats/summary')
  return data
}

export async function createTicket(payload: {
  session_id?: string | null
  intent?: string | null
  category?: string | null
  summary: string
  priority?: number | null
  assigned_to?: string | null
  source?: string
}): Promise<TicketItem> {
  const { data } = await api.post('/ticket', payload)
  return data
}

export async function updateTicketStatus(
  ticketId: number,
  status: string,
  opts?: { resolution?: string; operator?: string },
): Promise<{ message: string; ticket: TicketItem }> {
  const { data } = await api.put(`/ticket/${ticketId}/status`, null, {
    params: { status, resolution: opts?.resolution, operator: opts?.operator },
  })
  return data
}

export async function assignTicket(
  ticketId: number,
  assignedTo: string,
  operator = '人工坐席',
): Promise<{ message: string; ticket: TicketItem }> {
  const { data } = await api.put(`/ticket/${ticketId}/assign`, null, {
    params: { assigned_to: assignedTo, operator },
  })
  return data
}

export async function addTicketEvent(
  ticketId: number,
  content: string,
  eventType = 'comment',
  operator = '人工坐席',
): Promise<TicketEventItem> {
  const { data } = await api.post(`/ticket/${ticketId}/events`, {
    content,
    event_type: eventType,
    operator,
  })
  return data
}

/**
 * 坐席确认 Agent 挂起的动作（如退款受理）→ 后端用 Command(resume) 续跑
 */
export async function decideTicketAction(
  ticketId: number,
  decision: 'approve' | 'reject',
  operator = '人工坐席',
  message?: string,
): Promise<{
  status: string
  decision?: string
  rma_no?: string | null
  answer?: string
  message?: string
  ticket?: TicketDetail
}> {
  const { data } = await api.post(`/ticket/${ticketId}/decision`, { decision, operator, message })
  return data
}

export default api

// ==================== 训练数据管理 API ====================

// SFT 训练样本
export interface SftSample {
  id: string
  instruction: string
  output: string
  category: string
  quality_score: number
  created_at: string
}

export interface SftSamplesResponse {
  total: number
  samples: SftSample[]
}

// DPO 偏好对
export interface DpoPair {
  id: string
  prompt: string
  business_category: string
  candidate_count: number
  annotation_status: string
  annotated_by: string
  quality_score: number
  created_at: string
}

export interface DpoPairsResponse {
  total: number
  pairs: DpoPair[]
}

export interface DpoRejectedDetail {
  index: number
  reply: string
  error_type: string
  preference_type: string
}

export interface DpoPairDetail {
  id: string
  prompt: string
  business_category: string
  scenario_description: string
  chosen_reply: string
  rejected_replies: string[]
  rejected_details?: DpoRejectedDetail[]
  preference_type: string
  annotation_status: string
  annotated_by: string
  annotated_at: string
  annotation_notes: string
  quality_score: number
  difficulty_level: string
  created_at: string
}

// 训练任务
export interface TrainingJob {
  id: number
  job_type: string
  job_name: string
  base_model: string
  status: string
  progress: number
  created_at: string
}

export interface TrainingStatistics {
  sft_samples: {
    total: number
    approved: number
  }
  dpo_pairs: {
    total: number
    pending: number
    annotated: number
    by_category: Record<string, number>
  }
  training_jobs: {
    total: number
    completed: number
  }
}

// API 函数
export async function getSftSamples(params?: {
  category?: string
  is_approved?: boolean
  limit?: number
  offset?: number
}): Promise<SftSamplesResponse> {
  const { data } = await api.get('/training/sft/samples', { params })
  return data
}

export async function extractSftSamples(params?: {
  session_id?: string
  min_quality?: string
  max_samples?: number
}): Promise<{ extracted: number; saved: number; message: string }> {
  const { data } = await api.post('/training/sft/extract', null, { params })
  return data
}

export async function exportSftData(params?: {
  format?: string
  categories?: string[]
}): Promise<{ format: string; count: number; data: any[] }> {
  const { data } = await api.post('/training/sft/export', params)
  return data
}

export async function getDpoPairs(params?: {
  category?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<DpoPairsResponse> {
  const { data } = await api.get('/training/dpo/pairs', { params })
  return data
}

export async function getDpoPairDetail(pairId: string): Promise<DpoPairDetail> {
  const { data } = await api.get(`/training/dpo/pairs/${pairId}`)
  return data
}

export async function generateDpoPairs(params?: {
  min_quality?: string
  max_pairs?: number
  rejected_per_pair?: number
}): Promise<{ generated: number; saved: number; message: string }> {
  const { data } = await api.post('/training/dpo/generate', params)
  return data
}

export async function annotateDpoPair(
  pairId: string,
  data: { chosen_index: number; annotated_by: string; notes?: string }
): Promise<{ message: string }> {
  const { data: response } = await api.post(`/training/dpo/pairs/${pairId}/annotate`, data)
  return response
}

export async function exportDpoData(params?: {
  format?: string
}): Promise<{ format: string; count: number; data: any[] }> {
  const { data } = await api.post('/training/dpo/export', params)
  return data
}

export async function getDpoStatistics(): Promise<{
  total: number
  pending: number
  annotated: number
  by_category: Record<string, number>
}> {
  const { data } = await api.get('/training/dpo/statistics')
  return data
}

export async function createTrainingJob(data: {
  job_type: string
  job_name: string
  base_model?: string
  dataset_id?: string
  config?: any
}): Promise<TrainingJob> {
  const { data: response } = await api.post('/training/jobs', data)
  return response
}

export async function listTrainingJobs(params?: {
  job_type?: string
  status?: string
  limit?: number
}): Promise<{ total: number; jobs: TrainingJob[] }> {
  const { data } = await api.get('/training/jobs', { params })
  return data
}

export async function getTrainingJob(jobId: string | number): Promise<any> {
  const { data } = await api.get(`/training/jobs/${jobId}`)
  return data
}

export async function updateTrainingJobStatus(
  jobId: string | number,
  status: string,
  progress?: number
): Promise<{ message: string; status: string }> {
  const { data } = await api.put(`/training/jobs/${jobId}/status?status=${status}&progress=${progress ?? ''}`)
  return data
}

export async function completeTrainingJob(
  jobId: string | number,
  metrics: any,
  modelPath?: string
): Promise<{ message: string; metrics: any; model_path: string }> {
  const { data } = await api.put(`/training/jobs/${jobId}/complete`, { metrics, model_path: modelPath })
  return data
}

export async function getTrainingStatistics(): Promise<TrainingStatistics> {
  const { data } = await api.get('/training/statistics')
  return data
}
