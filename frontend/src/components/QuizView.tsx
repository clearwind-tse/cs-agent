import { useState, useEffect, useCallback } from 'react'
import {
  ClipboardList, Plus, Play, Send, Bot, UserCheck, ChevronLeft,
  Trash2, Loader2, CheckCircle2, XCircle, AlertCircle, Trophy,
  ArrowRight, MessageSquare,
} from 'lucide-react'
import {
  generateQuiz, getQuizList, getQuiz, deleteQuiz,
  startQuizAttempt, submitQuizAnswers, aiGradeAttempt,
  humanReviewAttempt, getQuizAttempt, getQuizAttempts,
  QuizData, QuizAttemptData,
  generateDialogueSet, getDialogueSets, getDialogueSet, deleteDialogueSet,
  getDialogueSessions, getDialogueSession,
  DialogueSetData, DialogueSessionData, DialogueScenario,
} from '../api'
import DialogueChat, { DialogueTranscript } from './DialogueChat'
import { cn } from '../utils'

interface QuizViewProps {
  onClose?: () => void
}

type Phase =
  | 'list' | 'generating' | 'answering' | 'submitting' | 'ai_grading' | 'review' | 'history'
  | 'dialogue_scenarios' | 'dialogue_chat' | 'dialogue_review'

const CATEGORY_OPTIONS = [
  { value: 'savings_explain', label: '省钱讲解' },
  { value: 'rebate_query', label: '返利查询' },
  { value: 'coupon_issue', label: '优惠券问题' },
  { value: 'order_problem', label: '订单问题' },
  { value: 'complaint', label: '投诉处理' },
  { value: 'merchant', label: '到店霸王餐' },
  { value: 'brand_promo', label: '品牌活动' },
  { value: 'points_box', label: '积分盲盒' },
  { value: 'onboarding', label: '新人引导' },
]

const DIFFICULTY_LABELS: Record<string, { text: string; color: string }> = {
  easy: { text: '简单', color: 'text-green-400 bg-green-500/10' },
  medium: { text: '中等', color: 'text-yellow-400 bg-yellow-500/10' },
  hard: { text: '困难', color: 'text-red-400 bg-red-500/10' },
}

// 问答(试卷/作答) 与 对话(情景集/会话) 在前端归并后统一渲染
type MergedSet = {
  kind: 'qa' | 'dialogue'
  id: number
  title: string
  category: string
  countLabel: string
  meta: string
  created_at: string | null
  quiz?: QuizData
  set?: DialogueSetData
}

type MergedRecord = {
  kind: 'qa' | 'dialogue'
  id: number
  title: string
  status: string
  score: number | null
  created_at: string | null
  attempt?: QuizAttemptData
  session?: DialogueSessionData
}

