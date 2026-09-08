import type { Asset, Checkpoint, DemoCase, Persona, Run, RunResult } from "../types";

const API = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? payload.message ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  personas: () => request<Persona[]>("/api/personas"),
  cases: () => request<DemoCase[]>("/api/demo-cases"),
  assets: (persona: string) => request<Asset[]>(`/api/personas/${persona}/assets`),
  createSession: (persona_id: string) =>
    request<{ id: string }>("/api/sessions", { method: "POST", body: JSON.stringify({ persona_id }) }),
  createRun: (body: Record<string, unknown>) =>
    request<Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  result: (id: string) => request<RunResult>(`/api/runs/${id}/result`),
  history: (persona: string) => request<Run[]>(`/api/personas/${persona}/history`),
  adminRuns: () => request<Run[]>("/api/admin/runs"),
  checkpoints: (id: string) => request<Checkpoint[]>(`/api/admin/runs/${id}/checkpoints`),
  benchmark: () => request<Record<string, unknown>>("/api/admin/benchmarks/latest"),
  eventsUrl: (id: string) => `${API}/api/runs/${id}/events`,
};

