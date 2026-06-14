import React, { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  
  const { login, loadFromStorage, token } = useAuthStore()
  const navigate = useNavigate()

  useEffect(() => {
    loadFromStorage()
  }, [loadFromStorage])

  useEffect(() => {
    if (token) {
      navigate('/')
    }
  }, [token, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    
    try {
      await login(email, password)
      navigate('/')
    } catch (err: any) {
      setError(err.message || 'An error occurred during login')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen w-full flex flex-col bg-surface font-sans selection:bg-primary selection:text-on-primary relative overflow-hidden">
      {/* Fixed Inset Decorative Glows */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/10 rounded-full blur-[120px] opacity-20 translate-x-1/2 -translate-y-1/2"></div>
        <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-primary-container/10 rounded-full blur-[120px] opacity-20 -translate-x-1/2 translate-y-1/2"></div>
      </div>

      {/* Fixed Top Header Bar */}
      <header className="fixed top-0 w-full z-50 bg-surface/60 backdrop-blur-xl border-b border-outline-variant/10 shadow-2xl shadow-black/40">
        <div className="flex justify-between items-center px-8 py-4">
          <div className="text-lg font-bold tracking-tighter text-on-surface uppercase">
            Clinical Monolith AI
          </div>
          <nav className="hidden md:flex gap-6 text-outline font-semibold text-[11px] uppercase tracking-widest">
            <span className="cursor-pointer hover:text-primary transition-colors">Docs</span>
            <span className="cursor-pointer hover:text-primary transition-colors">API</span>
            <span className="cursor-pointer text-primary">Support</span>
          </nav>
        </div>
      </header>

      <main className="flex-grow flex items-center justify-center px-4 pt-20 pb-12 relative z-10">
        <div className="w-full max-w-[420px] bg-surface-container-low border border-outline-variant/10 rounded-lg p-8 shadow-[0_0_20px_-5px_rgba(76,215,246,0.15)] flex flex-col gap-6 animate-in fade-in zoom-in-95 duration-500">
          
          {/* Branding Row */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-surface-container-lowest border border-primary/20 rounded flex items-center justify-center shadow-[0_0_15px_rgba(76,215,246,0.1)]">
              <span className="material-symbols-outlined text-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>terminal</span>
            </div>
            <div className="flex flex-col">
              <span className="text-primary font-extrabold uppercase tracking-widest text-sm">QCM Extractor</span>
              <span className="text-[10px] text-outline font-mono opacity-60">v5.0</span>
            </div>
          </div>

          {/* Title Section */}
          <div className="space-y-1">
            <h1 className="text-2xl font-bold text-on-surface tracking-tight">Welcome back</h1>
            <p className="text-[13px] text-on-surface-variant opacity-80">Sign in to your account</p>
          </div>

          {/* Pending Status Bar */}
          {error === 'PENDING_APPROVAL' && (
            <div className="bg-tertiary-container/10 border border-tertiary/20 px-4 py-3 rounded flex items-center gap-3 animate-in slide-in-from-top-2 duration-300">
              <span className="material-symbols-outlined text-tertiary text-lg">lock</span>
              <span className="text-[12px] text-tertiary font-medium">Your account is pending admin approval</span>
            </div>
          )}

          {/* Login Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email Field */}
            <div className="space-y-1.5">
              <label className="text-[10px] uppercase tracking-wider font-bold text-on-surface-variant/70 ml-1">Email Address</label>
              <input
                type="email"
                required
                className="w-full bg-surface-container-lowest border border-outline-variant px-4 py-3 text-on-surface text-sm rounded focus:ring-1 focus:ring-primary focus:border-primary outline-none transition-all placeholder:text-outline/30"
                placeholder="name@medical-institution.org"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            {/* Password Field */}
            <div className="space-y-1.5">
              <div className="flex justify-between items-center px-1">
                <label className="text-[10px] uppercase tracking-wider font-bold text-on-surface-variant/70">Password</label>
                <span className="text-[10px] text-primary cursor-pointer hover:underline">Forgot?</span>
              </div>
              <div className="relative group">
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  className="w-full bg-surface-container-lowest border border-outline-variant px-4 py-3 text-on-surface text-sm rounded focus:ring-1 focus:ring-primary focus:border-primary outline-none transition-all placeholder:text-outline/30"
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-outline-variant hover:text-primary transition-colors"
                >
                  <span className="material-symbols-outlined text-lg">
                    {showPassword ? 'visibility_off' : 'visibility'}
                  </span>
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-surface-tint text-on-primary font-bold py-3.5 px-4 rounded flex items-center justify-center gap-2 group transition-all active:scale-[0.98] shadow-lg shadow-primary/10 disabled:opacity-50 disabled:pointer-events-none"
            >
              {loading ? 'SIGNING IN...' : 'SIGN IN'}
              {!loading && <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>}
            </button>
          </form>

          {/* Error Status Bar */}
          {error && error !== 'PENDING_APPROVAL' && (
            <div className="bg-error-container/20 border border-error/30 px-4 py-3 rounded flex items-center gap-3 animate-in slide-in-from-top-2 duration-300">
              <span className="material-symbols-outlined text-error text-lg">warning</span>
              <span className="text-[12px] text-error font-medium">{error}</span>
            </div>
          )}

          {/* Divider */}
          <div className="h-[1px] bg-outline-variant/10 w-full"></div>

          {/* Footer Link */}
          <div className="text-center">
            <Link to="/register" className="text-[12px] text-on-surface-variant hover:text-primary transition-colors group">
              Don't have an account? <span className="font-semibold">Request access <span className="inline-block group-hover:translate-x-1 transition-transform">-&gt;</span></span>
            </Link>
          </div>
        </div>
      </main>

      {/* Decorative Text */}
      <div className="fixed bottom-0 right-0 p-12 opacity-5 pointer-events-none hidden lg:block">
        <span className="text-[12rem] font-black tracking-tighter text-primary-container leading-none">QCM</span>
      </div>

      {/* Footer */}
      <footer class="w-full py-8 border-t border-white/5 bg-surface relative z-10">
        <div class="flex flex-col md:flex-row justify-between items-center px-8 gap-4">
          <div class="text-[10px] uppercase tracking-[0.2em] font-medium text-slate-500">
            © 2024 QCM Extractor. Precision Diagnostic Systems.
          </div>
          <div class="flex gap-6">
            <a class="text-[10px] uppercase tracking-[0.2em] font-medium text-slate-500 hover:text-slate-300 transition-colors opacity-80 hover:opacity-100" href="#">Privacy Policy</a>
            <a class="text-[10px] uppercase tracking-[0.2em] font-medium text-slate-500 hover:text-slate-300 transition-colors opacity-80 hover:opacity-100" href="#">Terms of Service</a>
            <a class="text-[10px] uppercase tracking-[0.2em] font-medium text-slate-500 hover:text-slate-300 transition-colors opacity-80 hover:opacity-100" href="#">Security Audit</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
