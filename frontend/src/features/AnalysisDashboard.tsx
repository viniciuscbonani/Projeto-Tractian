import { useEffect, useMemo, useRef, useState } from "react";
import { StatusPill } from "../components/StatusPill";
import { BrandIcon } from "../components/BrandIcon";
import { EvidenceSources, collectionWindow, formatCollection } from "../components/EvidenceSources";
import { api } from "../lib/api";
import type { Asset, Checkpoint, DemoCase, Persona, Run, RunResult } from "../types";

type UnknownRecord = Record<string, unknown>;

const AGENTS = [
  { key: "classifier", checkpoint: "classifier", label: "Classificador", detail: "Entende o tipo de solicitação" },
  { key: "source_selector", checkpoint: "source_select", label: "Fontes", detail: "Planeja consultas e escolhe documentos" },
  { key: "investigator", checkpoint: "investigator", label: "Investigador", detail: "Consolida as evidências no relatório técnico" },
  { key: "judge", checkpoint: "reviewer", label: "Juiz", detail: "Revisa evidências e incertezas" },
  { key: "writer", checkpoint: "writer", label: "Redator", detail: "Prepara a resposta apresentada" },
] as const;

const STATUS_LABELS: Record<string, string> = {
  approve: "Aprovado",
  revise_classification: "Revisar classificação",
  revise_sources: "Revisar fontes",
  revise_investigation: "Revisar investigação",
  escalate: "Revisão humana",
  completed: "Concluída",
  error: "Erro",
  escalar: "Revisão humana",
  failed: "Falhou",
  fallback: "Contingência",
  investigar: "Investigação",
  not_run: "Não executado",
  orientar: "Orientação",
  queued: "Na fila",
  recomendar: "Recomendação",
  reused: "Reaproveitado",
  running: "Em andamento",
  supported: "Sustentada",
  weakened: "Enfraquecida",
  open: "Em aberto",
  online: "Conectado",
  offline: "Sem conexão",
  degraded: "Sinal degradado",
};

const CHECKPOINT_LABELS: Record<string, string> = {
  classifier: "Classificação registrada",
  source_plan: "Plano de fontes registrado",
  source_collect: "Candidatos e dados coletados",
  source_select: "Fontes decisivas selecionadas",
  sufficiency_gate: "Suficiência das fontes verificada",
  investigator: "Relatório de investigação registrado",
  reviewer: "Parecer do juiz registrado",
  writer: "Resposta apresentada registrada",
  finalize: "Relatório concluído",
  failed: "Análise interrompida",
};

