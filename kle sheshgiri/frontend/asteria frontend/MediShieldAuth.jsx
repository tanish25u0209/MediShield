import { useState } from "react";

const API_BASE =
  (typeof window !== "undefined" && window.__MEDISHIELD_API_BASE__) ||
  (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("api")) ||
  (typeof window !== "undefined" && window.localStorage && window.localStorage.getItem("medishield_api_base")) ||
  "http://127.0.0.1:8000";

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
  * { box-sizing: border-box; }
  body { margin: 0; }
  .ms-root { min-height: 100vh; display: flex; font-family: 'Outfit', sans-serif; background: #060d0a; color: #e8f5ef; }
  .ms-brand { width: 44%; min-height: 100vh; background: #060d0a; display: flex; flex-direction: column; justify-content: space-between; padding: 3rem 3.5rem; position: relative; overflow: hidden; }
  .ms-brand::before { content: ''; position: absolute; inset: 0; background-image: linear-gradient(rgba(29,158,117,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(29,158,117,0.06) 1px, transparent 1px); background-size: 40px 40px; }
  .ms-brand::after { content: ''; position: absolute; bottom: -180px; left: -180px; width: 520px; height: 520px; background: radial-gradient(circle, rgba(29,158,117,0.18) 0%, transparent 65%); pointer-events: none; }
  .ms-logo-row, .ms-hero, .ms-brand-footer { position: relative; z-index: 1; }
  .ms-logo-row { display: flex; align-items: center; gap: 12px; }
  .ms-logo-text { font-size: 20px; font-weight: 700; color: #e8f5ef; }
  .ms-logo-text span { color: #1d9e75; }
  .ms-hero-badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(29,158,117,0.12); border: 1px solid rgba(29,158,117,0.25); color: #5dcaa5; font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; padding: 5px 12px; border-radius: 999px; margin-bottom: 1.5rem; }
  .ms-hero h1 { font-size: 2.6rem; line-height: 1.15; letter-spacing: -1px; margin-bottom: 1rem; }
  .ms-hero h1 em { font-style: normal; color: #1d9e75; }
  .ms-hero p { font-size: 15px; color: rgba(232,245,239,0.58); line-height: 1.7; max-width: 320px; margin-bottom: 2rem; }
  .ms-feature { display: flex; gap: 14px; margin-bottom: 14px; }
  .ms-feature-icon { width: 36px; height: 36px; border-radius: 10px; background: rgba(29,158,117,0.1); border: 1px solid rgba(29,158,117,0.2); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .ms-feature-text strong { display: block; font-size: 13px; margin-bottom: 2px; }
  .ms-feature-text span { font-size: 12px; color: rgba(232,245,239,0.46); line-height: 1.4; }
  .ms-scan-bar { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: rgba(29,158,117,0.07); border: 1px solid rgba(29,158,117,0.15); border-radius: 10px; }
  .ms-scan-line { flex: 1; height: 3px; background: rgba(29,158,117,0.15); border-radius: 2px; overflow: hidden; }
  .ms-scan-progress { height: 100%; background: linear-gradient(90deg, #1d9e75, #5dcaa5); border-radius: 2px; animation: scan-anim 2.5s ease-in-out infinite; }
  .ms-scan-label { font-size: 11px; color: #5dcaa5; font-family: 'Space Mono', monospace; white-space: nowrap; }
  @keyframes scan-anim { 0% { width: 0%; } 60% { width: 85%; } 100% { width: 100%; } }
  .ms-form-panel { flex: 1; display: flex; align-items: center; justify-content: center; background: #0b1510; padding: 2rem; position: relative; }
  .ms-card { width: 100%; max-width: 430px; }
  .ms-tabs { display: flex; background: rgba(255,255,255,0.04); border: 1px solid rgba(29,158,117,0.12); border-radius: 12px; padding: 4px; margin-bottom: 2rem; }
  .ms-tab { flex: 1; padding: 10px; border: none; background: transparent; color: rgba(232,245,239,0.4); font-family: 'Outfit', sans-serif; font-size: 14px; border-radius: 9px; cursor: pointer; }
  .ms-tab.active { background: #1d9e75; color: #fff; }
  .ms-form-header { margin-bottom: 1rem; }
  .ms-form-header h2 { font-size: 1.6rem; margin: 0 0 6px; }
  .ms-form-header p { font-size: 13.5px; color: rgba(232,245,239,0.45); margin: 0; }
  .ms-message { margin-bottom: 1rem; padding: 11px 12px; border-radius: 10px; font-size: 13px; line-height: 1.5; }
  .ms-message.error { background: rgba(255,95,87,0.1); border: 1px solid rgba(255,95,87,0.25); color: #ffc3bf; }
  .ms-message.success { background: rgba(29,158,117,0.1); border: 1px solid rgba(29,158,117,0.22); color: #b8f0db; }
  .ms-fields { display: flex; flex-direction: column; gap: 14px; margin-bottom: 1.5rem; }
  .ms-field label { display: block; font-size: 12px; color: rgba(232,245,239,0.5); text-transform: uppercase; margin-bottom: 6px; }
  .ms-input-wrap { position: relative; }
  .ms-input-wrap svg { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); opacity: 0.35; pointer-events: none; }
  .ms-input { width: 100%; padding: 12px 14px 12px 42px; background: rgba(255,255,255,0.04); border: 1px solid rgba(29,158,117,0.15); border-radius: 10px; color: #e8f5ef; font-family: 'Outfit', sans-serif; font-size: 14px; outline: none; }
  .ms-input:focus { border-color: rgba(29,158,117,0.5); background: rgba(29,158,117,0.04); }
  .ms-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; }
  .ms-check-label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: rgba(232,245,239,0.5); }
  .ms-forgot, .ms-switch button { font-size: 13px; color: #5dcaa5; background: none; border: none; cursor: pointer; font-family: 'Outfit', sans-serif; }
  .ms-submit { width: 100%; padding: 13px; background: #1d9e75; color: #fff; border: none; border-radius: 10px; font-family: 'Outfit', sans-serif; font-size: 15px; font-weight: 600; cursor: pointer; }
  .ms-submit:disabled { opacity: 0.65; cursor: not-allowed; }
  .ms-divider { display: flex; align-items: center; gap: 12px; margin: 1.25rem 0; }
  .ms-divider-line { flex: 1; height: 1px; background: rgba(29,158,117,0.12); }
  .ms-divider span { font-size: 12px; color: rgba(232,245,239,0.25); }
  .ms-oauth { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .ms-oauth-btn { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 10px; background: rgba(255,255,255,0.04); border: 1px solid rgba(29,158,117,0.12); border-radius: 10px; color: rgba(232,245,239,0.6); font-family: 'Outfit', sans-serif; font-size: 13px; }
  .ms-switch { text-align: center; margin-top: 1.25rem; font-size: 13px; color: rgba(232,245,239,0.4); }
  .ms-terms { text-align: center; font-size: 11.5px; color: rgba(232,245,239,0.25); margin-top: 1rem; line-height: 1.6; }
  .ms-success { text-align: center; padding: 2rem 0; }
  .ms-success h3 { font-size: 1.2rem; margin-bottom: 8px; }
  .ms-success p { font-size: 13.5px; color: rgba(232,245,239,0.45); }
  @media (max-width: 768px) { .ms-brand { display: none; } .ms-form-panel { background: #060d0a; } }
`;

const ShieldIcon = () => (
  <svg className="ms-logo-icon" viewBox="0 0 40 40" fill="none">
    <path d="M20 4L6 9v10c0 8.5 5.9 16.4 14 18.8C28.1 35.4 34 27.5 34 19V9L20 4z" fill="rgba(29,158,117,0.15)" stroke="#1D9E75" strokeWidth="1.5"/>
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

const UserIcon = () => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="5" r="3" stroke="#e8f5ef" strokeWidth="1.2"/><path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="#e8f5ef" strokeWidth="1.2" strokeLinecap="round"/></svg>;
const MailIcon = () => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="3" width="14" height="10" rx="1.5" stroke="#e8f5ef" strokeWidth="1.2"/><path d="M1 5l7 5 7-5" stroke="#e8f5ef" strokeWidth="1.2" strokeLinecap="round"/></svg>;
const LockIcon = () => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3" y="7" width="10" height="8" rx="1.5" stroke="#e8f5ef" strokeWidth="1.2"/><path d="M5 7V5a3 3 0 016 0v2" stroke="#e8f5ef" strokeWidth="1.2" strokeLinecap="round"/></svg>;
const GoogleIcon = () => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M14.5 8.1c0-.5-.04-1-.12-1.45H8v2.74h3.65c-.16.85-.63 1.56-1.34 2.04v1.7h2.17c1.27-1.17 2-2.9 2-4.98z" fill="#4285F4"/><path d="M8 15c1.83 0 3.36-.6 4.48-1.64l-2.17-1.7c-.6.41-1.38.65-2.31.65-1.78 0-3.28-1.2-3.82-2.81H1.94v1.75C3.05 13.43 5.36 15 8 15z" fill="#34A853"/><path d="M4.18 9.5A4.44 4.44 0 013.88 8c0-.52.09-1.02.24-1.5V4.75H1.94A6.98 6.98 0 001 8c0 1.13.27 2.2.74 3.15L4.18 9.5z" fill="#FBBC05"/><path d="M8 3.67c1 0 1.9.35 2.61 1.03l1.96-1.96C11.35 1.67 9.82 1 8 1 5.36 1 3.05 2.57 1.94 4.76L4.18 6.5C4.72 4.89 6.22 3.67 8 3.67z" fill="#EA4335"/></svg>;

const features = [
  { icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM11.5 9v6M8.5 12h6" stroke="#1D9E75" strokeWidth="1.3" strokeLinecap="round"/></svg>, label: "Multi-image input", desc: "Upload front, back & blister pack for cross-validation" },
  { icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="#1D9E75" strokeWidth="1.3"/><path d="M5 8l2 2 4-4" stroke="#1D9E75" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>, label: "Batch intelligence", desc: "Detect anomalous scan patterns across geographies" },
  { icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="4" cy="8" r="2" stroke="#1D9E75" strokeWidth="1.3"/><circle cx="12" cy="4" r="2" stroke="#1D9E75" strokeWidth="1.3"/><circle cx="12" cy="12" r="2" stroke="#1D9E75" strokeWidth="1.3"/><path d="M6 7.1l4-2.2M6 8.9l4 2.2" stroke="#1D9E75" strokeWidth="1" strokeLinecap="round"/></svg>, label: "Graph intelligence", desc: "Visual network of batch scan behavior" },
];

export default function MediShieldAuth() {
  const [mode, setMode] = useState("login");
  const [recoverMode, setRecoverMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [resetCode, setResetCode] = useState("");
  const [message, setMessage] = useState({ type: "", text: "" });
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "", reset: "" });

  const update = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const clearState = (nextMode = "login") => {
    setMode(nextMode);
    setRecoverMode(false);
    setDone(false);
    setResetCode("");
    setMessage({ type: "", text: "" });
    setForm({ name: "", email: "", password: "", confirm: "", reset: "" });
  };

  const submit = async () => {
    setLoading(true);
    setMessage({ type: "", text: "" });
    try {
      if (recoverMode) {
        if (!resetCode) {
          const res = await fetch(`${API_BASE}/auth/forgot-password`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: form.email }),
          });
          const payload = await res.json();
          if (!res.ok) throw new Error(payload.detail || "Could not generate reset code");
          setResetCode(payload.reset_code);
          setMessage({ type: "success", text: `Reset code: ${payload.reset_code}. Enter it below with your new password.` });
        } else {
          if (form.password !== form.confirm) throw new Error("Passwords do not match");
          const res = await fetch(`${API_BASE}/auth/reset-password`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: form.email, code: form.reset, new_password: form.password }),
          });
          const payload = await res.json();
          if (!res.ok) throw new Error(payload.detail || "Password reset failed");
          setDone(true);
        }
      } else if (mode === "signup") {
        if (form.password !== form.confirm) throw new Error("Passwords do not match");
        const res = await fetch(`${API_BASE}/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: form.name, email: form.email, password: form.password }),
        });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.detail || "Could not create account");
        setDone(true);
      } else {
        const res = await fetch(`${API_BASE}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: form.email, password: form.password }),
        });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.detail || "Login failed");
        setDone(true);
      }
    } catch (error) {
      setMessage({ type: "error", text: error.message || "Something went wrong" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <style>{styles}</style>
      <div className="ms-root">
        <div className="ms-brand">
          <div className="ms-logo-row">
            <ShieldIcon />
            <span className="ms-logo-text">Medi<span>Shield</span></span>
          </div>
          <div className="ms-hero">
            <div className="ms-hero-badge">AI Risk Intelligence</div>
            <h1>Screen medicines for <em>counterfeit risk</em> in seconds</h1>
            <p>Multi-image analysis across packaging, OCR, and batch scan behavior, not just a visual check.</p>
            {features.map((feature, index) => (
              <div className="ms-feature" key={index}>
                <div className="ms-feature-icon">{feature.icon}</div>
                <div className="ms-feature-text">
                  <strong>{feature.label}</strong>
                  <span>{feature.desc}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="ms-brand-footer">
            <div className="ms-scan-bar">
              <ScanIcon />
              <div className="ms-scan-line"><div className="ms-scan-progress" /></div>
              <span className="ms-scan-label">ANALYZING BATCH B2042...</span>
            </div>
          </div>
        </div>

        <div className="ms-form-panel">
          <div className="ms-card">
            <div className="ms-tabs">
              <button className={`ms-tab${mode === "login" && !recoverMode ? " active" : ""}`} onClick={() => clearState("login")}>Sign In</button>
              <button className={`ms-tab${mode === "signup" && !recoverMode ? " active" : ""}`} onClick={() => clearState("signup")}>Create Account</button>
            </div>

            {done ? (
              <div className="ms-success">
                <h3>{recoverMode ? "Password updated" : mode === "login" ? "Welcome back!" : "Account created!"}</h3>
                <p>{recoverMode ? "Your password has been reset. You can sign in now." : mode === "login" ? "Login successful." : "Your account details have been stored in the database."}</p>
                <button className="ms-submit" onClick={() => clearState("login")}>Back to Sign In</button>
              </div>
            ) : (
              <>
                <div className="ms-form-header">
                  <h2>{recoverMode ? "Recover account" : mode === "login" ? "Welcome back" : "Get started free"}</h2>
                  <p>{recoverMode ? "Request a reset code and set a new password" : mode === "login" ? "Sign in to access your MediShield dashboard" : "Create an account to save login details securely"}</p>
                </div>

                {message.text && <div className={`ms-message ${message.type}`}>{message.text}</div>}

                <div className="ms-fields">
                  {mode === "signup" && !recoverMode && (
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
                  {(!recoverMode || resetCode) && (
                    <div className="ms-field">
                      <label>{recoverMode ? "New Password" : "Password"}</label>
                      <div className="ms-input-wrap">
                        <LockIcon />
                        <input className="ms-input" type="password" placeholder="********" value={form.password} onChange={update("password")} />
                      </div>
                    </div>
                  )}
                  {recoverMode && resetCode && (
                    <div className="ms-field">
                      <label>Reset Code</label>
                      <div className="ms-input-wrap">
                        <LockIcon />
                        <input className="ms-input" type="text" placeholder="Enter 6-digit code" value={form.reset} onChange={update("reset")} />
                      </div>
                    </div>
                  )}
                  {(mode === "signup" || (recoverMode && resetCode)) && (
                    <div className="ms-field">
                      <label>Confirm Password</label>
                      <div className="ms-input-wrap">
                        <LockIcon />
                        <input className="ms-input" type="password" placeholder="********" value={form.confirm} onChange={update("confirm")} />
                      </div>
                    </div>
                  )}
                </div>

                {mode === "login" && !recoverMode && (
                  <div className="ms-row">
                    <label className="ms-check-label"><input type="checkbox" defaultChecked /> Remember me</label>
                    <button className="ms-forgot" onClick={() => { setRecoverMode(true); setMessage({ type: "", text: "" }); setResetCode(""); setForm((current) => ({ ...current, password: "", confirm: "", reset: "" })); }}>Forgot password?</button>
                  </div>
                )}

                <button className="ms-submit" onClick={submit} disabled={loading}>
                  {loading ? "Please wait..." : recoverMode ? (resetCode ? "Reset Password ->" : "Get Reset Code ->") : mode === "login" ? "Sign In ->" : "Create Account ->"}
                </button>

                {!recoverMode && (
                  <>
                    <div className="ms-divider">
                      <div className="ms-divider-line" />
                      <span>or continue with</span>
                      <div className="ms-divider-line" />
                    </div>
                    <div className="ms-oauth">
                      <button className="ms-oauth-btn"><GoogleIcon /> Google</button>
                      <button className="ms-oauth-btn">Hospital SSO</button>
                    </div>
                  </>
                )}

                <div className="ms-switch">
                  {recoverMode ? (
                    <>Remembered your password? <button onClick={() => clearState("login")}>Back to sign in</button></>
                  ) : mode === "login" ? (
                    <>Don't have an account? <button onClick={() => clearState("signup")}>Sign up free</button></>
                  ) : (
                    <>Already have an account? <button onClick={() => clearState("login")}>Sign in</button></>
                  )}
                </div>

                {mode === "signup" && !recoverMode && (
                  <p className="ms-terms">By creating an account, you agree to our Terms of Service and Privacy Policy.</p>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
