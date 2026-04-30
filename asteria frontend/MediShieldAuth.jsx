import { useState } from "react";

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  .ms-root {
    min-height: 100vh;
    display: flex;
    font-family: 'Outfit', sans-serif;
    background: #060D0A;
    color: #e8f5ef;
  }

  /* ─── LEFT BRAND PANEL ─── */
  .ms-brand {
    width: 44%;
    min-height: 100vh;
    background: #060D0A;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 3rem 3.5rem;
    position: relative;
    overflow: hidden;
  }

  .ms-brand::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(29,158,117,0.06) 1px, transparent 1px),
      linear-gradient(90deg, rgba(29,158,117,0.06) 1px, transparent 1px);
    background-size: 40px 40px;
  }

  .ms-brand::after {
    content: '';
    position: absolute;
    bottom: -180px;
    left: -180px;
    width: 520px;
    height: 520px;
    background: radial-gradient(circle, rgba(29,158,117,0.18) 0%, transparent 65%);
    pointer-events: none;
  }

  .ms-logo-row {
    display: flex;
    align-items: center;
    gap: 12px;
    position: relative;
    z-index: 1;
  }

  .ms-logo-icon {
    width: 40px;
    height: 40px;
  }

  .ms-logo-text {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: #e8f5ef;
  }

  .ms-logo-text span {
    color: #1D9E75;
  }

  .ms-hero {
    position: relative;
    z-index: 1;
  }

  .ms-hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(29,158,117,0.12);
    border: 1px solid rgba(29,158,117,0.25);
    color: #5DCAA5;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 5px 12px;
    border-radius: 100px;
    margin-bottom: 1.5rem;
  }

  .ms-hero-badge::before {
    content: '';
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #1D9E75;
    animation: pulse-dot 2s infinite;
  }

  @keyframes pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }

  .ms-hero h1 {
    font-size: 2.6rem;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: -1px;
    color: #e8f5ef;
    margin-bottom: 1rem;
  }

  .ms-hero h1 em {
    font-style: normal;
    color: #1D9E75;
  }

  .ms-hero p {
    font-size: 15px;
    color: rgba(232,245,239,0.55);
    line-height: 1.7;
    max-width: 300px;
    margin-bottom: 2.5rem;
  }

  .ms-features {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .ms-feature {
    display: flex;
    align-items: flex-start;
    gap: 14px;
  }

  .ms-feature-icon {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: rgba(29,158,117,0.1);
    border: 1px solid rgba(29,158,117,0.2);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 1px;
  }

  .ms-feature-text strong {
    display: block;
    font-size: 13px;
    font-weight: 600;
    color: #c5e8d8;
    margin-bottom: 2px;
  }

  .ms-feature-text span {
    font-size: 12px;
    color: rgba(232,245,239,0.4);
    line-height: 1.4;
  }

  .ms-brand-footer {
    position: relative;
    z-index: 1;
  }

  .ms-scan-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: rgba(29,158,117,0.07);
    border: 1px solid rgba(29,158,117,0.15);
    border-radius: 10px;
  }

  .ms-scan-line {
    flex: 1;
    height: 3px;
    background: rgba(29,158,117,0.15);
    border-radius: 2px;
    overflow: hidden;
  }

  .ms-scan-progress {
    height: 100%;
    background: linear-gradient(90deg, #1D9E75, #5DCAA5);
    border-radius: 2px;
    animation: scan-anim 2.5s ease-in-out infinite;
  }

  @keyframes scan-anim {
    0% { width: 0%; }
    60% { width: 85%; }
    100% { width: 100%; }
  }

  .ms-scan-label {
    font-size: 11px;
    color: #5DCAA5;
    font-family: 'Space Mono', monospace;
    white-space: nowrap;
  }

  /* ─── RIGHT FORM PANEL ─── */
  .ms-form-panel {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #0B1510;
    padding: 2rem;
    position: relative;
  }

  .ms-form-panel::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 3px;
    background: linear-gradient(90deg, transparent, #1D9E75, transparent);
    opacity: 0.5;
  }

  .ms-card {
    width: 100%;
    max-width: 420px;
  }

  .ms-tabs {
    display: flex;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(29,158,117,0.12);
    border-radius: 12px;
    padding: 4px;
    margin-bottom: 2rem;
  }

  .ms-tab {
    flex: 1;
    padding: 10px;
    border: none;
    background: transparent;
    color: rgba(232,245,239,0.4);
    font-family: 'Outfit', sans-serif;
    font-size: 14px;
    font-weight: 500;
    border-radius: 9px;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .ms-tab.active {
    background: #1D9E75;
    color: #fff;
  }

  .ms-tab:hover:not(.active) {
    color: rgba(232,245,239,0.7);
    background: rgba(29,158,117,0.08);
  }

  .ms-form-header {
    margin-bottom: 1.75rem;
  }

  .ms-form-header h2 {
    font-size: 1.6rem;
    font-weight: 700;
    color: #e8f5ef;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
  }

  .ms-form-header p {
    font-size: 13.5px;
    color: rgba(232,245,239,0.45);
  }

  .ms-fields {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-bottom: 1.5rem;
  }

  .ms-field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .ms-field label {
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.5px;
    color: rgba(232,245,239,0.5);
    text-transform: uppercase;
  }

  .ms-input-wrap {
    position: relative;
  }

  .ms-input-wrap svg {
    position: absolute;
    left: 14px;
    top: 50%;
    transform: translateY(-50%);
    opacity: 0.35;
    pointer-events: none;
  }

  .ms-input {
    width: 100%;
    padding: 12px 14px 12px 42px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(29,158,117,0.15);
    border-radius: 10px;
    color: #e8f5ef;
    font-family: 'Outfit', sans-serif;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s, background 0.2s;
  }

  .ms-input::placeholder {
    color: rgba(232,245,239,0.2);
  }

  .ms-input:focus {
    border-color: rgba(29,158,117,0.5);
    background: rgba(29,158,117,0.04);
  }

  .ms-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.25rem;
  }

  .ms-check-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    font-size: 13px;
    color: rgba(232,245,239,0.5);
  }

  .ms-check-label input[type="checkbox"] {
    accent-color: #1D9E75;
    width: 14px;
    height: 14px;
  }

  .ms-forgot {
    font-size: 13px;
    color: #5DCAA5;
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    font-family: 'Outfit', sans-serif;
  }

  .ms-forgot:hover {
    color: #1D9E75;
  }

  .ms-submit {
    width: 100%;
    padding: 13px;
    background: #1D9E75;
    color: #fff;
    border: none;
    border-radius: 10px;
    font-family: 'Outfit', sans-serif;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s, transform 0.1s;
    position: relative;
    overflow: hidden;
  }

  .ms-submit:hover {
    background: #0F6E56;
  }

  .ms-submit:active {
    transform: scale(0.99);
  }

  .ms-submit:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .ms-submit.loading::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.15) 50%, transparent 100%);
    animation: shimmer 1.2s infinite;
  }

  @keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
  }

  .ms-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 1.25rem 0;
  }

  .ms-divider-line {
    flex: 1;
    height: 1px;
    background: rgba(29,158,117,0.12);
  }

  .ms-divider span {
    font-size: 12px;
    color: rgba(232,245,239,0.25);
    white-space: nowrap;
  }

  .ms-oauth {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .ms-oauth-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 10px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(29,158,117,0.12);
    border-radius: 10px;
    color: rgba(232,245,239,0.6);
    font-family: 'Outfit', sans-serif;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
  }

  .ms-oauth-btn:hover {
    background: rgba(29,158,117,0.07);
    border-color: rgba(29,158,117,0.25);
    color: #e8f5ef;
  }

  .ms-switch {
    text-align: center;
    margin-top: 1.25rem;
    font-size: 13px;
    color: rgba(232,245,239,0.4);
  }

  .ms-switch button {
    background: none;
    border: none;
    color: #5DCAA5;
    font-family: 'Outfit', sans-serif;
    font-size: 13px;
    cursor: pointer;
    font-weight: 500;
  }

  .ms-switch button:hover { color: #1D9E75; }

  .ms-success {
    text-align: center;
    padding: 2rem 0;
  }

  .ms-success-icon {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: rgba(29,158,117,0.12);
    border: 1px solid rgba(29,158,117,0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 1.25rem;
    animation: pop-in 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  }

  @keyframes pop-in {
    0% { transform: scale(0); opacity: 0; }
    100% { transform: scale(1); opacity: 1; }
  }

  .ms-success h3 {
    font-size: 1.2rem;
    font-weight: 600;
    color: #e8f5ef;
    margin-bottom: 8px;
  }

  .ms-success p {
    font-size: 13.5px;
    color: rgba(232,245,239,0.45);
  }

  .ms-terms {
    text-align: center;
    font-size: 11.5px;
    color: rgba(232,245,239,0.25);
    margin-top: 1rem;
    line-height: 1.6;
  }

  .ms-terms a {
    color: #5DCAA5;
    text-decoration: none;
  }

  @media (max-width: 768px) {
    .ms-brand { display: none; }
    .ms-form-panel { background: #060D0A; }
  }
`;

const ShieldIcon = () => (
  <svg className="ms-logo-icon" viewBox="0 0 40 40" fill="none">
    <path d="M20 4L6 9v10c0 8.5 5.9 16.4 14 18.8C28.1 35.4 34 27.5 34 19V9L20 4z" fill="rgba(29,158,117,0.15)" stroke="#1D9E75" strokeWidth="1.5"/>
    <path d="M20 4L6 9v10c0 8.5 5.9 16.4 14 18.8" stroke="#5DCAA5" strokeWidth="1" opacity="0.4"/>
    <line x1="20" y1="13" x2="20" y2="27" stroke="#1D9E75" strokeWidth="2" strokeLinecap="round"/>
    <line x1="13" y1="20" x2="27" y2="20" stroke="#1D9E75" strokeWidth="2" strokeLinecap="round"/>
  </svg>
);

const ScanIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <rect x="1" y="1" width="3" height="3" rx="0.5" stroke="#5DCAA5" strokeWidth="1.2"/>
    <rect x="10" y="1" width="3" height="3" rx="0.5" stroke="#5DCAA5" strokeWidth="1.2"/>
    <rect x="1" y="10" width="3" height="3" rx="0.5" stroke="#5DCAA5" strokeWidth="1.2"/>
    <line x1="7" y1="2" x2="7" y2="12" stroke="#5DCAA5" strokeWidth="0.8" opacity="0.4"/>
  </svg>
);

const UserIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="5" r="3" stroke="#e8f5ef" strokeWidth="1.2"/>
    <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="#e8f5ef" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
);

const MailIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <rect x="1" y="3" width="14" height="10" rx="1.5" stroke="#e8f5ef" strokeWidth="1.2"/>
    <path d="M1 5l7 5 7-5" stroke="#e8f5ef" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
);

const LockIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <rect x="3" y="7" width="10" height="8" rx="1.5" stroke="#e8f5ef" strokeWidth="1.2"/>
    <path d="M5 7V5a3 3 0 016 0v2" stroke="#e8f5ef" strokeWidth="1.2" strokeLinecap="round"/>
    <circle cx="8" cy="11" r="1" fill="#e8f5ef"/>
  </svg>
);

const GoogleIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M14.5 8.1c0-.5-.04-1-.12-1.45H8v2.74h3.65c-.16.85-.63 1.56-1.34 2.04v1.7h2.17c1.27-1.17 2-2.9 2-4.98z" fill="#4285F4"/>
    <path d="M8 15c1.83 0 3.36-.6 4.48-1.64l-2.17-1.7c-.6.41-1.38.65-2.31.65-1.78 0-3.28-1.2-3.82-2.81H1.94v1.75C3.05 13.43 5.36 15 8 15z" fill="#34A853"/>
    <path d="M4.18 9.5A4.44 4.44 0 013.88 8c0-.52.09-1.02.24-1.5V4.75H1.94A6.98 6.98 0 001 8c0 1.13.27 2.2.74 3.15L4.18 9.5z" fill="#FBBC05"/>
    <path d="M8 3.67c1 0 1.9.35 2.61 1.03l1.96-1.96C11.35 1.67 9.82 1 8 1 5.36 1 3.05 2.57 1.94 4.76L4.18 6.5C4.72 4.89 6.22 3.67 8 3.67z" fill="#EA4335"/>
  </svg>
);

const features = [
  {
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM11.5 9v6M8.5 12h6" stroke="#1D9E75" strokeWidth="1.3" strokeLinecap="round"/></svg>,
    label: "Multi-image scanning",
    desc: "Upload front, back & blister pack for cross-validation"
  },
  {
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="#1D9E75" strokeWidth="1.3"/><path d="M5 8l2 2 4-4" stroke="#1D9E75" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
    label: "Batch intelligence",
    desc: "Detect anomalous scan patterns across geographies"
  },
  {
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="4" cy="8" r="2" stroke="#1D9E75" strokeWidth="1.3"/><circle cx="12" cy="4" r="2" stroke="#1D9E75" strokeWidth="1.3"/><circle cx="12" cy="12" r="2" stroke="#1D9E75" strokeWidth="1.3"/><path d="M6 7.1l4-2.2M6 8.9l4 2.2" stroke="#1D9E75" strokeWidth="1" strokeLinecap="round"/></svg>,
    label: "Graph-based anomaly detection",
    desc: "Visual network of batch scan behavior"
  }
];

export default function MediShieldAuth() {
  const [mode, setMode] = useState("login");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "" });

  const update = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = () => {
    setLoading(true);
    setTimeout(() => { setLoading(false); setDone(true); }, 1800);
  };

  const switchMode = (m) => { setMode(m); setDone(false); setForm({ name: "", email: "", password: "", confirm: "" }); };

  return (
    <>
      <style>{styles}</style>
      <div className="ms-root">

        {/* ── BRAND PANEL ── */}
        <div className="ms-brand">
          <div className="ms-logo-row">
            <ShieldIcon />
            <span className="ms-logo-text">Medi<span>Shield</span></span>
          </div>

          <div className="ms-hero">
            <div className="ms-hero-badge">AI Risk Intelligence</div>
            <h1>Detect <em>counterfeit</em> medicine risk in seconds</h1>
            <p>Multi-signal analysis across packaging, OCR, and batch scan behavior — not just a visual check.</p>
            <div className="ms-features">
              {features.map((f, i) => (
                <div className="ms-feature" key={i}>
                  <div className="ms-feature-icon">{f.icon}</div>
                  <div className="ms-feature-text">
                    <strong>{f.label}</strong>
                    <span>{f.desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="ms-brand-footer">
            <div className="ms-scan-bar">
              <ScanIcon />
              <div className="ms-scan-line"><div className="ms-scan-progress" /></div>
              <span className="ms-scan-label">ANALYZING BATCH B2042…</span>
            </div>
          </div>
        </div>

        {/* ── FORM PANEL ── */}
        <div className="ms-form-panel">
          <div className="ms-card">

            {/* Tabs */}
            <div className="ms-tabs">
              <button className={`ms-tab${mode === "login" ? " active" : ""}`} onClick={() => switchMode("login")}>Sign In</button>
              <button className={`ms-tab${mode === "signup" ? " active" : ""}`} onClick={() => switchMode("signup")}>Create Account</button>
            </div>

            {done ? (
              <div className="ms-success">
                <div className="ms-success-icon">
                  <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                    <path d="M6 14l5 5 11-10" stroke="#1D9E75" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <h3>{mode === "login" ? "Welcome back!" : "Account created!"}</h3>
                <p>{mode === "login" ? "Redirecting to your dashboard…" : "Verification email sent. Check your inbox."}</p>
              </div>
            ) : (
              <>
                <div className="ms-form-header">
                  <h2>{mode === "login" ? "Welcome back" : "Get started free"}</h2>
                  <p>{mode === "login" ? "Sign in to access your MediShield dashboard" : "Scan your first medicine in under 2 minutes"}</p>
                </div>

                <div className="ms-fields">
                  {mode === "signup" && (
                    <div className="ms-field">
                      <label>Full Name</label>
                      <div className="ms-input-wrap">
                        <UserIcon />
                        <input className="ms-input" type="text" placeholder="Dr. Anil Kumar" value={form.name} onChange={update("name")} />
                      </div>
                    </div>
                  )}
                  <div className="ms-field">
                    <label>Email Address</label>
                    <div className="ms-input-wrap">
                      <MailIcon />
                      <input className="ms-input" type="email" placeholder="you@hospital.com" value={form.email} onChange={update("email")} />
                    </div>
                  </div>
                  <div className="ms-field">
                    <label>Password</label>
                    <div className="ms-input-wrap">
                      <LockIcon />
                      <input className="ms-input" type="password" placeholder="••••••••" value={form.password} onChange={update("password")} />
                    </div>
                  </div>
                  {mode === "signup" && (
                    <div className="ms-field">
                      <label>Confirm Password</label>
                      <div className="ms-input-wrap">
                        <LockIcon />
                        <input className="ms-input" type="password" placeholder="••••••••" value={form.confirm} onChange={update("confirm")} />
                      </div>
                    </div>
                  )}
                </div>

                {mode === "login" && (
                  <div className="ms-row">
                    <label className="ms-check-label">
                      <input type="checkbox" defaultChecked /> Remember me
                    </label>
                    <button className="ms-forgot">Forgot password?</button>
                  </div>
                )}

                <button
                  className={`ms-submit${loading ? " loading" : ""}`}
                  onClick={submit}
                  disabled={loading}
                >
                  {loading ? "Verifying…" : mode === "login" ? "Sign In →" : "Create Account →"}
                </button>

                <div className="ms-divider">
                  <div className="ms-divider-line" />
                  <span>or continue with</span>
                  <div className="ms-divider-line" />
                </div>

                <div className="ms-oauth">
                  <button className="ms-oauth-btn"><GoogleIcon /> Google</button>
                  <button className="ms-oauth-btn">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <rect x="1" y="1" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.2"/>
                      <path d="M6 13V7h4v6M6 7V5a2 2 0 014 0v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
                    </svg>
                    Hospital SSO
                  </button>
                </div>

                <div className="ms-switch">
                  {mode === "login" ? (
                    <>Don't have an account? <button onClick={() => switchMode("signup")}>Sign up free</button></>
                  ) : (
                    <>Already have an account? <button onClick={() => switchMode("login")}>Sign in</button></>
                  )}
                </div>

                {mode === "signup" && (
                  <p className="ms-terms">By creating an account, you agree to our <a href="#">Terms of Service</a> and <a href="#">Privacy Policy</a></p>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
