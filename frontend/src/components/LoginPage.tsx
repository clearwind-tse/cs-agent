import React, { useState } from 'react'
import { ArrowRight, Eye, EyeOff, Lock, Mail, Sparkles, User, X } from 'lucide-react'
import api from '../api'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'
import { AuroraBackground } from './ui/AuroraBackground'
import { Button } from './ui/Button'
import { ThemeToggle } from './ui/ThemeToggle'

interface LoginPageProps {
  onClose: () => void
  onSuccess: () => void
  canClose?: boolean
}

const inputClass =
  'block w-full rounded-xl border border-line/70 bg-canvas/50 py-3.5 pl-11 pr-11 text-sm text-ink ' +
  'placeholder:text-ink-subtle outline-none transition-all duration-200 ' +
  'focus:border-iris/70 focus:ring-2 focus:ring-halo/25'

export default function LoginPage({ onClose, onSuccess, canClose = true }: LoginPageProps) {
  const [isLogin, setIsLogin] = useState(true)
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  // 表单状态
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  const { login: saveLoginState } = useAuth()
  const { showToast } = useToast()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMsg('')
    setLoading(true)

    try {
      if (isLogin) {
        // 登录请求
        const res = await api.post('/auth/login', { username, password })
        const { access_token, refresh_token, user } = res.data
        saveLoginState(access_token, refresh_token, user)
        showToast('登录成功', 'success')
        onSuccess()
      } else {
        // 注册请求
        await api.post('/auth/register', { username, password, nickname: nickname || undefined })
        showToast('注册成功，请登录', 'success')
        setIsLogin(true) // 注册完成后切换到登录页
      }
    } catch (error: any) {
      setErrorMsg(error.response?.data?.detail?.message || '操作失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] min-h-[100dvh] overflow-y-auto bg-canvas text-ink">
      <AuroraBackground variant="login" className="fixed inset-0" />

      <div className="relative z-10 flex min-h-[100dvh] flex-col">
        {/* 顶栏 */}
        <header className="flex items-center justify-between gap-4 px-6 py-6 md:px-12">
          <div className="flex items-center gap-3">
            <div
              className="relative h-9 w-9 rounded-xl"
              style={{ background: 'conic-gradient(from 210deg, rgb(var(--c-mint)), rgb(var(--c-iris)), rgb(var(--c-flare)), rgb(var(--c-mint)))' }}
            >
              <div className="absolute inset-[3px] rounded-[9px] bg-canvas/85 backdrop-blur-md" />
              <Sparkles size={15} className="absolute inset-0 m-auto text-ink" strokeWidth={1.6} />
            </div>
            <div>
              <div className="font-display text-sm font-bold tracking-tight text-ink">Agent CS Playbook</div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-subtle">Data quality & agent workspace</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <ThemeToggle compact className="hidden sm:inline-flex" />
            {canClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="关闭登录"
                className="flex h-9 w-9 items-center justify-center rounded-full border border-line/70 bg-panel-2/60 text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
              >
                <X size={17} />
              </button>
            )}
          </div>
        </header>

        <main className="flex flex-1 items-center justify-center px-5 pb-16 pt-6">
          <div className="grid w-full max-w-5xl items-center gap-12 lg:grid-cols-[1fr_440px]">
            {/* 左侧视觉 */}
            <section className="hidden lg:block">
              <div className="mb-7 inline-flex items-center gap-2 rounded-pill border border-iris/35 bg-iris/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-info">
                <Sparkles size={12} /> 智能架构
              </div>
              <h1 className="font-display text-[clamp(2.4rem,4vw,3.5rem)] font-extrabold leading-[1.08] tracking-[-0.04em] text-ink">
                用 AI 赋能销售。
                <br />
                <span className="aurora-text">把聊天记录变成资产。</span>
              </h1>
              <p className="mt-6 max-w-md text-[15px] leading-[1.9] text-ink-muted">
                为高效转化和深度数据洞察而生的客服工作空间：质检、标注、SFT/DPO 训练数据、智能客服 Agent，一条链路跑通。
              </p>

              <div className="mt-10 flex items-center gap-5">
                <div className="flex -space-x-2">
                  {[
                    'conic-gradient(from 30deg, rgb(var(--c-mint)), rgb(var(--c-iris)))',
                    'conic-gradient(from 120deg, rgb(var(--c-iris)), rgb(var(--c-flare)))',
                    'conic-gradient(from 240deg, rgb(var(--c-flare)), rgb(var(--c-mint)))',
                  ].map((background, index) => (
                    <div
                      key={index}
                      className="h-9 w-9 rounded-xl border-2 border-canvas"
                      style={{ background }}
                    />
                  ))}
                </div>
                <span className="text-xs text-ink-subtle">客服质检 · 数据闭环 · Agent 实战</span>
              </div>

              <div className="mt-12 grid max-w-md grid-cols-3 gap-3">
                {[
                  ['SFT', '语气模仿'],
                  ['DPO', '偏好对齐'],
                  ['QC', '质检校准'],
                ].map(([key, label]) => (
                  <div key={key} className="glass rounded-2xl px-4 py-3">
                    <div className="font-display text-lg font-bold text-ink">{key}</div>
                    <div className="mt-0.5 text-[11px] text-ink-subtle">{label}</div>
                  </div>
                ))}
              </div>
            </section>

            {/* 右侧表单 */}
            <section className="glass w-full rounded-card p-7 shadow-glow md:p-9">
              <div className="mb-7 text-center">
                <div
                  className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl"
                  style={{ background: 'linear-gradient(135deg, rgb(var(--c-iris)), rgb(var(--c-flare)))' }}
                >
                  <Sparkles size={24} className="text-ink" strokeWidth={1.7} />
                </div>
                <h2 className="font-display text-2xl font-bold tracking-tight text-ink">
                  {isLogin ? '欢迎回来' : '创建账号'}
                </h2>
                <p className="mt-1.5 text-sm text-ink-muted">
                  {isLogin ? '输入您的详细信息以访问工作空间' : '加入工作空间，开始数据洞察之旅'}
                </p>
              </div>

              <div className="mb-7 flex gap-1 rounded-pill border border-line/70 bg-panel-2/60 p-1">
                {[
                  { key: true, label: '登录' },
                  { key: false, label: '创建账号' },
                ].map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    onClick={() => { setIsLogin(item.key); setErrorMsg('') }}
                    className={`flex-1 rounded-pill py-2 text-sm font-medium transition-all duration-200 ${
                      isLogin === item.key ? 'bg-brand text-brand-fg shadow-glow' : 'text-ink-muted hover:text-ink'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              {errorMsg && (
                <div className="mb-5 rounded-xl border border-bad/40 bg-bad/10 px-3 py-2.5 text-center text-sm text-bad">
                  {errorMsg}
                </div>
              )}

              <form className="space-y-4" onSubmit={handleSubmit}>
                <label className="relative block">
                  <Mail size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
                  <input
                    id="username"
                    type="text"
                    required
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className={inputClass}
                    placeholder="用户名或邮箱"
                  />
                </label>

                <label className="relative block">
                  <Lock size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    autoComplete={isLogin ? 'current-password' : 'new-password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={inputClass}
                    placeholder="密码"
                  />
                  <button
                    type="button"
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-ink-subtle transition-colors hover:text-ink"
                  >
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </label>

                {!isLogin && (
                  <label className="relative block animate-fade-in">
                    <User size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
                    <input
                      id="nickname"
                      type="text"
                      value={nickname}
                      onChange={(e) => setNickname(e.target.value)}
                      className={inputClass}
                      placeholder="昵称（选填）"
                    />
                  </label>
                )}

                <div className="flex items-center justify-between px-1 text-xs text-ink-subtle">
                  {isLogin ? (
                    <>
                      <span>记住我</span>
                      <span className="text-info">忘记密码？</span>
                    </>
                  ) : (
                    <span className="w-full text-center">注册即代表您同意服务条款</span>
                  )}
                </div>

                <Button type="submit" variant="primary" size="lg" className="w-full" disabled={loading} icon={loading ? undefined : <ArrowRight size={17} />}>
                  {loading ? '处理中…' : isLogin ? '立即登录' : '创建账号'}
                </Button>
              </form>
            </section>
          </div>
        </main>

        <footer className="flex flex-wrap items-center justify-between gap-3 px-6 pb-6 md:px-12">
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-subtle">© 2026 clearwind · Apache-2.0</span>
          <ThemeToggle compact className="sm:hidden" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-subtle">Aurora design system</span>
        </footer>
      </div>
    </div>
  )
}
