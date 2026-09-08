import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AnalysisDashboard } from "./AnalysisDashboard";
import type { Run, RunResult } from "../types";

const run: Run = {
  id: "run_12345678",
  session_id: "ses_1",
  persona_id: "lucas",
  user_id: "usr_lucas",
  asset_id: "asset_B204",
  case_id: "case_1",
  message: "Investigue o espectro do ativo.",
  additional_context: null,
  investigation_key: "case_1",
  revision: 1,
  parent_run_id: null,
  reused: false,
  seed: "complete",
  gate_enabled: true,
  status: "completed",
  modality: "investigar",
  decision: "orientar",
  current_stage: "completed",
  error: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:01Z",
};

const result: RunResult = {
  run_id: run.id,
  thread_id: "thread_1",
  status: "completed",
  modality: "investigar",
  decision: "orientar",
  response: {
    summary: "O ativo precisa de acompanhamento, sem intervenção imediata.",
    explanation: ["O espectro foi consultado e não indicou uma condição crítica."],
    next_steps: [],
    limitations: [],
  },
  evidence: [],
  gaps: [],
  gates: [
    {
      gate: "sufficiency",
      passed: true,
      enabled: true,
      reasons: ["Evidência suficiente."],
      missing: [],
    },
  ],
  runtime_verdict: {
    verdict: "approve",
    judge: "deterministic_fallback",
    safe: true,
    grounded: true,
    complete: true,
    reasons: ["O dossiê está fundamentado."],
    advisory_objections: [
      {
        kind: "unsupported_claim",
        detail: "A afirmação livre foi substituída por uma síntese conservadora.",
      },
    ],
  },
  actions: [],
  recommendations: [],
  investigation: {
    conclusion: "O espectro não indicou uma condição crítica.",
    evidence_ids: [],
    hypotheses: [],
    unknowns: [],
    needs_human: false,
  },
  agent_events: [
    { role: "classifier", model: "granite-small", status: "completed", latency_ms: 15, summary: "Caso classificado.", error: null, created_at: "2026-09-01T00:00:00Z" },
    { role: "investigator", model: "qwen-strong", status: "completed", latency_ms: 150, summary: "Relatório consolidado.", error: null, created_at: "2026-09-01T00:00:00Z" },
    { role: "judge", model: "qwen-strong", status: "fallback", latency_ms: 90, summary: "Revisão conservadora local utilizada.", error: null, created_at: "2026-09-01T00:00:00Z" },
    { role: "writer", model: "granite-writer", status: "completed", latency_ms: 60, summary: "Resposta preparada.", error: null, created_at: "2026-09-01T00:00:00Z" },
  ],
  metrics: { tool_calls: 1, duration_ms: 5, degraded_reads: 0, conflicts: 0, mutations_attempted: 0 },
};

const personas = [{ id: "lucas", user_id: "usr_lucas", name: "Lucas", role: "Mecânico", company_id: "comp", company_name: "Empresa" }];
const cases = [{ id: "case_1", ticket_id: "TKT-1", company_id: "comp", user_id: "usr_lucas", asset_id: "asset_B204", message: run.message }];

