import { useState, useEffect, useCallback } from "react";

const API = "http://localhost:8000";

type Page = "overview" | "tokens" | "apikeys" | "integration" | "settings";

interface Token { id: string; preview: string; active: boolean; added_at: string; }
interface ApiKey { id: string; key: string; label: string; active: boolean; created_at: string; }
interface Status { tokens: number; api_keys: number; browser_connected: boolean; recaptcha_ready: boolean; uptime: number; }

function useApi<T>(url: string, trigger?: unknown) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const refetch = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(url, { headers: { "X-Admin-Password": pw() } });
      if (r.ok) setData(await r.json());
    } finally { setLoading(false); }
  }, [url]);
  useEffect(() => { refetch(); }, [trigger, refetch]);
  return { data, loading, refetch };
}

function pw() { return sessionStorage.getItem("pw") || ""; }

// ── Login ──────────────────────────────────────────────────────────────────────
function Login({ onLogin }: { onLogin: () => void }) {
  const [pass, setPass] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setErr("");
    try {
      const r = await fetch(`${API}/admin/status`, { headers: { "X-Admin-Password": pass } });
      if (r.ok) { sessionStorage.setItem("pw", pass); onLogin(); }
      else setErr("Wrong password");
    } catch { setErr("Bridge not running — start it with: cd bridge && python -m src.main"); }
    finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 shadow-xl mb-4">
            <span className="text-2xl">🦊</span>
          </div>
          <h1 className="text-2xl font-bold text-white">Arena Bridge</h1>
          <p className="text-slate-400 text-sm mt-1">Admin Dashboard</p>
        </div>
        <form onSubmit={submit} className="bg-slate-800 rounded-2xl p-6 border border-slate-700 space-y-4">
          <div>
            <label className="text-sm text-slate-300 mb-1 block">Password</label>
            <input
              type="password" value={pass} onChange={e => setPass(e.target.value)}
              placeholder="admin"
              className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-violet-500"
            />
          </div>
          {err && <p className="text-red-400 text-sm bg-red-900/20 rounded-lg px-3 py-2">{err}</p>}
          <button type="submit" disabled={loading}
            className="w-full bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-xl py-3 font-medium transition-colors">
            {loading ? "Connecting..." : "Login"}
          </button>
          <p className="text-slate-500 text-xs text-center">Default password: <code className="text-slate-400">admin</code></p>
        </form>
      </div>
    </div>
  );
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
const NAV = [
  { id: "overview", icon: "📊", label: "Overview" },
  { id: "tokens", icon: "🔑", label: "Arena Tokens" },
  { id: "apikeys", icon: "🗝️", label: "API Keys" },
  { id: "integration", icon: "🔌", label: "Integration" },
  { id: "settings", icon: "⚙️", label: "Settings" },
] as const;

function Sidebar({ page, setPage, status }: { page: Page; setPage: (p: Page) => void; status: Status | null }) {
  return (
    <div className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col">
      <div className="p-6 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-lg">🦊</div>
          <div>
            <div className="text-white font-semibold text-sm">Arena Bridge</div>
            <div className="text-slate-500 text-xs">Admin Panel</div>
          </div>
        </div>
      </div>

      {status && (
        <div className="mx-4 mt-4 p-3 rounded-xl bg-slate-800 border border-slate-700">
          <div className="flex items-center gap-2 mb-2">
            <div className={`h-2 w-2 rounded-full ${status.browser_connected ? "bg-green-400" : "bg-red-400"}`} />
            <span className="text-xs text-slate-300">{status.browser_connected ? "Browser connected" : "No browser"}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${status.recaptcha_ready ? "bg-green-400" : "bg-yellow-400"}`} />
            <span className="text-xs text-slate-300">{status.recaptcha_ready ? "reCAPTCHA ready" : "reCAPTCHA pending"}</span>
          </div>
        </div>
      )}

      <nav className="flex-1 p-4 space-y-1">
        {NAV.map(n => (
          <button key={n.id} onClick={() => setPage(n.id as Page)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${page === n.id ? "bg-violet-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"}`}>
            <span>{n.icon}</span>{n.label}
          </button>
        ))}
      </nav>

      <div className="p-4 border-t border-slate-800">
        <button onClick={() => { sessionStorage.removeItem("pw"); window.location.reload(); }}
          className="w-full text-slate-500 hover:text-slate-300 text-xs py-2 transition-colors">
          Logout
        </button>
      </div>
    </div>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────
