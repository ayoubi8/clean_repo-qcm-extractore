import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { registerUser } from '../lib/api'

export function Register() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setLoading(true)
    try {
      await registerUser(email, password)
      setSuccess(true)
    } catch (err: any) {
      setError(err.message || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center bg-background p-6 font-sans relative overflow-hidden">
        {/* Decorative Glows */}
        <div className="fixed inset-0 pointer-events-none z-0">
          <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/20 rounded-full blur-[120px] opacity-20 translate-x-1/2 -translate-y-1/2"></div>
          <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-primary-container/20 rounded-full blur-[120px] opacity-20 -translate-x-1/2 translate-y-1/2"></div>
        </div>

        <div className="w-full max-w-[420px] bg-surface-container-low border border-primary/20 rounded-lg p-10 text-center shadow-2xl relative z-10 animate-in fade-in zoom-in-95 duration-500">
          <div className="w-16 h-16 bg-primary/10 border border-primary/30 rounded-full flex items-center justify-center mx-auto mb-6">
            <span className="material-symbols-outlined text-primary text-4xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
          </div>
          <h2 className="text-2xl font-bold text-on-surface mb-2 tracking-tight">Request Submitted!</h2>
          <p className="text-on-surface-variant text-sm mb-8 leading-relaxed">
            Your application has been logged to the clinical monolith. Please wait for an administrator to verify your credentials.
          </p>
          <Link
            to="/login"
            className="inline-block w-full bg-primary/10 hover:bg-primary/20 text-primary font-semibold py-3 rounded transition-all border border-primary/20"
          >
            Back to Login
          </Link>
        </div>

        {/* Fixed Footer */}
        <footer className="fixed bottom-0 w-full flex justify-between items-center px-8 py-4 bg-transparent z-10">
          <div className="text-slate-600 text-[10px] uppercase tracking-widest font-semibold">
            v5.0 | QCM Extractor
          </div>
          <nav className="flex gap-6">
            <span className="text-slate-600 hover:text-primary transition-all duration-300 text-[10px] uppercase tracking-widest font-semibold cursor-pointer">Support</span>
            <span className="text-slate-600 hover:text-primary transition-all duration-300 text-[10px] uppercase tracking-widest font-semibold cursor-pointer">Privacy Policy</span>
          </nav>
        </footer>
      </div>
    )
  }

  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center bg-background p-6 font-sans relative overflow-hidden">
      {/* Decorative Glows */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/20 rounded-full blur-[120px] opacity-20 translate-x-1/2 -translate-y-1/2"></div>
        <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-primary-container/20 rounded-full blur-[120px] opacity-20 -translate-x-1/2 translate-y-1/2"></div>
      </div>

      <main className="w-full max-w-[420px] z-10">
        {/* Brand Header Section */}
        <header className="flex items-center justify-between mb-8 px-1">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded flex items-center justify-center bg-primary-container/10 border border-primary/20 shadow-[0_0_15px_rgba(76,215,246,0.15)]">
              <span className="material-symbols-outlined text-primary text-xl">terminal</span>
            </div>
            <div className="flex flex-col leading-none">
              <span className="text-primary font-bold text-sm tracking-widest uppercase">QCM Extractor</span>
              <span className="text-on-surface-variant text-[10px] font-medium uppercase tracking-[0.2em] opacity-60">v5.0</span>
            </div>
          </div>
        </header>

        {/* Main Registration Card */}
        <div className="bg-surface-container-low border border-outline-variant/10 rounded-lg p-8 shadow-2xl relative overflow-hidden">
          <h1 className="text-on-surface text-[28px] font-bold tracking-tight mb-3">Request Access</h1>
          
          {/* Admin Notice */}
          <div className="flex items-start gap-3 p-3.5 bg-tertiary/5 border border-tertiary/10 rounded mb-8">
            <span className="material-symbols-outlined text-tertiary text-lg mt-0.5">warning</span>
            <p className="text-on-surface-variant text-[12px] leading-relaxed">New accounts require admin approval before access is granted.</p>
          </div>

          {/* Registration Form */}
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Email Field */}
            <div className="space-y-2">
              <label className="block text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider ml-0.5">Email Address</label>
              <input
                type="email"
                required
                className="w-full bg-surface-container-lowest border border-outline-variant px-4 py-3 rounded text-sm text-on-surface placeholder:text-outline/40 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all"
                placeholder="name@medical-institution.org"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            {/* Password Field */}
            <div className="space-y-2">
              <label className="block text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider ml-0.5">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  className="w-full bg-surface-container-lowest border border-outline-variant px-4 py-3 rounded text-sm text-on-surface placeholder:text-outline/40 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all"
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-outline-variant hover:text-on-surface-variant transition-colors"
                >
                  <span className="material-symbols-outlined text-xl">
                    {showPassword ? 'visibility_off' : 'visibility'}
                  </span>
                </button>
              </div>
            </div>

            {/* Confirm Password Field */}
            <div className="space-y-2">
              <label className="block text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider ml-0.5">Confirm Password</label>
              <input
                type="password"
                required
                className="w-full bg-surface-container-lowest border border-outline-variant px-4 py-3 rounded text-sm text-on-surface placeholder:text-outline/40 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all"
                placeholder="••••••••••••"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>

            {error && (
              <div className="bg-error-container/20 border border-error/30 px-4 py-3 rounded flex items-center gap-3 animate-in slide-in-from-top-2 duration-300">
                <span className="material-symbols-outlined text-error text-lg">warning</span>
                <span className="text-[12px] text-error font-medium">{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary-fixed-dim text-on-primary font-bold py-3.5 rounded shadow-lg shadow-primary/10 active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:pointer-events-none"
            >
              {loading ? 'CREATING ACCOUNT...' : 'CREATE ACCOUNT'}
            </button>
          </form>

          {/* Bottom Redirect */}
          <div className="mt-8 pt-6 border-t border-outline-variant/10 text-center">
            <p className="text-on-surface-variant text-[13px]">
              Already have an account? 
              <Link to="/login" className="text-primary hover:text-primary-fixed-dim transition-colors font-medium inline-flex items-center gap-1 ml-1">
                Sign in <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
              </Link>
            </p>
          </div>
        </div>
      </main>

      {/* Fixed Footer */}
      <footer className="fixed bottom-0 w-full flex justify-between items-center px-8 py-4 bg-transparent z-10">
        <div className="text-slate-600 text-[10px] uppercase tracking-widest font-semibold">
          v5.0 | QCM Extractor
        </div>
        <nav className="flex gap-6">
          <span className="text-slate-600 hover:text-primary transition-all duration-300 text-[10px] uppercase tracking-widest font-semibold cursor-pointer">Support</span>
          <span className="text-slate-600 hover:text-primary transition-all duration-300 text-[10px] uppercase tracking-widest font-semibold cursor-pointer">Privacy Policy</span>
        </nav>
      </footer>
    </div>
  )
}