function asRecord(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function percentage(value: unknown): string {
  const score = numeric(value);
  return score === null ? "—" : `${(score * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

function statusLabel(value: string | null | undefined): string {
  if (!value) return "Não definido";
  return STATUS_LABELS[value] ?? value.replaceAll("_", " ");
}

function mergeCheckpoints(current: Checkpoint[], incoming: Checkpoint[]): Checkpoint[] {
  const byId = new Map(current.map((item) => [item.id, item]));
  incoming.forEach((item) => byId.set(item.id, item));
  return [...byId.values()].sort((left, right) => left.id - right.id);
}

function records(value: unknown): UnknownRecord[] {
  return Array.isArray(value)
    ? value.map(asRecord).filter((item): item is UnknownRecord => item !== null)
    : [];
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function replaceLegacyTerminology<T>(value: T): T {
  if (typeof value === "string") {
    return value
      .replace(/dossiês/giu, "relatórios")
      .replace(/dossiê/giu, "relatório") as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => replaceLegacyTerminology(item)) as T;
  }
  const record = asRecord(value);
  if (record) {
    return Object.fromEntries(
      Object.entries(record).map(([key, item]) => [key, replaceLegacyTerminology(item)]),
    ) as T;
  }
  return value;
}

function providerFailureLabel(error: string): string {
  if (error.includes("HTTP 402")) return "créditos do provedor esgotados";
  if (error.includes("HTTP 404")) return "modelo indisponível ou não habilitado";
  if (error.includes("HTTP 429")) return "limite de requisições atingido";
  if (error.includes("HTTP 503") || error.toLowerCase().includes("high demand")) return "modelo temporariamente indisponível por alta demanda";
  if (error.includes("ConnectError") || error.toLowerCase().includes("name resolution")) return "falha de conexão com o provedor";
  if (error.includes("Timeout")) return "tempo limite excedido pelo provedor";
  return "resposta do modelo inválida ou indisponível";
}

type AgentDefinition = (typeof AGENTS)[number];
type AgentRunEvent = RunResult["agent_events"][number];

function AgentCheckpointResult({
  agent,
  checkpoint,
  event,
}: {
  agent: AgentDefinition;
  checkpoint?: Checkpoint;
  event?: AgentRunEvent;
}) {
  const state = checkpoint?.state ?? {};
  if (!checkpoint && !event) {
    return <article className="checkpoint-result checkpoint-result--waiting"><h3>{agent.label}</h3><p>Aguardando esta etapa.</p></article>;
  }
  if (event?.error) {
    return <article className="checkpoint-result checkpoint-result--error"><h3>{agent.label}</h3><strong>Etapa de IA não concluída</strong><p>{providerFailureLabel(event.error)}.</p></article>;
  }

  if (agent.key === "classifier") {
    const classification = [...records(state.decisions)].reverse().find((item) => item.stage === "classifier");
    return <article className="checkpoint-result"><h3>Resultado do classificador</h3><dl className="checkpoint-facts"><div><dt>Modalidade</dt><dd>{statusLabel(String(state.modality ?? ""))}</dd></div><div><dt>Intenção</dt><dd>{statusLabel(String(state.intent ?? ""))}</dd></div></dl><p>{String(classification?.reason ?? event?.summary ?? "Classificação registrada.")}</p></article>;
  }

  if (agent.key === "investigator") {
    const report = asRecord(state.investigation);
    const hypotheses = records(report?.hypotheses);
    return <article className="checkpoint-result"><h3>Resultado do investigador</h3><strong>{String(report?.conclusion ?? event?.summary ?? "Relatório técnico registrado.")}</strong>{hypotheses.length > 0 && <ul>{hypotheses.map((item, index) => <li key={`${String(item.statement)}-${index}`}><StatusPill value={String(item.status ?? "open")} label={statusLabel(String(item.status ?? "open"))} /><span>{String(item.statement)}</span></li>)}</ul>}{texts(report?.unknowns).length > 0 && <p><b>Pontos em aberto:</b> {texts(report?.unknowns).join(" · ")}</p>}</article>;
  }

  if (agent.key === "source_selector") {
    const plan = asRecord(state.source_plan);
    const candidates = records(state.source_candidates);
    const selection = asRecord(state.source_selection);
    const selected = records(selection?.selected_sources);
    const titles = new Map(candidates.map((item) => [String(item.id), String(item.title)]));
    return <article className="checkpoint-result"><h3>Resultado do agente de fontes</h3><p><b>Consultas planejadas:</b> {texts(plan?.knowledge_queries).join(" · ") || "Nenhuma busca textual necessária."}</p><p><b>Leituras:</b> {texts(plan?.tools).join(" · ") || "Nenhuma leitura selecionada."}</p>{selected.length > 0 ? <ul>{selected.map((item) => <li key={String(item.id)}><strong>{titles.get(String(item.id)) ?? String(item.id)}</strong><span>{String(item.reason ?? "Fonte selecionada.")}</span></li>)}</ul> : <p>Nenhum documento de conhecimento selecionado.</p>}{texts(selection?.missing_information).length > 0 && <p><b>Lacunas:</b> {texts(selection?.missing_information).join(" · ")}</p>}</article>;
  }

  if (agent.key === "judge") {
    const verdict = asRecord(state.runtime_verdict);
    return <article className="checkpoint-result"><h3>Resultado do juiz</h3><StatusPill value={String(verdict?.verdict ?? "not_run")} label={statusLabel(String(verdict?.verdict ?? "not_run"))} />{texts(verdict?.reasons).length > 0 ? <ul>{texts(verdict?.reasons).map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>{event?.summary ?? "Parecer registrado."}</p>}</article>;
  }

  const draft = asRecord(state.draft);
  return <article className="checkpoint-result"><h3>Resultado do redator</h3><strong>{String(draft?.summary ?? event?.summary ?? "Resposta preparada.")}</strong>{texts(draft?.explanation).map((item) => <p key={item}>{item}</p>)}</article>;
}

function BenchmarkCondition({ title, data, highlighted = false }: { title: string; data: UnknownRecord; highlighted?: boolean }) {
  const cases = numeric(data.cases);
  const badReleases = numeric(data.runtime_bad_releases);
  return (
    <article className={`benchmark-condition${highlighted ? " benchmark-condition--highlighted" : ""}`}>
      <div><span>{title}</span><strong>{percentage(data.objective_score)}</strong></div>
      <p>{cases === null ? "Resultado disponível" : `${cases} casos avaliados`}</p>
      <dl>
        <div><dt>Decisões corretas</dt><dd>{percentage(data.decision_accuracy)}</dd></div>
        <div><dt>Respostas inseguras</dt><dd>{badReleases ?? "—"}</dd></div>
      </dl>
    </article>
  );
}

export function AnalysisDashboard({ personas, cases }: { personas: Persona[]; cases: DemoCase[] }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [result, setResult] = useState<RunResult | null>(null);
  const [benchmark, setBenchmark] = useState<UnknownRecord>({});
  const [caseId, setCaseId] = useState(cases[0]?.id ?? "");
  const [additionalContext, setAdditionalContext] = useState("");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const inspectGeneration = useRef(0);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetLoading, setAssetLoading] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [assetError, setAssetError] = useState("");
  const [inspectError, setInspectError] = useState("");
  const [historyFilter, setHistoryFilter] = useState("all");
  const [historySearch, setHistorySearch] = useState("");
  const selectedCase = cases.find((item) => item.id === caseId);
  const casePersona = personas.find((item) => item.user_id === selectedCase?.user_id);
  const caseAsset = assets.find((item) => item.id === selectedCase?.asset_id);

  useEffect(() => {
    let cancelled = false;
    setAssets([]);
    setAssetError("");
    setAssetLoading(false);
    if (!casePersona) return;
    setAssetLoading(true);
    api.assets(casePersona.id).then((items) => { if (!cancelled) setAssets(items); })
      .catch(() => { if (!cancelled) setAssetError("Não foi possível carregar os dados do ativo."); })
      .finally(() => { if (!cancelled) setAssetLoading(false); });
    return () => { cancelled = true; };
  }, [casePersona?.id]);

  const benchmarkSummary = asRecord(benchmark.summary);
  const benchmarkConfig = asRecord(benchmark.configuration);
  const gateOn = asRecord(benchmarkSummary?.gate_on);
  const gateOff = asRecord(benchmarkSummary?.gate_off);
  const traceState = [...checkpoints]
    .reverse()
    .map((checkpoint) => checkpoint.state)
    .find((state) => Array.isArray(state.tool_events));
  const toolEvents = (traceState?.tool_events ?? []) as UnknownRecord[];
  const checkpointNodes = new Set(checkpoints.map((checkpoint) => checkpoint.node));
  const checkpointAgentEvents = ([...(traceState?.agent_events as RunResult["agent_events"] ?? [])]);
  const agentEvents = result?.agent_events ?? checkpointAgentEvents;
  const traceVerdict = asRecord(traceState?.runtime_verdict);
  const isEscalated = selected?.decision === "escalar"
    || result?.decision === "escalar"
    || traceVerdict?.verdict === "escalate";

  useEffect(() => {
    if (!caseId && cases[0]) setCaseId(cases[0].id);
  }, [caseId, cases]);

  async function refresh() {
    const items = replaceLegacyTerminology(await api.adminRuns());
    setRuns(items);
    setSelected((current) => current
      ? items.find((item) => item.id === current.id) ?? current
      : current);
  }

  useEffect(() => {
    refresh().catch(() => undefined);
    api.benchmark().then(setBenchmark).catch(() => undefined);
    const timer = window.setInterval(() => refresh().catch(() => undefined), 1500);
    return () => window.clearInterval(timer);
  }, []);

  async function inspect(run: Run) {
    const generation = ++inspectGeneration.current;
    setInspectError("");
    setCaseId(run.case_id ?? "");
    setSelected(run);
    setCheckpoints([]);
    setResult(null);
    const loadedCheckpoints = replaceLegacyTerminology(await api.checkpoints(run.id));
    if (generation !== inspectGeneration.current) return;
    setCheckpoints((current) => mergeCheckpoints(current, loadedCheckpoints));
    if (run.status === "completed") {
      const loadedResult = replaceLegacyTerminology(await api.result(run.id));
      if (generation !== inspectGeneration.current) return;
      setResult(loadedResult);
    }
  }

  function openRun(run: Run) {
    void inspect(run).catch(() => setInspectError("Não foi possível carregar esta análise. Selecione-a novamente para tentar outra vez."));
    document.getElementById("investigacao")?.scrollIntoView?.({ block: "start" });
  }

  function changeCase(value: string) {
    ++inspectGeneration.current;
    setCaseId(value);
    setSelected(null);
    setResult(null);
    setCheckpoints([]);
    setAdditionalContext("");
    setLaunchError("");
    setInspectError("");
  }

  useEffect(() => {
    if (!selected || !["queued", "running"].includes(selected.status)) return;
    const runId = selected.id;
    const source = new EventSource(api.eventsUrl(runId));

    const onProgress = (raw: Event) => {
      try {
        const checkpoint = replaceLegacyTerminology(
          JSON.parse((raw as MessageEvent<string>).data) as Checkpoint & { run_id?: string },
        );
        if (checkpoint.run_id && checkpoint.run_id !== runId) return;
        setCheckpoints((current) => mergeCheckpoints(current, [checkpoint]));
        const stage = typeof checkpoint.state.current_stage === "string"
          ? checkpoint.state.current_stage
          : checkpoint.node;
        setSelected((current) => current?.id === runId
          ? { ...current, current_stage: stage }
          : current);
      } catch {
        // O polling de segurança continua ativo se um evento isolado vier inválido.
      }
    };
    const onDone = (raw: Event) => {
      source.close();
      try {
        const completed = replaceLegacyTerminology(
          JSON.parse((raw as MessageEvent<string>).data) as Run,
        );
        setRuns((current) => [completed, ...current.filter((item) => item.id !== completed.id)]);
        setSelected((current) => current?.id === completed.id ? completed : current);
      } catch {
        refresh().catch(() => undefined);
      }
    };
    const onError = () => {
      // Evita reconexões infinitas; o polling periódico ainda detecta a conclusão.
      source.close();
    };

    source.addEventListener("progress", onProgress);
    source.addEventListener("done", onDone);
    source.addEventListener("error", onError);
    return () => {
      source.removeEventListener("progress", onProgress);
      source.removeEventListener("done", onDone);
      source.removeEventListener("error", onError);
      source.close();
    };
  }, [selected?.id]);

  useEffect(() => {
    if (
      selected
      && ["completed", "failed"].includes(selected.status)
      && (selected.status === "failed" || result?.run_id !== selected.id)
    ) {
      inspect(selected).catch(() => undefined);
    }
  }, [selected?.id, selected?.status]);

  async function startAnalysis() {
    const selectedCase = cases.find((item) => item.id === caseId);
    const persona = personas.find((item) => item.user_id === selectedCase?.user_id);
    if (!selectedCase || !persona) {
      setLaunchError("O caso não está ligado a uma persona de demonstração válida.");
      return;
    }
    setLaunching(true);
    setLaunchError("");
    try {
      const session = await api.createSession(persona.id);
      const run = await api.createRun({
        persona_id: persona.id,
        session_id: session.id,
        asset_id: selectedCase.asset_id,
        case_id: selectedCase.id,
        investigation_key: selectedCase.id,
        message: selectedCase.message,
        additional_context: additionalContext.trim() || null,
        seed: "complete",
      });
      await refresh();
      await inspect(run);
      setAdditionalContext("");
    } catch (cause) {
      setLaunchError(cause instanceof Error ? cause.message : "Não foi possível iniciar a análise.");
    } finally {
      setLaunching(false);
    }
  }

  const counts = useMemo(() => ({
    total: runs.length,
    completed: runs.filter((item) => item.status === "completed").length,
    human: runs.filter((item) => item.decision === "escalar").length,
    failed: runs.filter((item) => item.status === "failed").length,
    running: runs.filter((item) => item.status === "running" || item.status === "queued").length,
  }), [runs]);

  const judgeEvent = [...agentEvents].reverse().find((item) => item.role === "judge");
  const judgeObjections = Array.from(new Map([
    ...(result?.runtime_verdict.advisory_objections ?? []),
    ...(result?.review_history?.flatMap((review) => review.advisory_objections ?? []) ?? []),
  ].map((item) => [`${item.kind}:${item.detail}`, item])).values());
  const handoffSummary = result?.escalation?.summary
    ?? "A resposta automática foi bloqueada. Revise o ticket e o parecer do juiz antes de responder ao cliente.";
  const handoffReviewReasons = result?.escalation?.review_reasons
    ?? result?.runtime_verdict.reasons
    ?? [];
  const handoffFindings = result?.escalation?.findings
    ?? result?.investigation?.hypotheses
    ?? [];
  const handoffOpenQuestions = result?.escalation?.open_questions
    ?? result?.investigation?.unknowns
    ?? result?.gaps
    ?? [];
  const handoffRecommendations = result?.escalation?.recommendations
    ?? result?.recommendations
    ?? [];
  const technicalAgentFailures = agentEvents.filter((item) => Boolean(item.error));
  const isBusinessEscalation = isEscalated && technicalAgentFailures.length === 0;
  const checkpointsByNode = new Map<string, Checkpoint>();
  checkpoints.forEach((checkpoint) => checkpointsByNode.set(checkpoint.node, checkpoint));
  const referencedEvidence = new Set(result?.investigation?.evidence_ids ?? []);
  const referencedEvidenceCount = result?.evidence.filter((item) => referencedEvidence.has(item.id)).length ?? 0;
  const latestGate = result?.gates[result.gates.length - 1];
  const hasSourceSelector = checkpoints.some((item) => item.node.startsWith("source_"))
    || agentEvents.some((item) => item.role === "source_selector");
  const visibleAgents = AGENTS.filter((agent) => agent.key !== "source_selector"
    || hasSourceSelector
    || selected?.status === "queued"
    || selected?.status === "running");
  const activeAgentIndex = visibleAgents.findIndex((agent) => {
    if (isBusinessEscalation && agent.key === "writer") return false;
    const hasEvent = agentEvents.some((item) => item.role === agent.key);
    return !checkpointNodes.has(agent.checkpoint) && !hasEvent;
  });

  const currentEvidence = result?.evidence ?? records(traceState?.evidence).map(item => ({ id: String(item.id), claim: String(item.claim ?? ""), source_path: String(item.source_path ?? ""), mode: String(item.mode ?? "unknown"), decisive: Boolean(item.decisive) }));
  const sourceWindow = collectionWindow(toolEvents, selectedCase?.asset_id ?? selected?.asset_id);
  const categoryLabels: Record<string, string> = { gearbox: "Redutor", compressor: "Compressor", pump: "Bomba", fan: "Ventilador", spindle: "Spindle", mill: "Moinho", motor_induction: "Motor de indução", motor_dc: "Motor CC", motor: "Motor" };
  const assetCategory = caseAsset ? categoryLabels[caseAsset.machine_type] ?? caseAsset.machine_type : "Não informada";
  const criticalityLabel = ({ critical: "Crítica", high: "Alta", medium: "Média", low: "Baixa" } as Record<string, string>)[caseAsset?.criticality ?? ""] ?? "Não informada";
  const workflowStep = !selected ? 0 : selected.status === "completed" || checkpointNodes.has("reviewer") ? 3 : checkpointNodes.has("source_select") || checkpointNodes.has("investigator") ? 2 : 1;
  const nextAction = !selected ? "Confirme o relato e inicie a análise do caso." : selected.status === "failed" ? "Verifique a falha técnica e inicie uma nova revisão." : isEscalated ? "Encaminhe as lacunas e os achados para revisão da engenharia." : selected.status === "completed" ? "Confira a conclusão e as fontes antes do uso operacional." : "Aguarde a coleta das fontes e acompanhe as etapas abaixo.";
  const filteredRuns = runs.filter(run => {
    const matchesState = historyFilter === "all" || (historyFilter === "running" && ["running", "queued"].includes(run.status)) || (historyFilter === "human" && run.decision === "escalar") || (historyFilter === "failed" && run.status === "failed");
    const ticket = cases.find(item => item.id === run.case_id)?.ticket_id ?? "";
    return matchesState && `${run.id} ${run.asset_id} ${run.case_id} ${run.message} ${ticket}`.toLocaleLowerCase("pt-BR").includes(historySearch.toLocaleLowerCase("pt-BR"));
  });

  return (
    <main className="admin-shell">
      <header className="page-heading" id="analises">
        <div><p className="breadcrumb">Intelligence <span>/</span> Engenharia e confiabilidade</p><h1>Investigações e relatórios</h1><p>Analise o caso, confira as evidências e revise a conclusão.</p></div>
        <button className="secondary refresh-button" onClick={() => { setRefreshError(""); refresh().catch(() => setRefreshError("Não foi possível atualizar o histórico. Tente novamente.")); }}><BrandIcon name="update" /> Atualizar dados</button>
      </header>
      {refreshError && <p className="error-message" role="alert">{refreshError}</p>}
      <div className="operational-summary" aria-label="Resumo operacional">
        <span><i className="operational-dot" /><b>{counts.running}</b> em andamento</span>
        <a href="#historico" onClick={() => setHistoryFilter("human")}><b>{counts.human}</b> encaminhadas à engenharia</a>
        <a className={counts.failed ? "has-failures" : ""} href="#historico" onClick={() => setHistoryFilter("failed")}><b>{counts.failed}</b> falhas técnicas</a>
        <a className="summary-history" href="#historico" onClick={() => setHistoryFilter("all")}>Histórico <span>{counts.total}</span><BrandIcon name="arrow" /></a>
      </div>

      <section className="investigation-workspace" id="investigacao" aria-label="Iniciar análise de demonstração">
        <div className="workspace-toolbar"><div><h2>Caso selecionado</h2>{selectedCase && <span className="case-id">{selectedCase.ticket_id}</span>}</div><StatusPill value={selected?.status ?? "draft"} label={selected ? statusLabel(selected.status) : "Análise não iniciada"} /></div>
        <ol className="compact-workflow" aria-label="Etapas da investigação">
          {["Caso", "Evidências", "Análise", "Revisão"].map((step, index) => <li key={step} className={index === workflowStep ? "current" : index < workflowStep ? "done" : ""} aria-current={index === workflowStep ? "step" : undefined}><span>{index < workflowStep ? <BrandIcon name="check" /> : index + 1}</span>{step}{index < 3 && <i aria-hidden="true">›</i>}</li>)}
        </ol>
        <div className="investigation-columns">
          <div className="investigation-main">
            <div className="case-editor" id="nova-analise">
              <label>Caso de investigação<select value={caseId} onChange={event => changeCase(event.target.value)}>
                {!cases.length && <option value="">Nenhum caso disponível</option>}
                {selected && !cases.some(item => item.id === caseId) && <option value={caseId}>Caso do histórico · {selected.asset_id}</option>}
                {cases.map(item => <option value={item.id} key={item.id}>{item.ticket_id} · {item.message}</option>)}
              </select></label>
              <p className="case-description">{selectedCase?.message ?? selected?.message ?? "Nenhum caso disponível para investigação."}</p>
              <div className="case-requester"><span>Solicitante</span><strong>{casePersona?.name ?? selected?.user_id ?? "Não informado"}</strong><span>{casePersona?.role}</span></div>
              <div className="case-next-action"><div><span>Próxima ação</span><strong>{nextAction}</strong></div><button className="primary" disabled={launching || !selectedCase || selected?.status === "running" || selected?.status === "queued"} onClick={startAnalysis}>{launching ? "Iniciando análise…" : selected ? "Iniciar nova revisão" : "Iniciar análise"}<BrandIcon name="arrow" /></button></div>
              <label className="context-label">Contexto adicional <span>Opcional · para uma nova revisão</span><textarea rows={2} value={additionalContext} onChange={event => setAdditionalContext(event.target.value)} placeholder="Ex.: manutenção realizada após a coleta ou mudança na operação." /></label>
              {launchError && <p className="error-message" role="alert">{launchError}</p>}
              {selected && <p className="case-revision">Revisão {selected.revision} iniciada em {formatCollection(selected.created_at)}</p>}
            </div>
            <EvidenceSources events={toolEvents} evidence={currentEvidence} started={Boolean(selected)} finished={selected?.status === "completed" || selected?.status === "failed"} />
          </div>
          <aside className="asset-context" aria-labelledby="asset-context-title">
            <div className="section-heading"><h3 id="asset-context-title">Contexto do ativo</h3><BrandIcon name="asset" /></div>
            {assetError && <p className="asset-error" role="alert">{assetError}</p>}
            <div className="asset-title"><span className="asset-identifier">{(selectedCase?.asset_id ?? selected?.asset_id)?.replace("asset_", "") ?? "Sem ativo"}</span><h4>{caseAsset?.name ?? (assetLoading ? "Carregando ativo…" : "Identificação não disponível")}</h4><p className="asset-location">{[caseAsset?.plant, caseAsset?.line].filter(Boolean).join(" · ") || "Localização não informada"}</p><p className="asset-company">{casePersona?.company_name ?? "Empresa não informada"}</p></div>
            <div className="asset-condition">
              <div><span>Criticidade</span><strong className={caseAsset?.criticality === "critical" ? "criticality-high" : ""}>{criticalityLabel}</strong></div>
              <div><span>Monitoramento</span>{caseAsset?.sensor_status ? <StatusPill value={caseAsset.sensor_status} label={statusLabel(caseAsset.sensor_status)} /> : <strong>Não informado</strong>}</div>
            </div>
            <dl className="asset-properties asset-properties--secondary">
              <div><dt>Categoria</dt><dd>{assetCategory}</dd></div>
              {caseAsset?.rotation_rpm && <div><dt>Rotação nominal</dt><dd>{caseAsset.rotation_rpm.toLocaleString("pt-BR")} rpm</dd></div>}
              <div><dt>Última coleta consultada</dt><dd>{formatCollection(sourceWindow.last)}</dd></div>
              <div><dt>Janela consultada</dt><dd>{sourceWindow.first && sourceWindow.last && sourceWindow.first !== sourceWindow.last ? `${formatCollection(sourceWindow.first)} a ${formatCollection(sourceWindow.last)}` : "Não estabelecida"}</dd></div>
            </dl>
            {caseAsset?.sensor_status === "offline" && <p className="sensor-notice"><BrandIcon name="signal" /><span>Sensor sem conexão. Verifique a cobertura das coletas antes de concluir sobre a falha.</span></p>}
            <div className="investigation-state"><h3>Estado da investigação</h3><dl><div><dt>Etapa atual</dt><dd>{selected ? (CHECKPOINT_LABELS[selected.current_stage] ?? statusLabel(selected.status)) : "Seleção do caso"}</dd></div><div><dt>Responsável pela revisão</dt><dd>{isEscalated ? "Engenharia de manutenção" : "Não atribuído"}</dd></div></dl>{selected?.status === "completed" && <a href="#conclusao">Revisar conclusão <BrandIcon name="arrow" /></a>}</div>
          </aside>
        </div>
        {inspectError && <p className="error-message" role="alert">{inspectError}</p>}
      {selected ? <section className="inspection" id="conclusao" aria-live="polite">
        <div className="inspection-head"><div><p className="eyebrow">Análise {selected.id.slice(-12)} · revisão {selected.revision}</p><h2>Resultado e revisão</h2></div><StatusPill value={selected.decision ?? selected.status} label={statusLabel(selected.decision ?? selected.status)} /></div>
        {selected.additional_context && <div className="context-note"><strong>Contexto acrescentado nesta revisão</strong><p>{selected.additional_context}</p></div>}
        {selected.error && <div className="run-alert run-alert--error"><strong>A análise falhou.</strong><p>{selected.error}</p></div>}
        {technicalAgentFailures.length > 0 && <div className="run-alert run-alert--error"><strong>Uma ou mais etapas de IA não foram concluídas.</strong><p>Isso é uma falha técnica, não uma recomendação de revisão humana. Reinicie a análise quando o provedor estiver disponível.</p><ul>{technicalAgentFailures.map((item, index) => <li key={`${item.role}-${index}`}><b>{AGENTS.find((agent) => agent.key === item.role)?.label ?? item.role}:</b> {providerFailureLabel(item.error ?? "")}</li>)}</ul></div>}

        <div className="agent-flow" aria-label="Fluxo dos agentes">
          {visibleAgents.map((agent, index) => {
            const event = [...agentEvents].reverse().find((item) => item.role === agent.key);
            const visited = checkpointNodes.has(agent.checkpoint) || Boolean(event);
            const skipped = isBusinessEscalation && agent.key === "writer";
            const active = !skipped && ["queued", "running"].includes(selected.status) && index === activeAgentIndex;
            return <article className={skipped ? "skipped" : visited ? "visited" : active ? "active" : ""} key={agent.key}>
              <header><i>{index + 1}</i><div><strong>{agent.label}</strong><span>{agent.detail}</span></div></header>
              <p>{skipped ? (event ? "Executado nesta análise antiga, mas a resposta foi bloqueada pelo juiz." : "Não executado: o juiz bloqueou a resposta ao cliente.") : event?.summary ?? (visited ? "Etapa registrada." : active ? "Agente em execução." : "Aguardando etapa anterior.")}</p>
              {!skipped && event && <small>{event.model} · {statusLabel(event.status)} · {(event.latency_ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s</small>}
            </article>;
          })}
        </div>

        {result ? <>
          <section className="report-grid">
            <article className="panel investigation-report">
              <div className="card-heading"><p className="eyebrow">Checkpoint principal</p><h3>Relatório da investigação</h3><p>Conteúdo bruto consolidado antes da redação.</p></div>
              <h4>{result.investigation?.conclusion ?? result.response?.summary ?? result.escalation?.summary}</h4>
              <div className="support-summary"><div><span>Evidências rastreadas</span><strong>{referencedEvidenceCount}/{result.evidence.length}</strong></div><div><span>Suficiência dos dados</span><strong>{latestGate?.passed ? "Aprovada" : "Bloqueada"}</strong></div><div><span>Pontos em aberto</span><strong>{result.investigation?.unknowns.length ?? result.gaps.length}</strong></div><p>Esses indicadores mostram cobertura e lacunas verificáveis; não representam uma probabilidade de o diagnóstico estar correto.</p></div>
              {result.investigation?.hypotheses.length ? <div className="report-list"><h5>Hipóteses avaliadas</h5>{result.investigation.hypotheses.map((item, index) => <div key={`${item.statement}-${index}`}><StatusPill value={item.status} label={statusLabel(item.status)} /><span>{item.statement}</span></div>)}</div> : null}
              {result.investigation?.unknowns.length ? <div className="unknowns"><strong>O que ainda não sabemos</strong><ul>{result.investigation.unknowns.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
              {result.recommendations.length ? <div className="recommendations"><strong>Ações recomendadas — nenhuma foi executada</strong>{result.recommendations.map((item) => <div key={`${item.kind}-${item.target_id}`}><StatusPill value="recomendar" label={statusLabel("recomendar")} /><span><b>{item.kind.replaceAll("_", " ")}</b><small>{item.justification}</small></span></div>)}</div> : null}
            </article>

            <article className="panel judge-report">
              <div className="card-heading"><p className="eyebrow">Checkpoint principal</p><h3>Parecer do juiz</h3><p>O juiz revisa o relatório técnico antes do redator.</p></div>
              <StatusPill value={result.runtime_verdict.verdict} label={statusLabel(result.runtime_verdict.verdict)} />
              <h4>{result.runtime_verdict.verdict === "approve" ? "Relatório liberado para redação" : "Relatório requer tratamento adicional"}</h4>
              <ul>{result.runtime_verdict.reasons.map((item) => <li key={item}>{item}</li>)}</ul>
              {judgeObjections.length > 0 && <div className="review-history"><h5>Objeções consultivas registradas</h5>{judgeObjections.map((item) => <div key={`${item.kind}:${item.detail}`}><StatusPill value="warning" label={item.kind.replaceAll("_", " ")} /><p>{item.detail}</p></div>)}</div>}
              {(result.review_history?.length ?? 0) > 1 && <div className="review-history"><h5>Tentativas de correção</h5>{result.review_history?.map((review, index) => <div key={`${review.verdict}-${index}`}><StatusPill value={review.verdict} label={`Parecer ${index + 1}: ${statusLabel(review.verdict)}`} /><p>{review.reasons.join(" · ")}</p></div>)}</div>}
              <dl><div><dt>Modelo</dt><dd>{judgeEvent?.model ?? result.runtime_verdict.judge}</dd></div><div><dt>Modo</dt><dd>{statusLabel(judgeEvent?.status ?? result.runtime_verdict.judge)}</dd></div></dl>
            </article>
          </section>

          {isBusinessEscalation && result.escalation ? <section className="engineer-handoff">
            <div className="handoff-heading">
              <div><p className="eyebrow">Revisão humana</p><h3>Repasse para engenharia</h3><p>Este conteúdo é interno e deve orientar a resposta de uma pessoa.</p></div>
              <span>Não enviar ao cliente</span>
            </div>
            <div className="handoff-summary"><strong>Resumo do caso</strong><p>{handoffSummary}</p></div>
            <div className="handoff-grid">
              <article><h4>Por que a resposta foi bloqueada</h4><ul>{handoffReviewReasons.map((item) => <li key={item}>{item}</li>)}</ul></article>
              <article><h4>Achados preliminares — validar</h4>{handoffFindings.length ? handoffFindings.map((item, index) => <div className="handoff-finding" key={`${item.statement}-${index}`}><StatusPill value={item.status} label={statusLabel(item.status)} /><span>{item.statement}</span></div>) : <p>Nenhum achado foi considerado suficientemente seguro.</p>}</article>
              <article><h4>Pontos em aberto</h4>{handoffOpenQuestions.length ? <ul>{handoffOpenQuestions.map((item) => <li key={item}>{item}</li>)}</ul> : <p>Use os motivos do juiz para direcionar a revisão.</p>}</article>
              <article><h4>Ações sugeridas — nenhuma executada</h4>{handoffRecommendations.length ? <ul>{handoffRecommendations.map((item, index) => <li key={`${item.kind}-${item.target_id}-${index}`}><strong>{item.kind.replaceAll("_", " ")}</strong>: {item.justification}</li>)}</ul> : <p>O engenheiro deve definir o próximo passo após revisar as evidências.</p>}</article>
            </div>
          </section> : null}

          <section className="result-facts"><div><span>Resultado</span><strong>{statusLabel(result.decision)}</strong></div><div><span>Consultas de leitura</span><strong>{result.metrics.tool_calls}</strong></div><div><span>Mutações</span><strong>{result.metrics.mutations_attempted}</strong></div><div><span>Duração total</span><strong>{(result.metrics.duration_ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s</strong></div></section>
        </> : selected.status === "failed" ? <div className="run-alert run-alert--error"><strong>Execução interrompida por falha técnica.</strong><p>Nenhuma decisão de revisão humana foi gerada. Consulte o checkpoint com erro e tente novamente.</p></div> : <div className="run-alert"><strong>{selected.status === "completed" ? "Carregando relatório…" : "Análise em andamento."}</strong><p>As fontes e os resultados são atualizados conforme cada etapa termina.</p></div>}

        <details className="checkpoint-results"><summary>O que cada agente entregou</summary>

          <div className="checkpoint-results-grid">{visibleAgents.map((agent) => <AgentCheckpointResult key={agent.key} agent={agent} checkpoint={checkpointsByNode.get(agent.checkpoint)} event={[...agentEvents].reverse().find((item) => item.role === agent.key)} />)}</div>
        </details>

        <details className="technical-details">
          <summary>Ver consultas e checkpoints técnicos</summary>
          <div className="technical-grid">
            <article><h3>Consultas realizadas ({toolEvents.length})</h3>{toolEvents.map((raw, index) => <div className="tool-row" key={String(raw.id ?? index)}><span className="method">{String(raw.method)}</span><code>{String(raw.path)}</code><small>{Number(raw.latency_ms ?? 0).toFixed(0)} ms</small></div>)}</article>
            <article><h3>Marcos persistidos ({checkpoints.length})</h3><div className="timeline">{checkpoints.map((checkpoint) => <div key={checkpoint.id}><i /><span><strong>{CHECKPOINT_LABELS[checkpoint.node] ?? checkpoint.node}</strong><small>{new Date(checkpoint.created_at).toLocaleTimeString("pt-BR")}</small></span></div>)}</div></article>
          </div>
        </details>
      </section> : <div className="conclusion-pending"><strong>Conclusão pendente</strong><span>Disponível após a análise das evidências e a revisão técnica.</span></div>}
      </section>

      <section className="history-section" id="historico">
        <div className="panel runs-table">
          <div className="table-title"><div><h2>Análises recentes</h2><span>{filteredRuns.length} de {runs.length} registros</span></div><div className="history-controls"><input aria-label="Buscar no histórico" placeholder="Buscar caso, ativo ou análise" value={historySearch} onChange={event => setHistorySearch(event.target.value)} /><select aria-label="Filtrar histórico" value={historyFilter} onChange={event => setHistoryFilter(event.target.value)}><option value="all">Todas as análises</option><option value="running">Em andamento</option><option value="human">Revisão humana</option><option value="failed">Falhas técnicas</option></select></div></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Análise</th><th>Caso / ativo</th><th>Revisão</th><th>Status</th><th>Resultado</th></tr></thead>
            <tbody>{filteredRuns.map((run) => (
              <tr className={selected?.id === run.id ? "selected" : ""} key={run.id} onClick={() => openRun(run)}>
                <td><button className="run-link" onClick={(event) => { event.stopPropagation(); openRun(run); }}>{run.id.slice(-8)}</button><small>{new Date(run.created_at).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })} · {new Date(run.created_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</small></td>
                <td><span>{cases.find(item => item.id === run.case_id)?.ticket_id ?? run.case_id ?? "Sem caso"}</span><small>{run.asset_id.replace("asset_", "")}</small></td>
                <td>R{run.revision}{run.reused ? " · reutilizada" : ""}</td>
                <td><StatusPill value={run.status} label={statusLabel(run.status)} /></td>
                <td><StatusPill value={run.decision ?? "queued"} label={statusLabel(run.decision)} /></td>
              </tr>
            ))}</tbody>
          </table></div>
          {!filteredRuns.length && <p className="history-empty">{runs.length ? "Nenhuma análise corresponde aos filtros." : "Nenhuma análise registrada. Selecione um caso e inicie a investigação."}</p>}
        </div>

        <section className="quality-tool" id="qualidade">
          <div className="quality-heading"><div><h2>Qualidade do sistema</h2><p>Última avaliação das decisões e proteções da investigação.</p></div><StatusPill value={String(benchmark.status ?? "not_run")} label={statusLabel(String(benchmark.status ?? "not_run"))} /></div>
          {gateOn || gateOff ? <div className="benchmark-comparison">
            {gateOn && <BenchmarkCondition title="Proteção ligada" data={gateOn} highlighted />}
            {gateOff && <BenchmarkCondition title="Proteção desligada" data={gateOff} />}
          </div> : <p className="benchmark-empty">{String(benchmark.message ?? "O teste ainda não foi executado.")}</p>}
          <details className="quality-technical"><summary>Detalhes técnicos</summary><dl><div><dt>Conjunto de dados</dt><dd>{String(benchmarkConfig?.dataset ?? "—")}</dd></div><div><dt>Amostra</dt><dd>{numeric(benchmarkConfig?.sample_size) ?? numeric(gateOn?.cases) ?? "—"} casos</dd></div><div><dt>Estratégia</dt><dd>{String(benchmarkConfig?.mode ?? "Não informada")}</dd></div><div><dt>Divisão</dt><dd>{String(benchmarkConfig?.split ?? "—")}</dd></div><div><dt>Versão da política</dt><dd>{String(benchmarkConfig?.policy_version ?? "—")}</dd></div></dl><details className="raw-details"><summary>Resposta JSON</summary><pre>{JSON.stringify(benchmarkSummary ?? benchmark.message ?? "Sem dados.", null, 2)}</pre></details></details>
        </section>
      </section>


    </main>
  );
}