export default function QuizView(_props: QuizViewProps) {
  const [phase, setPhase] = useState<Phase>('list')
  const [quizzes, setQuizzes] = useState<QuizData[]>([])
  const [attempts, setAttempts] = useState<QuizAttemptData[]>([])
  const [currentQuiz, setCurrentQuiz] = useState<QuizData | null>(null)
  const [currentAttempt, setCurrentAttempt] = useState<QuizAttemptData | null>(null)
  const [attemptId, setAttemptId] = useState<number | null>(null)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [genCategory, setGenCategory] = useState('savings_explain')
  const [genCount, setGenCount] = useState(10)
  const [humanScore, setHumanScore] = useState<number>(0)
  const [humanFeedback, setHumanFeedback] = useState('')
  const [activeTab, setActiveTab] = useState<'quizzes' | 'history'>('quizzes')

  // 多轮对话实训
  const [mode, setMode] = useState<'qa' | 'dialogue'>('qa')
  const [dialogueSets, setDialogueSets] = useState<DialogueSetData[]>([])
  const [dialogueSessions, setDialogueSessions] = useState<DialogueSessionData[]>([])
  const [genDialogueCount, setGenDialogueCount] = useState(3)
  const [currentSet, setCurrentSet] = useState<DialogueSetData | null>(null)
  const [currentScenario, setCurrentScenario] = useState<DialogueScenario | null>(null)
  const [reviewSession, setReviewSession] = useState<DialogueSessionData | null>(null)

  const loadQuizzes = useCallback(async () => {
    try {
      const res = await getQuizList()
      setQuizzes(res.items)
    } catch { /* ignore */ }
  }, [])

  const loadAttempts = useCallback(async () => {
    try {
      const res = await getQuizAttempts()
      setAttempts(res.items)
    } catch { /* ignore */ }
  }, [])

  const loadDialogue = useCallback(async () => {
    try {
      const [sets, sessions] = await Promise.all([
        getDialogueSets(),
        getDialogueSessions(),
      ])
      setDialogueSets(sets.items)
      setDialogueSessions(sessions.items)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    loadQuizzes()
    loadAttempts()
    loadDialogue()
  }, [loadQuizzes, loadAttempts, loadDialogue])

  const handleGenerate = async () => {
    setPhase('generating')
    setError('')
    setLoading(true)
    try {
      const res = await generateQuiz({ category: genCategory, count: genCount })
      const quiz = await getQuiz(res.id)
      setCurrentQuiz(quiz)
      await loadQuizzes()
      setPhase('list')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '出题失败')
      setPhase('list')
    } finally {
      setLoading(false)
    }
  }

  const handleStartQuiz = async (quiz: QuizData) => {
    setLoading(true)
    setError('')
    try {
      const fullQuiz = await getQuiz(quiz.id)
      setCurrentQuiz(fullQuiz)
      const res = await startQuizAttempt(quiz.id)
      setAttemptId(res.attempt_id)
      setAnswers({})
      setPhase('answering')
    } catch (e: any) {
      setError(e?.response?.data?.detail || '开始考核失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitAnswers = async () => {
    if (!attemptId || !currentQuiz) return
    const unanswered = currentQuiz.questions.filter(q => !answers[q.id]?.trim())
    if (unanswered.length > 0) {
      setError(`还有 ${unanswered.length} 题未作答`)
      return
    }

    setPhase('submitting')
    setError('')
    setLoading(true)
    try {
      const answerList = currentQuiz.questions.map(q => ({
        question_id: q.id,
        answer: answers[q.id] || '',
      }))
      await submitQuizAnswers(attemptId, answerList)

      setPhase('ai_grading')
      const gradeRes = await aiGradeAttempt(attemptId)
      const attemptData = await getQuizAttempt(attemptId)
      setCurrentAttempt(attemptData)
      setHumanScore(gradeRes.ai_total_score)
      setHumanFeedback('')
      setPhase('review')
    } catch (e: any) {
      setError(e?.response?.data?.detail || '提交失败')
      setPhase('answering')
    } finally {
      setLoading(false)
    }
  }

  const handleHumanReview = async () => {
    if (!currentAttempt) return
    setLoading(true)
    try {
      await humanReviewAttempt(currentAttempt.id, {
        human_score: humanScore,
        human_feedback: humanFeedback,
      })
      const updated = await getQuizAttempt(currentAttempt.id)
      setCurrentAttempt(updated)
      await loadAttempts()
    } catch (e: any) {
      setError(e?.response?.data?.detail || '评测提交失败')
    } finally {
      setLoading(false)
    }
  }

  const handleViewAttempt = async (attempt: QuizAttemptData) => {
    setLoading(true)
    try {
      const full = await getQuizAttempt(attempt.id)
      setCurrentAttempt(full)
      if (full.quiz_id) {
        const quiz = await getQuiz(full.quiz_id)
        setCurrentQuiz(quiz)
      }
      setHumanScore(full.human_score ?? full.ai_total_score ?? 0)
      setHumanFeedback(full.human_feedback ?? '')
      setPhase('review')
    } catch (e: any) {
      setError('加载记录失败')
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteQuiz = async (quizId: number) => {
    if (!confirm('确认删除该试卷及其所有作答记录？')) return
    try {
      await deleteQuiz(quizId)
      await loadQuizzes()
      await loadAttempts()
    } catch { /* ignore */ }
  }

  // ========== 多轮对话实训 ==========

  const handleGenerateDialogue = async () => {
    setPhase('generating')
    setError('')
    setLoading(true)
    try {
      await generateDialogueSet({ category: genCategory, count: genDialogueCount })
      await loadDialogue()
      setActiveTab('quizzes')
      setPhase('list')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || '情景生成失败')
      setPhase('list')
    } finally {
      setLoading(false)
    }
  }

  const handleOpenSet = async (set: DialogueSetData) => {
    setLoading(true)
    setError('')
    try {
      setCurrentSet(await getDialogueSet(set.id))
      setPhase('dialogue_scenarios')
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载情景失败')
    } finally {
      setLoading(false)
    }
  }

  const handleStartScenario = (scenario: DialogueScenario) => {
    setCurrentScenario(scenario)
    setPhase('dialogue_chat')
  }

  const handleExitChat = async () => {
    setCurrentScenario(null)
    await loadDialogue()
    if (currentSet) {
      try {
        setCurrentSet(await getDialogueSet(currentSet.id))
      } catch { /* ignore */ }
    }
    setPhase('dialogue_scenarios')
  }

  const handleViewDialogueSession = async (session: DialogueSessionData) => {
    setLoading(true)
    setError('')
    try {
      setReviewSession(await getDialogueSession(session.id))
      setPhase('dialogue_review')
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载记录失败')
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteDialogueSet = async (setId: number) => {
    if (!confirm('确认删除该情景集及其所有对话记录？')) return
    try {
      await deleteDialogueSet(setId)
      await loadDialogue()
    } catch { /* ignore */ }
  }

  const handleBack = () => {
    setPhase('list')
    setCurrentQuiz(null)
    setCurrentAttempt(null)
    setAttemptId(null)
    setAnswers({})
    setCurrentSet(null)
    setCurrentScenario(null)
    setReviewSession(null)
    setError('')
  }

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-400'
    if (score >= 50) return 'text-yellow-400'
    return 'text-red-400'
  }

  // ========== 出题中 / AI评判中 加载态 ==========
  if (phase === 'generating' || phase === 'ai_grading' || phase === 'submitting') {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-dark-900">
        <Loader2 size={48} className="animate-spin text-accent-primary mb-6" />
        <p className="text-lg text-gray-300">
          {phase === 'generating' ? 'AI 正在出题...' : phase === 'submitting' ? '正在提交答案...' : 'AI 正在评判答案...'}
        </p>
        <p className="text-sm text-gray-500 mt-2">请稍候，通常需要 10-30 秒</p>
      </div>
    )
  }

  // ========== 对话实训 · 与客户对话 ==========
  if (phase === 'dialogue_chat' && currentSet && currentScenario) {
    return (
      <DialogueChat
        setId={currentSet.id}
        scenario={currentScenario}
        onExit={handleExitChat}
      />
    )
  }

  // ========== 对话实训 · 情景列表 ==========
  if (phase === 'dialogue_scenarios' && currentSet) {
    const scenarios = currentSet.scenarios || []
    const finishedCount = scenarios.filter(s => s.session?.status === 'finished').length
    return (
      <div className="flex-1 flex flex-col bg-dark-900 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-dark-600">
          <div className="flex items-center gap-3">
            <button onClick={handleBack} className="p-2 rounded-lg hover:bg-dark-700 text-gray-400">
              <ChevronLeft size={20} />
            </button>
            <div>
              <h2 className="text-lg font-bold text-white">{currentSet.title}</h2>
              <p className="text-sm text-gray-500">
                已完成 {finishedCount}/{scenarios.length} 个情景
              </p>
            </div>
          </div>
        </div>

        {error && (
          <div className="mx-6 mt-4 px-4 py-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
            <AlertCircle size={16} /> {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {scenarios.map((sc, idx) => {
            const diff = DIFFICULTY_LABELS[sc.difficulty] || DIFFICULTY_LABELS.medium
            const done = sc.session?.status === 'finished'
            const inProgress = sc.session?.status === 'in_progress'
            return (
              <div key={sc.id} className="bg-dark-800 rounded-xl border border-dark-600 p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <span className="flex-shrink-0 w-8 h-8 rounded-lg bg-accent-primary/20 text-accent-primary flex items-center justify-center text-sm font-bold">
                      {idx + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={cn('text-xs px-2 py-0.5 rounded-full', diff.color)}>{diff.text}</span>
                        {done && <span className="text-xs px-2 py-0.5 rounded-full text-green-400 bg-green-500/10">已完成</span>}
                        {inProgress && <span className="text-xs px-2 py-0.5 rounded-full text-blue-400 bg-blue-500/10">进行中</span>}
                        {sc.source && (
                          <span className="text-xs px-2 py-0.5 rounded-full text-gray-400 bg-dark-700">
                            真实案例 #{sc.source.conversation_id}
                          </span>
                        )}
                      </div>
                      <p className="text-gray-200 text-sm">{sc.customer_persona}</p>
                      <p className="text-gray-500 text-sm mt-1 truncate">客户开场：{sc.opening_line}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => handleStartScenario(sc)}
                    className="flex-shrink-0 px-3 py-1.5 bg-accent-primary/20 text-accent-primary rounded-lg hover:bg-accent-primary/30 text-sm flex items-center gap-1"
                  >
                    <Play size={14} /> {done || inProgress ? '重新练习' : '开始实训'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // ========== 对话实训 · 记录回看 ==========
  if (phase === 'dialogue_review' && reviewSession) {
    return (
      <div className="flex-1 flex flex-col bg-dark-900 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-dark-600">
          <div className="flex items-center gap-3">
            <button onClick={handleBack} className="p-2 rounded-lg hover:bg-dark-700 text-gray-400">
              <ChevronLeft size={20} />
            </button>
            <div>
              <h2 className="text-lg font-bold text-white">{reviewSession.set_title || '对话记录'}</h2>
              <p className="text-sm text-gray-500">
                {reviewSession.scenario?.customer_persona || '客户情景'} · 共 {reviewSession.turn_count} 轮 ·
                {reviewSession.status === 'finished' ? ' 已完成' : ' 进行中'}
                {reviewSession.source && ` · 源自真实对话 #${reviewSession.source.conversation_id}`}
              </p>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <DialogueTranscript turns={reviewSession.transcript} />

          {/* 参考答案与原始真实对话：仅会话结束后后端才下发，练习中不存在 */}
          {reviewSession.status === 'finished' && (reviewSession.reference_replies?.length ?? 0) > 0 && (
            <div className="border-t border-dark-600 pt-6">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">参考答案 · 真实客服回复</h3>
              <ol className="space-y-2">
                {reviewSession.reference_replies!.map((r, i) => (
                  <li key={i} className="flex gap-3 text-sm">
                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-accent-primary/20 text-accent-primary flex items-center justify-center text-xs font-bold">
                      {i + 1}
                    </span>
                    <p className="text-gray-300 whitespace-pre-wrap break-words">{r}</p>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {(reviewSession.source_transcript?.length ?? 0) > 0 && (
            <details className="border-t border-dark-600 pt-6">
              <summary className="cursor-pointer text-sm font-semibold text-gray-300">
                原始真实对话（{reviewSession.source_transcript!.length} 条）
              </summary>
              <div className="mt-4">
                <DialogueTranscript turns={reviewSession.source_transcript!} />
              </div>
            </details>
          )}
        </div>
      </div>
    )
  }

  // ========== 答题页 ==========
  if (phase === 'answering' && currentQuiz) {
    const answeredCount = Object.values(answers).filter(a => a.trim()).length
    const progress = Math.round((answeredCount / currentQuiz.questions.length) * 100)
    return (
      <div className="flex-1 flex flex-col bg-dark-900 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-dark-600">
          <div className="flex items-center gap-3">
            <button onClick={handleBack} className="p-2 rounded-lg hover:bg-dark-700 text-gray-400">
              <ChevronLeft size={20} />
            </button>
            <div>
              <h2 className="text-lg font-bold text-white">{currentQuiz.title}</h2>
              <p className="text-sm text-gray-500">
                已完成 {answeredCount}/{currentQuiz.questions.length} 题
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="w-32 h-2 bg-dark-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-accent-primary to-accent-secondary rounded-full transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <button
              onClick={handleSubmitAnswers}
              disabled={loading}
              className="px-4 py-2 bg-accent-primary text-white rounded-lg hover:bg-accent-primary/80 disabled:opacity-50 flex items-center gap-2 text-sm font-medium"
            >
              <Send size={16} /> 提交答案
            </button>
          </div>
        </div>

        {error && (
          <div className="mx-6 mt-4 px-4 py-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {/* Questions */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {currentQuiz.questions.map((q, idx) => {
            const diff = DIFFICULTY_LABELS[q.difficulty] || DIFFICULTY_LABELS.medium
            return (
              <div key={q.id} className="bg-dark-800 rounded-xl border border-dark-600 p-5">
                <div className="flex items-start gap-3 mb-4">
                  <span className="flex-shrink-0 w-8 h-8 rounded-lg bg-accent-primary/20 text-accent-primary flex items-center justify-center text-sm font-bold">
                    {idx + 1}
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={cn('text-xs px-2 py-0.5 rounded-full', diff.color)}>
                        {diff.text}
                      </span>
                    </div>
                    <p className="text-gray-200 leading-relaxed">{q.question}</p>
                  </div>
                </div>
                <textarea
                  value={answers[q.id] || ''}
                  onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                  placeholder="请输入你的回复话术..."
                  rows={3}
                  className="w-full bg-dark-700 border border-dark-500 rounded-lg px-4 py-3 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-accent-primary/50 resize-none text-sm"
                />
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // ========== 评测结果页 ==========
  if (phase === 'review' && currentAttempt) {
    const questions = currentAttempt.questions || currentQuiz?.questions || []
    const answerMap = new Map(
      (currentAttempt.user_answers || []).map(a => [a.question_id, a.answer])
    )
    const evalMap = new Map(
      (currentAttempt.ai_evaluation || []).map(e => [e.question_id, e])
    )
    const isHumanReviewed = currentAttempt.status === 'human_reviewed'

    return (
      <div className="flex-1 flex flex-col bg-dark-900 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-dark-600">
          <div className="flex items-center gap-3">
            <button onClick={handleBack} className="p-2 rounded-lg hover:bg-dark-700 text-gray-400">
              <ChevronLeft size={20} />
            </button>
            <div>
              <h2 className="text-lg font-bold text-white">
                {currentAttempt.quiz_title || '考核结果'}
              </h2>
              <p className="text-sm text-gray-500">
                {isHumanReviewed ? '已完成人工评测' : 'AI 已评判 · 等待人工评测'}
              </p>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Score Summary */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-dark-800 rounded-xl border border-dark-600 p-6 text-center">
              <Bot size={24} className="mx-auto mb-2 text-accent-primary" />
              <p className="text-sm text-gray-500 mb-1">AI 评分</p>
              <p className={cn('text-4xl font-bold', getScoreColor(currentAttempt.ai_total_score ?? 0))}>
                {currentAttempt.ai_total_score ?? '-'}
              </p>
              <p className="text-xs text-gray-600 mt-1">满分 100</p>
            </div>
            <div className="bg-dark-800 rounded-xl border border-dark-600 p-6 text-center">
              <UserCheck size={24} className="mx-auto mb-2 text-yellow-400" />
              <p className="text-sm text-gray-500 mb-1">人工评分</p>
              {isHumanReviewed ? (
                <>
                  <p className={cn('text-4xl font-bold', getScoreColor(currentAttempt.human_score ?? 0))}>
                    {currentAttempt.human_score}
                  </p>
                  <p className="text-xs text-gray-600 mt-1">满分 100</p>
                </>
              ) : (
                <p className="text-2xl text-gray-600 mt-2">待评测</p>
              )}
            </div>
          </div>

          {/* Each question result */}
          {questions.map((q, idx) => {
            const userAns = answerMap.get(q.id) || '(未作答)'
            const ev = evalMap.get(q.id)
            const diff = DIFFICULTY_LABELS[q.difficulty] || DIFFICULTY_LABELS.medium
            return (
              <div key={q.id} className="bg-dark-800 rounded-xl border border-dark-600 p-5">
                <div className="flex items-start gap-3 mb-3">
                  <span className="flex-shrink-0 w-8 h-8 rounded-lg bg-accent-primary/20 text-accent-primary flex items-center justify-center text-sm font-bold">
                    {idx + 1}
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={cn('text-xs px-2 py-0.5 rounded-full', diff.color)}>
                        {diff.text}
                      </span>
                      {ev && (
                        <span className={cn(
                          'text-xs px-2 py-0.5 rounded-full',
                          ev.score >= 8 ? 'text-green-400 bg-green-500/10' :
                          ev.score >= 5 ? 'text-yellow-400 bg-yellow-500/10' :
                          'text-red-400 bg-red-500/10'
                        )}>
                          {ev.score}/10 分
                        </span>
                      )}
                    </div>
                    <p className="text-gray-200 leading-relaxed">{q.question}</p>
                  </div>
                </div>

                <div className="ml-11 space-y-3">
                  <div className="bg-dark-700/50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">你的回答</p>
                    <p className="text-gray-300 text-sm whitespace-pre-wrap">{userAns}</p>
                  </div>
                  <div className="bg-accent-primary/5 rounded-lg p-3 border border-accent-primary/10">
                    <p className="text-xs text-accent-primary/70 mb-1">参考答案</p>
                    <p className="text-gray-400 text-sm whitespace-pre-wrap">{q.reference_answer}</p>
                  </div>
                  {ev?.feedback && (
                    <div className={cn(
                      'rounded-lg p-3 border',
                      ev.is_reasonable
                        ? 'bg-green-500/5 border-green-500/10'
                        : 'bg-red-500/5 border-red-500/10'
                    )}>
                      <div className="flex items-center gap-1 mb-1">
                        {ev.is_reasonable
                          ? <CheckCircle2 size={14} className="text-green-400" />
                          : <XCircle size={14} className="text-red-400" />
                        }
                        <p className="text-xs text-gray-500">AI 点评</p>
                      </div>
                      <p className="text-gray-300 text-sm">{ev.feedback}</p>
                    </div>
                  )}
                </div>
              </div>
            )
          })}

          {/* Human Review Form */}
          {!isHumanReviewed && (
            <div className="bg-dark-800 rounded-xl border border-dark-600 p-6">
              <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                <UserCheck size={18} className="text-yellow-400" />
                人工评测
              </h3>
              <div className="space-y-4">
                <div>
                  <label className="text-sm text-gray-400 mb-2 block">总分 (0-100)</label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={humanScore}
                    onChange={e => setHumanScore(Number(e.target.value))}
                    className="w-32 bg-dark-700 border border-dark-500 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-accent-primary/50"
                  />
                </div>
                <div>
                  <label className="text-sm text-gray-400 mb-2 block">评语</label>
                  <textarea
                    value={humanFeedback}
                    onChange={e => setHumanFeedback(e.target.value)}
                    placeholder="输入评测意见..."
                    rows={3}
                    className="w-full bg-dark-700 border border-dark-500 rounded-lg px-4 py-3 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-accent-primary/50 resize-none text-sm"
                  />
                </div>
                <button
                  onClick={handleHumanReview}
                  disabled={loading}
                  className="px-4 py-2 bg-yellow-500 text-dark-900 rounded-lg hover:bg-yellow-400 disabled:opacity-50 flex items-center gap-2 text-sm font-medium"
                >
                  <Trophy size={16} /> 提交评测结果
                </button>
              </div>
              {error && (
                <p className="text-red-400 text-sm mt-3">{error}</p>
              )}
            </div>
          )}

          {isHumanReviewed && currentAttempt.human_feedback && (
            <div className="bg-dark-800 rounded-xl border border-yellow-500/20 p-6">
              <h3 className="text-white font-semibold mb-2 flex items-center gap-2">
                <Trophy size={18} className="text-yellow-400" />
                人工评语
              </h3>
              <p className="text-gray-300 text-sm whitespace-pre-wrap">{currentAttempt.human_feedback}</p>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ========== 列表主页 ==========
  // 试卷列表与作答记录：问答 + 对话两个来源在前端归并（后端各管各的表）
  const mergedSets: MergedSet[] = [
    ...quizzes.map(q => ({
      kind: 'qa' as const,
      id: q.id,
      title: q.title,
      category: q.category,
      countLabel: `${q.question_count} 题`,
      meta: `${q.attempt_count || 0} 次作答`,
      created_at: q.created_at,
      quiz: q,
    })),
    ...dialogueSets.map(s => ({
      kind: 'dialogue' as const,
      id: s.id,
      title: s.title,
      category: s.category,
      countLabel: `${s.scenario_count} 个情景`,
      meta: `已练 ${s.finished_count ?? 0}/${s.scenario_count}`,
      created_at: s.created_at,
      set: s,
    })),
  ].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))

  const mergedRecords: MergedRecord[] = [
    ...attempts.map(a => ({
      kind: 'qa' as const,
      id: a.id,
      title: a.quiz_title || '考核',
      status: a.status,
      score: a.ai_total_score,
      created_at: a.created_at,
      attempt: a,
    })),
    ...dialogueSessions.map(s => ({
      kind: 'dialogue' as const,
      id: s.id,
      title: s.set_title || '对话实训',
      status: s.status,
      score: null,
      created_at: s.created_at,
      session: s,
    })),
  ].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))

  return (
    <div className="flex-1 flex flex-col bg-dark-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-dark-600">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <ClipboardList size={24} className="text-accent-primary" />
          AI 考核
        </h1>
        <button
          onClick={mode === 'qa' ? handleGenerate : handleGenerateDialogue}
          disabled={loading}
          className="px-4 py-2 bg-accent-primary text-white rounded-lg hover:bg-accent-primary/80 disabled:opacity-50 flex items-center gap-2 text-sm font-medium"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {mode === 'qa' ? 'AI 出题' : 'AI 生成情景'}
        </button>
      </div>

      {/* 模式切换 */}
      <div className="px-6 py-3 border-b border-dark-700 flex items-center gap-2">
        <button
          onClick={() => { setMode('qa'); setActiveTab('quizzes'); setError('') }}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors',
            mode === 'qa'
              ? 'bg-accent-primary/20 text-accent-primary'
              : 'text-gray-400 hover:text-gray-200 hover:bg-dark-700'
          )}
        >
          <ClipboardList size={16} /> 问答模式
        </button>
        <button
          onClick={() => { setMode('dialogue'); setActiveTab('quizzes'); setError('') }}
          className={cn(
            'px-3 py-1.5 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors',
            mode === 'dialogue'
              ? 'bg-accent-primary/20 text-accent-primary'
              : 'text-gray-400 hover:text-gray-200 hover:bg-dark-700'
          )}
        >
          <MessageSquare size={16} /> 对话模式
        </button>
      </div>

      {/* Generate Config */}
      <div className="px-6 py-3 border-b border-dark-700 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">分类:</span>
          <select
            value={genCategory}
            onChange={e => setGenCategory(e.target.value)}
            className="bg-dark-700 border border-dark-500 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none"
          >
            {CATEGORY_OPTIONS.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        {mode === 'qa' ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">题数:</span>
            <input
              type="number"
              min={1}
              max={20}
              value={genCount}
              onChange={e => setGenCount(Number(e.target.value))}
              className="w-16 bg-dark-700 border border-dark-500 rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none text-center"
            />
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">情景数:</span>
            <input
              type="number"
              min={1}
              max={10}
              value={genDialogueCount}
              onChange={e => setGenDialogueCount(Number(e.target.value))}
              className="w-16 bg-dark-700 border border-dark-500 rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none text-center"
            />
          </div>
        )}
      </div>

      {error && (
        <div className="mx-6 mt-4 px-4 py-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Tabs */}
      <div className="px-6 pt-4 flex gap-1">
        <button
          onClick={() => setActiveTab('quizzes')}
          className={cn(
            'px-4 py-2 rounded-t-lg text-sm font-medium transition-colors',
            activeTab === 'quizzes'
              ? 'bg-dark-800 text-white border-b-2 border-accent-primary'
              : 'text-gray-500 hover:text-gray-300'
          )}
        >
          试卷列表 ({quizzes.length})
        </button>
        <button
          onClick={() => { setActiveTab('history'); loadAttempts() }}
          className={cn(
            'px-4 py-2 rounded-t-lg text-sm font-medium transition-colors',
            activeTab === 'history'
              ? 'bg-dark-800 text-white border-b-2 border-accent-primary'
              : 'text-gray-500 hover:text-gray-300'
          )}
        >
          作答记录 ({attempts.length})
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 pt-2">
        {activeTab === 'quizzes' ? (
          mergedSets.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-500">
              <ClipboardList size={48} className="mb-4 opacity-30" />
              <p className="text-base mb-2">还没有考核试卷</p>
              <p className="text-sm">
                {mode === 'qa'
                  ? '点击右上角「AI 出题」生成第一份试卷'
                  : '点击右上角「AI 生成情景」创建第一组对话实训'}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {mergedSets.map(item => (
                <div
                  key={`${item.kind}-${item.id}`}
                  className="bg-dark-800 rounded-xl border border-dark-600 p-4 flex items-center justify-between hover:border-dark-500 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-white font-medium truncate">{item.title}</h3>
                      <span className={cn(
                        'text-xs px-2 py-0.5 rounded-full',
                        item.kind === 'dialogue'
                          ? 'bg-accent-secondary/10 text-accent-secondary'
                          : 'bg-accent-primary/10 text-accent-primary'
                      )}>
                        {item.kind === 'dialogue' ? '对话' : '问答'}
                      </span>
                      <span className="text-xs text-gray-500">
                        {CATEGORY_OPTIONS.find(c => c.value === item.category)?.label || item.category}
                      </span>
                    </div>
                    <p className="text-sm text-gray-500">
                      {item.countLabel} · {item.meta} · {item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN') : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    <button
                      onClick={() => item.kind === 'dialogue'
                        ? (item.set && handleOpenSet(item.set))
                        : (item.quiz && handleStartQuiz(item.quiz))}
                      className="px-3 py-1.5 bg-accent-primary/20 text-accent-primary rounded-lg hover:bg-accent-primary/30 text-sm flex items-center gap-1"
                    >
                      <Play size={14} /> {item.kind === 'dialogue' ? '开始实训' : '开始考核'}
                    </button>
                    <button
                      onClick={() => item.kind === 'dialogue'
                        ? handleDeleteDialogueSet(item.id)
                        : handleDeleteQuiz(item.id)}
                      className="p-1.5 rounded-lg hover:bg-dark-600 text-gray-500 hover:text-red-400"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          mergedRecords.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-500">
              <Trophy size={48} className="mb-4 opacity-30" />
              <p className="text-base">暂无作答记录</p>
            </div>
          ) : (
            <div className="space-y-3">
              {mergedRecords.map(item => {
                const statusLabels: Record<string, { text: string; color: string }> = {
                  answering: { text: '作答中', color: 'text-blue-400 bg-blue-500/10' },
                  submitted: { text: '已提交', color: 'text-yellow-400 bg-yellow-500/10' },
                  ai_graded: { text: 'AI已评判', color: 'text-purple-400 bg-purple-500/10' },
                  human_reviewed: { text: '已评测', color: 'text-green-400 bg-green-500/10' },
                  in_progress: { text: '进行中', color: 'text-blue-400 bg-blue-500/10' },
                  finished: { text: '已完成', color: 'text-green-400 bg-green-500/10' },
                }
                const st = statusLabels[item.status] || statusLabels.answering
                return (
                  <div
                    key={`${item.kind}-${item.id}`}
                    onClick={() => item.kind === 'dialogue'
                      ? (item.session && handleViewDialogueSession(item.session))
                      : (item.attempt && handleViewAttempt(item.attempt))}
                    className="bg-dark-800 rounded-xl border border-dark-600 p-4 flex items-center justify-between hover:border-dark-500 transition-colors cursor-pointer"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="text-white font-medium truncate">{item.title}</h3>
                        <span className={cn(
                          'text-xs px-2 py-0.5 rounded-full',
                          item.kind === 'dialogue'
                            ? 'bg-accent-secondary/10 text-accent-secondary'
                            : 'bg-accent-primary/10 text-accent-primary'
                        )}>
                          {item.kind === 'dialogue' ? '对话' : '问答'}
                        </span>
                        <span className={cn('text-xs px-2 py-0.5 rounded-full', st.color)}>
                          {st.text}
                        </span>
                      </div>
                      <p className="text-sm text-gray-500">
                        {item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN') : ''}
                        {item.kind === 'qa' && item.score != null && ` · AI评分: ${item.score}`}
                        {item.kind === 'dialogue' && item.session && ` · ${item.session.turn_count} 轮`}
                      </p>
                    </div>
                    <ArrowRight size={18} className="text-gray-500 ml-3" />
                  </div>
                )
              })}
            </div>
          )
        )}
      </div>
    </div>
  )
}
