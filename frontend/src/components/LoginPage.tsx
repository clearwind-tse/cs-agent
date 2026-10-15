import React, { useState } from 'react'
import api from '../api'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'

interface LoginPageProps {
  onClose: () => void
  onSuccess: () => void
  canClose?: boolean
}

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
    <div className="fixed inset-0 z-[100] bg-mesh min-h-screen text-on-surface overflow-y-auto selection:bg-primary selection:text-on-primary">
      <style>{`
        body { font-family: 'Inter', sans-serif; background-color: #060e20; }
        .glass-card {
            background: rgba(6, 18, 45, 0.4);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(189, 194, 255, 0.1);
        }
        .glow-button {
            box-shadow: 0 0 20px rgba(189, 194, 255, 0.2);
        }
        .glow-button:hover {
            box-shadow: 0 0 30px rgba(189, 194, 255, 0.4);
        }
        .text-gradient {
            background: linear-gradient(135deg, #dee5ff 0%, #bdc2ff 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .bg-mesh {
            background-color: #060e20;
            background-image: 
                radial-gradient(at 0% 0%, hsla(230, 100%, 15%, 1) 0, transparent 50%), 
                radial-gradient(at 100% 100%, hsla(260, 100%, 10%, 1) 0, transparent 50%);
        }
      `}</style>
      
      {canClose && (
        <button 
          onClick={onClose}
          className="absolute top-6 right-6 p-2 text-on-surface-variant hover:text-primary bg-surface-container-lowest hover:bg-surface-container-highest rounded-full transition-colors z-[110]"
        >
          <span className="material-symbols-outlined text-xl">close</span>
        </button>
      )}

      {/* Navigation Shell (TopAppBar) */}
      <header className="fixed top-0 w-full z-50 pointer-events-none">
        <nav className="flex justify-between items-center px-8 py-6 w-full max-w-none bg-transparent">
          <div className="flex items-center gap-2 group cursor-pointer pointer-events-auto">
            <span className="material-symbols-outlined text-primary text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>auto_awesome</span>
            <span className="text-2xl font-bold tracking-tight text-[#dee5ff] dark:text-[#dee5ff] font-headline">Agent CS Playbook</span>
          </div>
          <div className="hidden md:flex items-center gap-8 pointer-events-auto">
            <a className={`text-[#bdc2ff] font-semibold font-body text-sm transition-colors duration-300 cursor-pointer ${isLogin ? 'text-[#bdc2ff]' : 'text-[#91aaeb]'}`} onClick={() => setIsLogin(true)}>登录</a>
            <a className={`hover:text-[#bdc2ff] transition-colors duration-300 font-body text-sm cursor-pointer ${!isLogin ? 'text-[#bdc2ff]' : 'text-[#91aaeb]'}`} onClick={() => setIsLogin(false)}>注册</a>
          </div>
        </nav>
      </header>

      <main className="flex min-h-[100dvh]">
        {/* Left Side: Abstract 3D Graphic (Desktop Only) */}
        <section className="hidden lg:flex w-1/2 relative items-center justify-center p-12 overflow-hidden bg-surface-container-lowest">
          <div className="absolute inset-0 z-0 opacity-40">
            <img alt="AI Data Visualization" className="w-full h-full object-cover" src="https://lh3.googleusercontent.com/aida-public/AB6AXuC4rxBkq4lOfX8eQpJmRyjfjrEMca2qYaBIRnBwtOGW7C9LmKkze-WbdxyWycCBfij0ANmsRXbAkqiJkW0C8snW9wJcgn4adlvYkPkd1ZjkotBM-jIvEUvvlPeBFeSf6imURmITMB7TQkub36pjxOSNwMNN2POLYR4f8NpP0RSa71EGlbXMFvQZLnhLREpxi2cUzuuxUU8H_Q1d66IHZfJW-7Gy4hNDNhb4YZDC0Uc9dnhycDx26raS-dWde3S5-W7zuZbhf48qaw" />
            <div className="absolute inset-0 bg-gradient-to-r from-surface-container-lowest via-transparent to-surface-container-lowest"></div>
          </div>
          <div className="relative z-10 max-w-xl space-y-8">
            <div className="space-y-4">
              <span className="inline-block px-3 py-1 rounded-full bg-primary-container/30 border border-primary/20 text-primary text-[10px] font-bold tracking-widest uppercase">智能架构</span>
              <h1 className="text-5xl font-extrabold font-headline leading-tight tracking-tight text-gradient">用 AI 赋能销售。<br />将聊天记录转化为销售利器。</h1>
              <p className="text-on-surface-variant text-lg font-body max-w-md leading-relaxed">为高效转化和深度数据洞察而生的客服工作空间。</p>
            </div>
            <div className="flex items-center gap-6 pt-8">
              <div className="flex -space-x-3">
                <img alt="User" className="w-10 h-10 rounded-xl border-2 border-surface-container-lowest" src="https://lh3.googleusercontent.com/aida-public/AB6AXuCWF36iQnvTkYkzKe7qPOPoA6whPW6J_HbChj6Sfd3RH3WtTH04xRq-GeKF4asWn-z1qQgKzCpfgZ2FKBm2lAIIucnvEW6ONKlMoSmhNy80fBiTl1wQt0rr8jdldjPN_5hXDYTFBleszZn6hyD8X7BhCHBPJ4wpbOxiKBurA7jPQLlytvg8fQFf-tTDt4_ckllJdmgbG7Z0JNJFM8mOBa5-2ndtxjAGvWaNtJRgkaoXETXrA0rI0iz-3Yf4KyRfRD9xAbKCZBUG9Q" />
                <img alt="User" className="w-10 h-10 rounded-xl border-2 border-surface-container-lowest" src="https://lh3.googleusercontent.com/aida-public/AB6AXuDYyzVYlts4ACRwVPmYTT9U5ss0KsMGSITyelt1Is8u0Y1ENsf663tE58jQVhz4vKR4X1IAObb7ebb5fE9hDitte_ipN0o3VszLs702kADbK3BssYJZhy80b61fRwtUJMssirerq8ftK3l_qdwSD7cVa4nEZiK79CAV0id3qEwVxDNRec2zo4eYUuN1tKG3VjtlMfDX6lxgblkR8qMY709lXH-hufAvUHaj7AAcb6Ka79QqFBIEqsdDhLTgCZW7rddOolMmICMQ9w" />
                <img alt="User" className="w-10 h-10 rounded-xl border-2 border-surface-container-lowest" src="https://lh3.googleusercontent.com/aida-public/AB6AXuDmiVEN89Nbd_OBeW2wYYaiQrI9bKJ5D_pjIWoE6y-I7dLJlZnQgD_zDEN7axPR6RbnqEz9VPtJ8ardHrWWN6ujXAXvkgCj1DksEGtzIymw1ELFLuugnA2l9xx7rDQ1_9lbVEngSR8lBS9qvCetcAYVnR8v76k2Ro6UNScg1hDJfXg08SLABjwWxgAu3Lralxcpq926Ws4jGmtyk7yvu7ARv23CxnWyDzCKspllRX0fl3PdImPmeg_nBb3ZYapUjLz1jupKKP6qbQ" />
              </div>
              <span className="text-sm text-on-surface-variant font-medium">已有 2,400+ 销售团队加入</span>
            </div>
          </div>
        </section>

        {/* Right Side: Login Form */}
        <section className="w-full lg:w-1/2 flex items-center justify-center p-6 sm:p-12 relative">
          <div className="absolute top-1/4 right-1/4 w-64 h-64 bg-primary/10 rounded-full blur-[100px]"></div>
          <div className="absolute bottom-1/4 left-1/4 w-64 h-64 bg-tertiary/10 rounded-full blur-[100px]"></div>
          
          <div className="w-full max-w-md glass-card rounded-[2rem] p-8 md:p-10 shadow-2xl relative z-10 animate-fade-in">
            <div className="flex flex-col items-center mb-10 text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center mb-4 shadow-lg shadow-primary/20">
                <span className="material-symbols-outlined text-on-primary text-4xl" style={{ fontVariationSettings: "'FILL' 1" }}>auto_awesome</span>
              </div>
              <h2 className="text-2xl font-bold font-headline text-on-surface tracking-tight">
                {isLogin ? '欢迎回来' : '创建账号'}
              </h2>
              <p className="text-on-surface-variant text-sm mt-1">
                {isLogin ? '输入您的详细信息以访问工作空间' : '加入 Agent CS Playbook 开始数据洞察之旅'}
              </p>
            </div>

            <div className="flex p-1 bg-surface-container-lowest rounded-full mb-8 border border-outline-variant/10">
              <button 
                type="button"
                onClick={() => { setIsLogin(true); setErrorMsg(''); }}
                className={`flex-1 py-2 text-sm font-semibold rounded-full transition-all duration-300 ${isLogin ? 'bg-surface-container-highest text-primary' : 'text-on-surface-variant hover:text-on-surface'}`}
              >
                登录
              </button>
              <button 
                type="button"
                onClick={() => { setIsLogin(false); setErrorMsg(''); }}
                className={`flex-1 py-2 text-sm font-medium transition-all duration-300 ${!isLogin ? 'bg-surface-container-highest text-primary' : 'text-on-surface-variant hover:text-on-surface'}`}
              >
                创建账号
              </button>
            </div>

            {errorMsg && (
              <div className="mb-6 p-3 bg-error-dim/20 border border-error-dim/40 rounded-xl text-error text-sm text-center">
                {errorMsg}
              </div>
            )}

            <form className="space-y-6" onSubmit={handleSubmit}>
              <div className="relative group">
                <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                  <span className={`material-symbols-outlined text-xl transition-colors ${username ? 'text-primary' : 'text-on-surface-variant group-focus-within:text-primary'}`}>alternate_email</span>
                </div>
                <input 
                  id="username" 
                  type="text" 
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="block w-full pl-12 pr-4 py-4 bg-surface-container-lowest border-0 rounded-xl focus:ring-1 focus:ring-primary/40 text-on-surface text-sm placeholder:text-transparent peer transition-all duration-200 outline-none" 
                  placeholder=" " 
                />
                <label className="absolute text-sm text-on-surface-variant duration-300 transform -translate-y-4 scale-75 top-2 z-10 origin-[0] bg-transparent px-2 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 left-10" htmlFor="username">用户名或邮箱</label>
              </div>

              <div className="relative group">
                <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                  <span className={`material-symbols-outlined text-xl transition-colors ${password ? 'text-primary' : 'text-on-surface-variant group-focus-within:text-primary'}`}>lock_open</span>
                </div>
                <input 
                  id="password" 
                  type={showPassword ? 'text' : 'password'} 
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="block w-full pl-12 pr-12 py-4 bg-surface-container-lowest border-0 rounded-xl focus:ring-1 focus:ring-primary/40 text-on-surface text-sm placeholder:text-transparent peer transition-all duration-200 outline-none" 
                  placeholder=" " 
                />
                <label className="absolute text-sm text-on-surface-variant duration-300 transform -translate-y-4 scale-75 top-2 z-10 origin-[0] bg-transparent px-2 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 left-10" htmlFor="password">密码</label>
                <button 
                  type="button" 
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-4 flex items-center text-on-surface-variant hover:text-primary transition-colors"
                >
                  <span className="material-symbols-outlined text-xl">{showPassword ? 'visibility_off' : 'visibility'}</span>
                </button>
              </div>

              {!isLogin && (
                <div className="relative group transition-opacity animate-in fade-in duration-300">
                  <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                    <span className={`material-symbols-outlined text-xl transition-colors ${nickname ? 'text-primary' : 'text-on-surface-variant group-focus-within:text-primary'}`}>person_outline</span>
                  </div>
                  <input 
                    id="nickname" 
                    type="text" 
                    value={nickname}
                    onChange={(e) => setNickname(e.target.value)}
                    className="block w-full pl-12 pr-4 py-4 bg-surface-container-lowest border-0 rounded-xl focus:ring-1 focus:ring-primary/40 text-on-surface text-sm placeholder:text-transparent peer transition-all duration-200 outline-none" 
                    placeholder=" " 
                  />
                  <label className="absolute text-sm text-on-surface-variant duration-300 transform -translate-y-4 scale-75 top-2 z-10 origin-[0] bg-transparent px-2 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 left-10" htmlFor="nickname">昵称（选填）</label>
                </div>
              )}

              <div className="flex items-center justify-between px-1">
                {isLogin ? (
                  <>
                    <label className="flex items-center gap-2 cursor-pointer group">
                      <input className="w-4 h-4 rounded-sm border-outline-variant bg-surface-container-lowest text-primary focus:ring-offset-background outline-none" type="checkbox" />
                      <span className="text-xs text-on-surface-variant group-hover:text-on-surface transition-colors">记住我</span>
                    </label>
                    <a className="text-xs font-semibold text-primary hover:text-on-primary-container transition-colors" href="#">忘记密码？</a>
                  </>
                ) : (
                  <p className="text-xs text-on-surface-variant text-center w-full">注册即代表您同意<a href="#" className="text-primary hover:underline ml-1">服务条款</a></p>
                )}
              </div>

              <button 
                type="submit" 
                disabled={loading}
                className="w-full py-4 glow-button rounded-xl bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold tracking-wide text-sm flex items-center justify-center gap-2 group transition-all duration-300 active:scale-[0.98] disabled:opacity-70 disabled:active:scale-100"
              >
                {loading ? (
                  <span className="animate-spin w-5 h-5 border-2 border-on-primary/20 border-t-on-primary rounded-full"></span>
                ) : (
                  <>
                    {isLogin ? '立即登录' : '创建账号'}
                    <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
                  </>
                )}
              </button>
            </form>


          </div>
        </section>
      </main>

      {/* Footer Shell */}
      <footer className="fixed bottom-0 w-full z-40 hidden md:block pointer-events-none">
        <div className="flex justify-between items-center px-12 py-8 w-full bg-transparent">
          <span className="text-[11px] font-medium font-body tracking-wide text-[#91aaeb]">© 2026 clearwind · Apache-2.0</span>
          <div className="flex items-center gap-6 pointer-events-auto">
            <a className="text-[11px] font-medium font-body tracking-wide text-[#91aaeb] hover:text-[#bdc2ff] opacity-80 hover:opacity-100 transition-opacity" href="#">隐私政策</a>
            <a className="text-[11px] font-medium font-body tracking-wide text-[#91aaeb] hover:text-[#bdc2ff] opacity-80 hover:opacity-100 transition-opacity" href="#">服务条款</a>
            <a className="text-[11px] font-medium font-body tracking-wide text-[#91aaeb] hover:text-[#bdc2ff] opacity-80 hover:opacity-100 transition-opacity" href="#">支持协助</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
