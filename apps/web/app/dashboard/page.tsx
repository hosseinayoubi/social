"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, clearToken } from "@/components/api";
import { Badge, Button, Card, Input, Select } from "@/components/ui";

type Config = { approval_required: boolean; interval_days: number; max_candidates: number; pick_top_n: number; };
type Source = { id: number; platform: "instagram"|"facebook"; handle: string; enabled: boolean; created_at: string; };
type Gen = { title_en: string; caption_en: string; hashtags_en: string[]; };
type Candidate = {
  id: number;
  platform: "instagram"|"facebook";
  original_url: string;
  caption_raw?: string | null;
  media_type: string;
  media_url?: string | null;
  posted_at_source?: string | null;
  engagement_score: number;
  status: string;
  created_at: string;
  generated?: Gen | null;
};
type Stats = { total_candidates: number; total_published: number; pending_approval: number; last_run_at?: string|null; };
type LogEvent = { id: number; level: string; message: string; job_id?: number|null; created_at: string; };

function fmtDate(s?: string|null) {
  if (!s) return "—";
  const d = new Date(s);
  return d.toLocaleString();
}

export default function DashboardPage() {
  const r = useRouter();
  const [tab, setTab] = useState<"overview"|"config"|"sources"|"queue"|"logs">("overview");

  const [me, setMe] = useState<{email:string; workspace_name:string} | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [posts, setPosts] = useState<Candidate[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [logs, setLogs] = useState<LogEvent[]>([]);

  const [runAuto, setRunAuto] = useState<boolean>(false);
  const [runLoading, setRunLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const pending = useMemo(() => posts.filter(p => p.status === "awaiting_approval"), [posts]);

  async function loadAll() {
    setErr(null);
    try {
      const m = await apiFetch<any>("/me");
      setMe({ email: m.email, workspace_name: m.workspace_name });
      const [c, s, st, l, p] = await Promise.all([
        apiFetch<Config>("/api/config"),
        apiFetch<Source[]>("/api/sources"),
        apiFetch<Stats>("/api/stats"),
        apiFetch<LogEvent[]>("/api/logs"),
        apiFetch<Candidate[]>("/api/posts"),
      ]);
      setCfg(c); setSources(s); setStats(st); setLogs(l); setPosts(p);
      setRunAuto(!c.approval_required);
    } catch (e:any) {
      setErr(String(e?.message || e));
      clearToken();
      r.replace("/login");
    }
  }

  useEffect(() => { loadAll(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll logs & posts (free-friendly, works across processes)
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const [l, p, st] = await Promise.all([
          apiFetch<LogEvent[]>("/api/logs"),
          apiFetch<Candidate[]>("/api/posts"),
          apiFetch<Stats>("/api/stats"),
        ]);
        setLogs(l); setPosts(p); setStats(st);
      } catch {}
    }, 4000);
    return () => clearInterval(t);
  }, []);

  async function saveConfig() {
    if (!cfg) return;
    setErr(null);
    try {
      const saved = await apiFetch<Config>("/api/config", { method: "POST", body: JSON.stringify(cfg) });
      setCfg(saved);
      setRunAuto(!saved.approval_required);
    } catch (e:any) { setErr(String(e?.message || e)); }
  }

  const [newPlatform, setNewPlatform] = useState<"instagram"|"facebook">("instagram");
  const [newHandle, setNewHandle] = useState("");
  async function addSource() {
    setErr(null);
    try {
      await apiFetch<Source>("/api/sources", { method:"POST", body: JSON.stringify({ platform: newPlatform, handle: newHandle, enabled: true }) });
      setNewHandle("");
      const s = await apiFetch<Source[]>("/api/sources");
      setSources(s);
    } catch (e:any) { setErr(String(e?.message || e)); }
  }

  async function runNow() {
    setErr(null);
    setRunLoading(true);
    try {
      await apiFetch<{enqueued_job_id:number}>("/api/run", { method:"POST", body: JSON.stringify({ auto_publish: runAuto }) });
      setTab("logs");
    } catch (e:any) { setErr(String(e?.message || e)); }
    finally { setRunLoading(false); }
  }

  async function approve(id: number) {
    setErr(null);
    try {
      await apiFetch("/api/posts/"+id+"/approve", { method:"POST", body: JSON.stringify({}) });
      const p = await apiFetch<Candidate[]>("/api/posts");
      setPosts(p);
    } catch (e:any) { setErr(String(e?.message || e)); }
  }

  async function clearLogs() {
    await apiFetch("/api/logs/clear", { method:"POST", body: JSON.stringify({}) });
    const l = await apiFetch<LogEvent[]>("/api/logs");
    setLogs(l);
  }

  function logout() {
    clearToken();
    r.replace("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-5 py-4 flex items-center justify-between gap-4">
          <div>
            <div className="text-xl font-semibold">Social SaaS Dashboard</div>
            <div className="text-xs text-gray-500">
              {me ? `${me.workspace_name} • ${me.email}` : "Loading..."}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={logout}>Log out</Button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-5 py-6 space-y-5">
        {err ? <Card><div className="text-sm text-red-700 whitespace-pre-wrap">{err}</div></Card> : null}

        <div className="flex flex-wrap gap-2">
          {(["overview","config","sources","queue","logs"] as const).map(t => (
            <Button key={t} variant={tab===t ? "primary" : "ghost"} onClick={()=>setTab(t)}>
              {t[0].toUpperCase()+t.slice(1)}
            </Button>
          ))}
        </div>

        {tab === "overview" ? (
          <div className="grid md:grid-cols-4 gap-4">
            <Card title="Candidates">{stats ? <div className="text-3xl font-semibold">{stats.total_candidates}</div> : "—"}</Card>
            <Card title="Published">{stats ? <div className="text-3xl font-semibold">{stats.total_published}</div> : "—"}</Card>
            <Card title="Pending approval">{stats ? <div className="text-3xl font-semibold">{stats.pending_approval}</div> : "—"}</Card>
            <Card title="Last run">{stats ? <div className="text-sm">{fmtDate(stats.last_run_at || null)}</div> : "—"}</Card>

            <Card title="Run pipeline">
              <div className="text-sm text-gray-600 mb-3">
                Choose manual approval or full auto for *this run*.
              </div>
              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="text-sm font-medium">Mode</div>
                <Select value={runAuto ? "auto" : "manual"} onChange={(e)=>setRunAuto(e.target.value==="auto")}>
                  <option value="manual">Manual approval</option>
                  <option value="auto">Fully automatic</option>
                </Select>
              </div>
              <Button disabled={runLoading} onClick={runNow} className="w-full">
                {runLoading ? "Enqueuing..." : "Run now"}
              </Button>
              <div className="text-xs text-gray-500 mt-3">
                Tip: GitHub Actions can call the tick endpoint hourly to process queued jobs.
              </div>
            </Card>

            <Card title="Manual approvals">
              <div className="text-sm text-gray-600 mb-3">
                {pending.length ? `You have ${pending.length} posts waiting.` : "No pending approvals."}
              </div>
              <Button variant="ghost" onClick={()=>setTab("queue")} className="w-full">Go to queue</Button>
            </Card>
          </div>
        ) : null}

        {tab === "config" && cfg ? (
          <Card title="Settings">
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium">Approval required</label>
                <Select value={cfg.approval_required ? "yes" : "no"} onChange={(e)=>setCfg({...cfg, approval_required: e.target.value==="yes"})}>
                  <option value="yes">Yes (manual approve)</option>
                  <option value="no">No (fully auto)</option>
                </Select>
                <p className="text-xs text-gray-500 mt-1">This is the default mode. You can override per-run in Overview.</p>
              </div>
              <div>
                <label className="text-sm font-medium">Interval (days)</label>
                <Input type="number" value={cfg.interval_days} onChange={(e)=>setCfg({...cfg, interval_days: Number(e.target.value)})} />
              </div>
              <div>
                <label className="text-sm font-medium">Max candidates per source</label>
                <Input type="number" value={cfg.max_candidates} onChange={(e)=>setCfg({...cfg, max_candidates: Number(e.target.value)})} />
              </div>
              <div>
                <label className="text-sm font-medium">Pick top N</label>
                <Input type="number" value={cfg.pick_top_n} onChange={(e)=>setCfg({...cfg, pick_top_n: Number(e.target.value)})} />
              </div>
            </div>
            <div className="mt-5 flex justify-end">
              <Button onClick={saveConfig}>Save settings</Button>
            </div>
          </Card>
        ) : null}

        {tab === "sources" ? (
          <Card title="Source pages">
            <div className="grid md:grid-cols-3 gap-3 mb-4">
              <div>
                <label className="text-sm font-medium">Platform</label>
                <Select value={newPlatform} onChange={(e)=>setNewPlatform(e.target.value as any)}>
                  <option value="instagram">Instagram</option>
                  <option value="facebook">Facebook</option>
                </Select>
              </div>
              <div className="md:col-span-2">
                <label className="text-sm font-medium">Handle / Page name</label>
                <Input value={newHandle} onChange={(e)=>setNewHandle(e.target.value)} placeholder="e.g. natgeo or Page Name" />
              </div>
            </div>
            <Button onClick={addSource} disabled={!newHandle.trim()}>Add source</Button>

            <div className="mt-5 space-y-2">
              {sources.length === 0 ? <div className="text-sm text-gray-500">No sources yet.</div> : null}
              {sources.map(s => (
                <div key={s.id} className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 p-3 bg-gray-50">
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{s.handle}</div>
                    <div className="text-xs text-gray-500">{s.platform} • {fmtDate(s.created_at)}</div>
                  </div>
                  <Badge>{s.enabled ? "enabled" : "disabled"}</Badge>
                </div>
              ))}
            </div>
          </Card>
        ) : null}

        {tab === "queue" ? (
          <Card title="Queue / Candidates">
            <div className="text-sm text-gray-600 mb-4">
              Posts move through statuses: <span className="font-mono">new → selected → generated → awaiting_approval/approved → published</span>.
            </div>
            <div className="space-y-3">
              {posts.length === 0 ? <div className="text-sm text-gray-500">No posts yet. Add sources and run the pipeline.</div> : null}
              {posts.map(p => (
                <div key={p.id} className="rounded-2xl border border-gray-200 bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge>{p.platform}</Badge>
                      <Badge>{p.media_type}</Badge>
                      <Badge>{p.status}</Badge>
                      <Badge>score: {p.engagement_score}</Badge>
                    </div>
                    {p.status === "awaiting_approval" ? (
                      <Button onClick={()=>approve(p.id)}>Approve & publish</Button>
                    ) : null}
                  </div>

                  <div className="mt-2 text-xs text-gray-500">
                    Created: {fmtDate(p.created_at)} • Source URL: <a className="underline" href={p.original_url} target="_blank">open</a>
                  </div>

                  {p.generated ? (
                    <div className="mt-3 rounded-xl bg-gray-50 border border-gray-200 p-3">
                      <div className="text-sm font-semibold">{p.generated.title_en}</div>
                      <div className="text-sm text-gray-700 mt-2 whitespace-pre-wrap">{p.generated.caption_en}</div>
                      <div className="text-xs text-gray-600 mt-2">{p.generated.hashtags_en.join(" ")}</div>
                    </div>
                  ) : (
                    <div className="mt-3 text-sm text-gray-500">No generated content yet.</div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        ) : null}

        {tab === "logs" ? (
          <Card title="Logs">
            <div className="flex justify-end mb-3">
              <Button variant="danger" onClick={clearLogs}>Clear logs</Button>
            </div>
            <div className="space-y-2">
              {logs.length === 0 ? <div className="text-sm text-gray-500">No logs yet.</div> : null}
              {logs.map(l => (
                <div key={l.id} className="rounded-xl border border-gray-200 p-3 bg-white">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs text-gray-500">{fmtDate(l.created_at)} {l.job_id ? `• job ${l.job_id}` : ""}</div>
                    <Badge>{l.level}</Badge>
                  </div>
                  <div className="text-sm mt-1 whitespace-pre-wrap">{l.message}</div>
                </div>
              ))}
            </div>
          </Card>
        ) : null}
      </main>
    </div>
  );
}
