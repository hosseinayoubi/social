"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, setToken } from "@/components/api";
import { Card, Button, Input } from "@/components/ui";

export default function LoginPage() {
  const r = useRouter();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("admin1234");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const res = await apiFetch<{ token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(res.token);
      r.push("/dashboard");
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <Card title="Sign in">
          <p className="text-sm text-gray-600 mb-4">
            Default admin: <span className="font-mono">admin@example.com</span> / <span className="font-mono">admin1234</span>
          </p>
          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label className="text-sm font-medium">Email</label>
              <Input value={email} onChange={(e)=>setEmail(e.target.value)} placeholder="you@example.com" />
            </div>
            <div>
              <label className="text-sm font-medium">Password</label>
              <Input type="password" value={password} onChange={(e)=>setPassword(e.target.value)} />
            </div>
            {err ? <div className="text-sm text-red-600 whitespace-pre-wrap">{err}</div> : null}
            <Button disabled={loading} className="w-full">{loading ? "Signing in..." : "Sign in"}</Button>
          </form>
        </Card>
        <p className="text-xs text-gray-500 mt-4">
          Tip: set <span className="font-mono">NEXT_PUBLIC_API_URL</span> in <span className="font-mono">.env.local</span>.
        </p>
      </div>
    </div>
  );
}