function Overview({ status, refetch }: { status: Status | null; refetch: () => void }) {
  useEffect(() => { const t = setInterval(refetch, 3000); return () => clearInterval(t); }, [refetch]);

  const cards = [
    { label: "Arena Tokens", value: status?.tokens ?? 0, icon: "🔑", color: "from-violet-500 to-indigo-600" },
    { label: "API Keys", value: status?.api_keys ?? 0, icon: "🗝️", color: "from-blue-500 to-cyan-600" },
    { label: "Browser", value: status?.browser_connected ? "Connected" : "Offline", icon: "🌐", color: status?.browser_connected ? "from-green-500 to-emerald-600" : "from-red-500 to-rose-600" },
    { label: "reCAPTCHA", value: status?.recaptcha_ready ? "Ready ✅" : "Pending ⏳", icon: "🤖", color: status?.recaptcha_ready ? "from-green-500 to-emerald-600" : "from-yellow-500 to-orange-600" },
  ];

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Overview</h2>
        <p className="text-slate-400 text-sm mt-1">Bridge status and quick info</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {cards.map(c => (
          <div key={c.label} className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
            <div className={`inline-flex h-10 w-10 rounded-xl bg-gradient-to-br ${c.color} items-center justify-center text-xl mb-3`}>{c.icon}</div>
            <div className="text-2xl font-bold text-white">{c.value}</div>
            <div className="text-slate-400 text-sm">{c.label}</div>
          </div>
        ))}
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">Quick Start</h3>
        <ol className="space-y-2 text-sm text-slate-300">
          <li className="flex gap-2"><span className="text-violet-400 font-bold">1.</span> Add your <code className="bg-slate-700 px-1 rounded">arena-auth-prod-v1.0</code> cookie in <strong>Arena Tokens</strong></li>
          <li className="flex gap-2"><span className="text-violet-400 font-bold">2.</span> Install Tampermonkey userscript from <strong>Integration</strong> page</li>
          <li className="flex gap-2"><span className="text-violet-400 font-bold">3.</span> Open arena.ai and send one message to warm up reCAPTCHA</li>
          <li className="flex gap-2"><span className="text-violet-400 font-bold">4.</span> Use <code className="bg-slate-700 px-1 rounded">http://localhost:8000/api/v1</code> as your OpenAI base URL</li>
        </ol>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">API Endpoints</h3>
        <div className="space-y-2 font-mono text-xs">
          {[
            ["GET", "/api/v1/models", "List all models"],
            ["POST", "/api/v1/chat/completions", "Chat (OpenAI-compatible)"],
            ["GET", "/health", "Health check"],
          ].map(([m, p, d]) => (
            <div key={p} className="flex items-center gap-3 bg-slate-700/50 rounded-lg px-3 py-2">
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${m === "GET" ? "bg-green-900 text-green-300" : "bg-blue-900 text-blue-300"}`}>{m}</span>
              <span className="text-slate-300 flex-1">{p}</span>
              <span className="text-slate-500">{d}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Tokens ─────────────────────────────────────────────────────────────────────
function Tokens() {
  const { data: tokens, loading, refetch } = useApi<Token[]>(`${API}/admin/tokens`, 0);
  const [v10, setV10] = useState("");
  const [v11, setV11] = useState("");
  const [adding, setAdding] = useState(false);
  const [msg, setMsg] = useState("");

  async function addToken() {
    if (!v10.trim()) return;
    setAdding(true); setMsg("");
    try {
      const r = await fetch(`${API}/admin/tokens`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Password": pw() },
        body: JSON.stringify({ token: v10.trim(), token_v11: v11.trim() || undefined }),
      });
      const d = await r.json();
      if (r.ok) { setMsg("✅ Token added!"); setV10(""); setV11(""); refetch(); }
      else setMsg(`❌ ${d.detail || "Error"}`);
    } catch (e) { setMsg("❌ Network error"); }
    finally { setAdding(false); }
  }

  async function toggleToken(id: string) {
    await fetch(`${API}/admin/tokens/${id}/toggle`, { method: "PATCH", headers: { "X-Admin-Password": pw() } });
    refetch();
  }

  async function deleteToken(id: string) {
    if (!confirm("Delete this token?")) return;
    await fetch(`${API}/admin/tokens/${id}`, { method: "DELETE", headers: { "X-Admin-Password": pw() } });
    refetch();
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Arena Tokens</h2>
        <p className="text-slate-400 text-sm mt-1">Your <code className="bg-slate-700 px-1 rounded text-slate-300">arena-auth-prod-v1.0</code> cookie values from arena.ai</p>
      </div>

      {/* How to get */}
      <div className="bg-blue-900/20 border border-blue-800 rounded-2xl p-5">
        <h3 className="text-blue-300 font-semibold mb-2">How to get your token</h3>
        <ol className="space-y-1 text-sm text-blue-200/80">
          <li>1. Open <strong>arena.ai</strong> and log in</li>
          <li>2. Press <strong>F12</strong> → <strong>Application</strong> tab → <strong>Cookies</strong> → <strong>arena.ai</strong></li>
          <li>3. Copy the value of <code className="bg-blue-900 px-1 rounded">arena-auth-prod-v1.0</code> (starts with <code className="bg-blue-900 px-1 rounded">base64-</code>)</li>
          <li>4. Optionally copy <code className="bg-blue-900 px-1 rounded">arena-auth-prod-v1.1</code> too</li>
        </ol>
      </div>

      {/* Add form */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5 space-y-4">
        <h3 className="text-white font-semibold">Add Token</h3>
        <div>
          <label className="text-sm text-slate-400 mb-1 block">arena-auth-prod-v1.0 <span className="text-red-400">*</span></label>
          <input value={v10} onChange={e => setV10(e.target.value)}
            placeholder="base64-eyJhY2Nlc3NfdG9rZW4i..."
            className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-violet-500 font-mono text-xs"
          />
        </div>
        <div>
          <label className="text-sm text-slate-400 mb-1 block">arena-auth-prod-v1.1 <span className="text-slate-500">(optional but recommended)</span></label>
          <input value={v11} onChange={e => setV11(e.target.value)}
            placeholder="mlkZXIiOiJlbWFpbCI..."
            className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-violet-500 font-mono text-xs"
          />
        </div>
        {msg && <p className={`text-sm px-3 py-2 rounded-lg ${msg.startsWith("✅") ? "bg-green-900/20 text-green-300" : "bg-red-900/20 text-red-300"}`}>{msg}</p>}
        <button onClick={addToken} disabled={adding || !v10.trim()}
          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-xl px-6 py-2.5 text-sm font-medium transition-colors">
          {adding ? "Adding..." : "Add Token"}
        </button>
      </div>

      {/* List */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white font-semibold">Configured Tokens ({tokens?.length ?? 0})</h3>
          <button onClick={refetch} className="text-slate-400 hover:text-white text-sm transition-colors">↻ Refresh</button>
        </div>
        {loading ? (
          <div className="text-slate-500 text-sm text-center py-4">Loading...</div>
        ) : !tokens?.length ? (
          <div className="text-slate-500 text-sm text-center py-8">No tokens yet. Add one above.</div>
        ) : (
          <div className="space-y-3">
            {tokens.map(t => (
              <div key={t.id} className="flex items-center gap-3 bg-slate-700/50 rounded-xl px-4 py-3">
                <div className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${t.active ? "bg-green-400" : "bg-slate-500"}`} />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs text-slate-300 truncate">{t.preview}</div>
                  <div className="text-slate-500 text-xs mt-0.5">{new Date(t.added_at).toLocaleString()}</div>
                </div>
                <button onClick={() => toggleToken(t.id)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${t.active ? "bg-green-900/30 text-green-400 hover:bg-green-900/50" : "bg-slate-600 text-slate-400 hover:bg-slate-500"}`}>
                  {t.active ? "Active" : "Disabled"}
                </button>
                <button onClick={() => deleteToken(t.id)}
                  className="text-slate-500 hover:text-red-400 transition-colors text-sm px-2">✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── API Keys ───────────────────────────────────────────────────────────────────
function ApiKeys() {
  const { data: keys, loading, refetch } = useApi<ApiKey[]>(`${API}/admin/api-keys`, 0);
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const [copied, setCopied] = useState("");

  async function addKey() {
    setAdding(true);
    const r = await fetch(`${API}/admin/api-keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Password": pw() },
      body: JSON.stringify({ label: label || "My Key" }),
    });
    if (r.ok) { setLabel(""); refetch(); }
    setAdding(false);
  }

  async function deleteKey(id: string) {
    if (!confirm("Delete this API key?")) return;
    await fetch(`${API}/admin/api-keys/${id}`, { method: "DELETE", headers: { "X-Admin-Password": pw() } });
    refetch();
  }

  function copyKey(key: string) {
    navigator.clipboard.writeText(key);
    setCopied(key);
    setTimeout(() => setCopied(""), 2000);
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">API Keys</h2>
        <p className="text-slate-400 text-sm mt-1">Keys for accessing the bridge from Open WebUI, curl, SDKs</p>
      </div>
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5 flex gap-3">
        <input value={label} onChange={e => setLabel(e.target.value)}
          placeholder="Key label (e.g. Open WebUI)"
          className="flex-1 bg-slate-700 border border-slate-600 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-violet-500 text-sm"
        />
        <button onClick={addKey} disabled={adding}
          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-xl px-5 py-2.5 text-sm font-medium transition-colors">
          {adding ? "..." : "Generate"}
        </button>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-4">Keys ({keys?.length ?? 0})</h3>
        {loading ? <div className="text-slate-500 text-sm text-center py-4">Loading...</div>
          : !keys?.length ? <div className="text-slate-500 text-sm text-center py-8">No API keys yet.</div>
          : (
            <div className="space-y-3">
              {keys.map(k => (
                <div key={k.id} className="flex items-center gap-3 bg-slate-700/50 rounded-xl px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white font-medium">{k.label}</div>
                    <div className="font-mono text-xs text-slate-400 truncate mt-0.5">{k.key}</div>
                  </div>
                  <button onClick={() => copyKey(k.key)}
                    className="text-slate-400 hover:text-white text-xs px-3 py-1.5 bg-slate-600 rounded-lg transition-colors">
                    {copied === k.key ? "Copied!" : "Copy"}
                  </button>
                  <button onClick={() => deleteKey(k.id)}
                    className="text-slate-500 hover:text-red-400 transition-colors px-2">✕</button>
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}

// ── Integration ────────────────────────────────────────────────────────────────
function Integration() {
  const [copied, setCopied] = useState("");
  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text);
    setCopied(key); setTimeout(() => setCopied(""), 2000);
  }

  const userscriptUrl = `${API}/userscript`;

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Integration Guide</h2>
        <p className="text-slate-400 text-sm mt-1">Connect Open WebUI, curl, or any OpenAI SDK</p>
      </div>

      {/* Userscript */}
      <div className="bg-slate-800 border border-violet-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">🦊 Step 1 — Install Tampermonkey Userscript</h3>
        <ol className="space-y-2 text-sm text-slate-300 mb-4">
          <li>1. Install <strong>Tampermonkey</strong> from <a href="https://tampermonkey.net" target="_blank" className="text-violet-400 underline">tampermonkey.net</a></li>
          <li>2. Click the button below to install the userscript</li>
          <li>3. Go to <strong>arena.ai</strong> and send one message — badge turns 🟢</li>
        </ol>
        <a href={userscriptUrl} target="_blank"
          className="inline-block bg-violet-600 hover:bg-violet-500 text-white rounded-xl px-5 py-2.5 text-sm font-medium transition-colors">
          📥 Install Userscript
        </a>
        <p className="text-slate-500 text-xs mt-2">Or manually copy from: <code className="text-slate-400">bridge/userscript/arena-bridge.user.js</code></p>
      </div>

      {/* Open WebUI */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">Open WebUI</h3>
        <p className="text-slate-400 text-sm mb-3">Profile → Admin Panel → Settings → Connections → OpenAI → set URL to:</p>
        <div className="flex items-center gap-2 bg-slate-700 rounded-xl px-4 py-3">
          <code className="text-violet-300 flex-1 text-sm">http://localhost:8000/api/v1</code>
          <button onClick={() => copy("http://localhost:8000/api/v1", "owui")} className="text-slate-400 hover:text-white text-xs">{copied === "owui" ? "✓" : "Copy"}</button>
        </div>
        <p className="text-slate-500 text-xs mt-2">API Key can be anything (or use a key from API Keys page)</p>
      </div>

      {/* curl */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">curl</h3>
        <div className="relative">
          <pre className="bg-slate-900 rounded-xl p-4 text-xs text-slate-300 overflow-x-auto">{`curl http://localhost:8000/api/v1/chat/completions \\
  -H "Authorization: Bearer any-key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-opus-4-5-20251101",
    "messages": [{"role":"user","content":"Hello!"}],
    "stream": true
  }'`}</pre>
          <button onClick={() => copy(`curl http://localhost:8000/api/v1/chat/completions -H "Authorization: Bearer any-key" -H "Content-Type: application/json" -d '{"model":"claude-opus-4-5-20251101","messages":[{"role":"user","content":"Hello!"}],"stream":true}'`, "curl")}
            className="absolute top-3 right-3 text-slate-500 hover:text-white text-xs px-2 py-1 bg-slate-700 rounded">
            {copied === "curl" ? "✓" : "Copy"}
          </button>
        </div>
      </div>

      {/* Python */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">Python SDK</h3>
        <div className="relative">
          <pre className="bg-slate-900 rounded-xl p-4 text-xs text-slate-300 overflow-x-auto">{`from openai import OpenAI

client = OpenAI(
    api_key="any-key",
    base_url="http://localhost:8000/api/v1"
)

response = client.chat.completions.create(
    model="claude-opus-4-5-20251101",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")`}</pre>
        </div>
      </div>
    </div>
  );
}

// ── Settings ───────────────────────────────────────────────────────────────────
function Settings() {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [msg, setMsg] = useState("");

  async function changePw() {
    if (!newPw) return;
    const r = await fetch(`${API}/admin/change-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Password": oldPw },
      body: JSON.stringify({ new_password: newPw }),
    });
    if (r.ok) { setMsg("✅ Password changed! Please log in again."); sessionStorage.removeItem("pw"); setTimeout(() => window.location.reload(), 2000); }
    else setMsg("❌ Wrong current password");
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Settings</h2>
        <p className="text-slate-400 text-sm mt-1">Bridge configuration</p>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5 space-y-4">
        <h3 className="text-white font-semibold">Change Password</h3>
        <input value={oldPw} onChange={e => setOldPw(e.target.value)} type="password" placeholder="Current password"
          className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-violet-500" />
        <input value={newPw} onChange={e => setNewPw(e.target.value)} type="password" placeholder="New password"
          className="w-full bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-violet-500" />
        {msg && <p className={`text-sm px-3 py-2 rounded-lg ${msg.startsWith("✅") ? "bg-green-900/20 text-green-300" : "bg-red-900/20 text-red-300"}`}>{msg}</p>}
        <button onClick={changePw} className="bg-violet-600 hover:bg-violet-500 text-white rounded-xl px-6 py-2.5 text-sm font-medium transition-colors">
          Change Password
        </button>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-white font-semibold mb-3">Bridge Info</h3>
        <div className="space-y-2 text-sm">
          {[
            ["API Base URL", "http://localhost:8000/api/v1"],
            ["Dashboard", "http://localhost:8000/dashboard"],
            ["WebSocket", "ws://127.0.0.1:7823"],
            ["Models", "From arena.ai (via userscript)"],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
              <span className="text-slate-400">{k}</span>
              <span className="text-slate-300 font-mono text-xs">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── App ────────────────────────────────────────────────────────────────────────
export function App() {
  const [authed, setAuthed] = useState(() => !!sessionStorage.getItem("pw"));
  const [page, setPage] = useState<Page>("overview");
  const { data: status, refetch: refetchStatus } = useApi<Status>(`${API}/admin/status`, authed);

  if (!authed) return <Login onLogin={() => setAuthed(true)} />;

  return (
    <div className="flex h-screen bg-slate-900 text-white overflow-hidden">
      <Sidebar page={page} setPage={setPage} status={status} />
      <main className="flex-1 overflow-y-auto">
        {page === "overview" && <Overview status={status} refetch={refetchStatus} />}
        {page === "tokens" && <Tokens />}
        {page === "apikeys" && <ApiKeys />}
        {page === "integration" && <Integration />}
        {page === "settings" && <Settings />}
      </main>
    </div>
  );
}