function jsonResponse(payload: unknown) {
  return { ok: true, json: async () => payload } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("troca o contexto do ativo e envia o caso selecionado com a nova revisão", async () => {
  const secondCase = { ...cases[0], id: "case_2", ticket_id: "TKT-2", asset_id: "asset_M300", message: "Motor com vibração após a manutenção." };
  let submitted: Record<string, unknown> | undefined;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/api/personas/lucas/assets")) return jsonResponse([
      { id: "asset_B204", name: "Bomba de alimentação", criticality: "high", machine_type: "pump", sensor_status: "online" },
      { id: "asset_M300", name: "Motor principal", criticality: "high", machine_type: "motor", sensor_status: "offline" },
    ]);
    if (path.endsWith("/api/admin/runs")) return jsonResponse([]);
    if (path.endsWith("/api/admin/benchmarks/latest")) return jsonResponse({ status: "not_run" });
    if (path.endsWith("/api/sessions")) return jsonResponse({ id: "session_new" });
    if (path.endsWith("/api/runs") && init?.method === "POST") {
      submitted = JSON.parse(String(init.body));
      return jsonResponse({ ...run, case_id: secondCase.id, asset_id: secondCase.asset_id, message: secondCase.message });
    }
    if (path.endsWith("/checkpoints")) return jsonResponse([]);
    if (path.endsWith("/result")) return jsonResponse(result);
    throw new Error(`Requisição não prevista: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AnalysisDashboard personas={personas} cases={[...cases, secondCase]} />);
  expect(await screen.findByText("Bomba de alimentação")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Caso de investigação" }), { target: { value: secondCase.id } });
  expect(await screen.findByText("Motor principal")).toBeInTheDocument();
  expect(screen.getByText("Sem conexão")).toBeInTheDocument();
  expect(screen.queryByText("Bomba de alimentação")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: /Contexto adicional/ }), { target: { value: "  Nova coleta disponível.  " } });
  fireEvent.click(screen.getByRole("button", { name: "Iniciar análise" }));
  await waitFor(() => expect(submitted).toMatchObject({ case_id: secondCase.id, asset_id: secondCase.asset_id, message: secondCase.message, additional_context: "Nova coleta disponível.", persona_id: "lucas" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: /Contexto adicional/ })).toHaveValue(""));
});

test("inspeciona investigação, juiz, prévia e detalhes técnicos", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/api/admin/runs")) return jsonResponse([run]);
      if (path.endsWith("/api/admin/benchmarks/latest")) {
        return jsonResponse({
          status: "completed",
          summary: {
            gate_on: {
              cases: 17,
              objective_score: 1,
              decision_accuracy: 1,
              runtime_bad_releases: 0,
            },
          },
        });
      }
      if (path.endsWith(`/api/admin/runs/${run.id}/checkpoints`)) {
        return jsonResponse([
          {
            id: 1,
            node: "reviewer",
            created_at: "2026-09-01T00:00:01Z",
            state: {
              tool_events: [
                {
                  id: "tool_1",
                  method: "GET",
                  path: "/assets/asset_B204/spectrum",
                  latency_ms: 12,
                  envelope: { mode: "complete" },
                  error: null,
                },
              ],
            },
          },
        ]);
      }
      if (path.endsWith(`/api/runs/${run.id}/result`)) return jsonResponse(result);
      throw new Error(`Requisição não prevista: ${path}`);
    }),
  );

  render(<AnalysisDashboard personas={personas} cases={cases} />);
  fireEvent.click(await screen.findByText("12345678"));

  const evidenceSources = within(screen.getByRole("region", { name: "Evidências e fontes" }));
  expect(await evidenceSources.findByText("/assets/asset_B204/spectrum")).toBeInTheDocument();
  expect(screen.queryByText(result.response!.summary)).not.toBeInTheDocument();
  expect(screen.queryByText(result.response!.explanation[0])).not.toBeInTheDocument();
  expect(screen.getByText("Relatório da investigação")).toBeInTheDocument();
  expect(screen.getByText("Parecer do juiz")).toBeInTheDocument();
  expect(screen.getByText("Objeções consultivas registradas")).toBeInTheDocument();
  expect(screen.getByText("A afirmação livre foi substituída por uma síntese conservadora.")).toBeInTheDocument();
  expect(screen.getByText("O relatório está fundamentado.")).toBeInTheDocument();
  expect(screen.queryByText("O dossiê está fundamentado.")).not.toBeInTheDocument();
  expect(screen.getByText("O que cada agente entregou")).toBeInTheDocument();
  expect(screen.getByText("Resultado do investigador")).toBeInTheDocument();
  expect(screen.queryByText("Confiança do relatório")).not.toBeInTheDocument();
  expect(screen.getByText("Evidências rastreadas")).toBeInTheDocument();
  expect(screen.queryByText("Como a resposta seria apresentada")).not.toBeInTheDocument();
  expect(screen.getByText("qwen-strong")).toBeInTheDocument();
  expect(screen.getByText("Mutações")).toBeInTheDocument();
  expect(screen.getByText("17 casos avaliados")).toBeInTheDocument();
  expect(screen.getByText("Qualidade do sistema")).toBeInTheDocument();
  expect(screen.getByText("Detalhes técnicos").closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText("Ver consultas e checkpoints técnicos")).toBeInTheDocument();
});

test("atualiza os agentes conforme cada checkpoint chega por SSE", async () => {
  const running = { ...run, status: "running" as const, decision: null, current_stage: "starting" };

  class FakeEventSource extends EventTarget {
    static latest: FakeEventSource | null = null;
    close = vi.fn();

    constructor(public url: string) {
      super();
      FakeEventSource.latest = this;
    }

    emit(type: string, payload: unknown) {
      this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(payload) }));
    }
  }

  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/api/admin/runs")) return jsonResponse([running]);
      if (path.endsWith("/api/admin/benchmarks/latest")) {
        return jsonResponse({ status: "not_run", message: "Sem benchmark." });
      }
      if (path.endsWith(`/api/admin/runs/${running.id}/checkpoints`)) {
        return jsonResponse([]);
      }
      throw new Error(`Requisição não prevista: ${path}`);
    }),
  );

  render(<AnalysisDashboard personas={personas} cases={cases} />);
  fireEvent.click(await screen.findByText("12345678"));
  await waitFor(() => expect(FakeEventSource.latest).not.toBeNull());

  act(() => {
    FakeEventSource.latest?.emit("progress", {
      id: 1,
      run_id: running.id,
      node: "classifier",
      created_at: "2026-09-01T00:00:01Z",
      state: {
        current_stage: "classifier",
        tool_events: [],
        agent_events: [
          {
            role: "classifier",
            model: "granite-small",
            status: "completed",
            latency_ms: 120,
            summary: "Solicitação classificada.",
            error: null,
            created_at: "2026-09-01T00:00:01Z",
          },
        ],
      },
    });
  });

  expect((await screen.findAllByText("Solicitação classificada.")).length).toBeGreaterThan(0);
  const flow = within(screen.getByLabelText("Fluxo dos agentes"));
  expect(flow.getByText("Fontes").closest("article")).toHaveClass("active");
  expect(flow.getByText("Classificador").closest("article")).toHaveClass("visited");
  expect(flow.getByText("Classificador").closest("article")).toHaveTextContent("granite-small");

  act(() => {
    FakeEventSource.latest?.emit("progress", {
      id: 2,
      run_id: running.id,
      node: "source_select",
      created_at: "2026-09-01T00:00:02Z",
      state: {
        current_stage: "source_select",
        tool_events: [],
        source_plan: {
          tools: ["spectrum", "knowledge"],
          required_tools: ["knowledge"],
          knowledge_queries: ["falha elétrica"],
        },
        source_candidates: [
          { id: "kb_1", title: "Falhas elétricas", tags: [], snippet: "" },
        ],
        source_selection: {
          selected_sources: [{ id: "kb_1", reason: "Responde à dúvida elétrica." }],
          missing_information: [],
        },
        agent_events: [
          {
            role: "source_selector",
            model: "small-source",
            status: "completed",
            latency_ms: 140,
            summary: "Fontes selecionadas.",
            error: null,
            created_at: "2026-09-01T00:00:02Z",
          },
        ],
      },
    });
  });

  expect(await screen.findByText("Resultado do agente de fontes")).toBeInTheDocument();
  expect(screen.getByText("Falhas elétricas")).toBeInTheDocument();
  expect(flow.getByText("Investigador").closest("article")).toHaveClass("active");
});

test("substitui a prévia ao cliente por um repasse interno quando o juiz escala", async () => {
  const escalatedRun: Run = { ...run, decision: "escalar" };
  const escalatedResult: RunResult = {
    ...result,
    decision: "escalar",
    response: null,
    runtime_verdict: {
      verdict: "escalate",
      judge: "llm",
      safe: true,
      grounded: false,
      complete: false,
      reasons: ["A evidência disponível não sustenta uma resposta segura."],
    },
    agent_events: result.agent_events.filter((item) => item.role !== "writer"),
    escalation: {
      reason: "A evidência disponível não sustenta uma resposta segura.",
      ticket: run.message,
      user_id: run.user_id,
      asset_id: run.asset_id,
      recipient: "maintenance_engineer",
      customer_response_allowed: false,
      summary: "O caso precisa ser revisado por um engenheiro antes de responder ao cliente.",
      review_reasons: ["A evidência disponível não sustenta uma resposta segura."],
      findings: [
        {
          statement: "Existe um pico no espectro que precisa ser validado.",
          status: "open",
          evidence_ids: ["ev_1"],
        },
      ],
      open_questions: ["Qual é a causa física do pico?"],
      recommendations: [],
      executed: false,
    },
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/api/admin/runs")) return jsonResponse([escalatedRun]);
      if (path.endsWith("/api/admin/benchmarks/latest")) {
        return jsonResponse({ status: "not_run", message: "Sem benchmark." });
      }
      if (path.endsWith(`/api/admin/runs/${run.id}/checkpoints`)) return jsonResponse([]);
      if (path.endsWith(`/api/runs/${run.id}/result`)) return jsonResponse(escalatedResult);
      throw new Error(`Requisição não prevista: ${path}`);
    }),
  );

  render(<AnalysisDashboard personas={personas} cases={cases} />);
  fireEvent.click(await screen.findByText("12345678"));

  expect(await screen.findByText("Repasse para engenharia")).toBeInTheDocument();
  expect(screen.getByText("Não enviar ao cliente")).toBeInTheDocument();
  expect(screen.getByText("Qual é a causa física do pico?")).toBeInTheDocument();
  expect(screen.queryByText("Como a resposta seria apresentada")).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Fluxo dos agentes")).getByText("Redator").closest("article")).toHaveClass("skipped");
});

test("ignora resposta atrasada ao trocar rapidamente de análise", async () => {
  const firstRun = { ...run, id: "run_first111111", message: "Primeira análise" };
  const secondRun = { ...run, id: "run_second22222", message: "Segunda análise" };
  const secondResult = {
    ...result,
    run_id: secondRun.id,
    investigation: { ...result.investigation!, conclusion: "Resultado correto da segunda análise." },
  };
  let resolveFirst: ((value: Response) => void) | undefined;

  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/api/admin/runs")) return Promise.resolve(jsonResponse([firstRun, secondRun]));
      if (path.endsWith("/api/admin/benchmarks/latest")) {
        return Promise.resolve(jsonResponse({ status: "not_run", message: "Sem benchmark." }));
      }
      if (path.endsWith(`/api/admin/runs/${firstRun.id}/checkpoints`)) {
        return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      }
      if (path.endsWith(`/api/admin/runs/${secondRun.id}/checkpoints`)) {
        return Promise.resolve(jsonResponse([]));
      }
      if (path.endsWith(`/api/runs/${secondRun.id}/result`)) {
        return Promise.resolve(jsonResponse(secondResult));
      }
      throw new Error(`Requisição não prevista: ${path}`);
    }),
  );

  render(<AnalysisDashboard personas={personas} cases={cases} />);
  fireEvent.click(await screen.findByText("st111111"));
  await waitFor(() => expect(resolveFirst).toBeDefined());
  fireEvent.click(screen.getByText("ond22222"));
  expect(await screen.findByText("Resultado correto da segunda análise.")).toBeInTheDocument();

  await act(async () => {
    resolveFirst?.(jsonResponse([
      { id: 999, node: "reviewer", created_at: "2026-09-01", state: { tool_events: [{ path: "/stale" }] } },
    ]));
  });

  expect(screen.queryByText("/stale")).not.toBeInTheDocument();
  expect(screen.getByText("Resultado correto da segunda análise.")).toBeInTheDocument();
});

test("filtra o histórico e limpa o relatório ao selecionar outro caso", async () => {
  const failedRun = { ...run, id: "run_failed87654321", status: "failed", asset_id: "asset_F300", decision: null };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/api/admin/runs")) return jsonResponse([run, failedRun]);
    if (path.endsWith("/assets")) return jsonResponse([]);
    if (path.endsWith("/api/admin/benchmarks/latest")) return jsonResponse({ status: "not_run" });
    if (path.endsWith("/checkpoints")) return jsonResponse([]);
    if (path.endsWith("/result")) return jsonResponse(result);
    throw new Error(path);
  }));
  render(<AnalysisDashboard personas={personas} cases={[...cases, { ...cases[0], id: "case_other", ticket_id: "TKT-2", message: "Outro caso" }]} />);
  await screen.findByRole("button", { name: "12345678" });
  fireEvent.change(screen.getByLabelText("Filtrar histórico"), { target: { value: "failed" } });
  expect(screen.queryByRole("button", { name: "12345678" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "87654321" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Filtrar histórico"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("Buscar no histórico"), { target: { value: "B204" } });
  expect(screen.queryByRole("button", { name: "87654321" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "12345678" }));
  expect(await screen.findByText(result.investigation!.conclusion)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Caso de investigação"), { target: { value: "case_other" } });
  expect(screen.queryByText(result.investigation!.conclusion)).not.toBeInTheDocument();
  expect(screen.getByText("Análise não iniciada")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Iniciar análise" })).toBeEnabled();
});
