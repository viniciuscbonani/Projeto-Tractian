export type Persona = {
  id: string;
  user_id: string;
  name: string;
  role: string;
  company_id: string;
  company_name: string;
};

export type Asset = {
  id: string;
  name: string;
  criticality: string;
  machine_type: string;
  sensor_status?: string;
  plant?: string;
  line?: string;
  rotation_rpm?: number;
};

export type DemoCase = {
  id: string;
  ticket_id: string;
  company_id: string;
  user_id: string;
  asset_id: string;
  message: string;
};

export type Run = {
  id: string;
  session_id: string | null;
  persona_id: string;
  user_id: string;
  asset_id: string;
  case_id: string | null;
  message: string;
  additional_context: string | null;
  investigation_key: string | null;
  revision: number;
  parent_run_id: string | null;
  reused: boolean;
  seed: string;
  gate_enabled: boolean;
  status: "queued" | "running" | "completed" | "failed";
  modality: string | null;
  decision: string | null;
  current_stage: string;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type Evidence = {
  id: string;
  claim: string;
  source_path: string;
  mode: string;
  decisive: boolean;
};

export type RunResult = {
  run_id: string;
  thread_id: string;
  status: string;
  modality: string;
  decision: string;
  response: {
    summary: string;
    explanation: string[];
    next_steps: string[];
    limitations: string[];
  } | null;
  final_response_valid?: boolean;
  factual_context?: {
    evidence_id: string;
    source_event_id: string;
    source_path: string;
    field: string;
    value: unknown;
    mode: string;
    observed_at: string;
  }[];
  evidence: Evidence[];
  gaps: string[];
  gates: { gate: string; passed: boolean; enabled: boolean; reasons: string[]; missing: string[] }[];
  runtime_verdict: RuntimeVerdict;
  actions: unknown[];
  recommendations: {
    kind: string;
    target_id: string | null;
    justification: string;
    priority: "low" | "medium" | "high";
    requires_human_approval: boolean;
  }[];
  investigation: {
    conclusion: string;
    evidence_ids: string[];
    hypotheses: { statement: string; status: "supported" | "weakened" | "open"; evidence_ids: string[] }[];
    unknowns: string[];
    needs_human: boolean;
  } | null;
  source_plan?: {
    tools: string[];
    required_tools: string[];
    knowledge_queries: string[];
    analysis_status: string | null;
    focus: string[];
  } | null;
  source_candidates?: SourceCandidate[];
  source_selection?: {
    selected_sources: { id: string; reason: string }[];
    missing_information: string[];
  } | null;
  review_history?: RuntimeVerdict[];
  agent_events: {
    role: "classifier" | "source_selector" | "investigator" | "judge" | "writer";
    model: string;
    status: "completed" | "fallback" | "failed" | "reused";
    latency_ms: number;
    summary: string;
    error: string | null;
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
    attempts?: number;
    token_usage_complete?: boolean | null;
    failure_stage?: string | null;
    failure_reason?: string | null;
    created_at: string;
  }[];
  escalation?: {
    reason: string;
    ticket: string;
    user_id: string;
    asset_id: string;
    recipient?: "maintenance_engineer";
    customer_response_allowed?: false;
    summary?: string;
    review_reasons?: string[];
    findings?: {
      statement: string;
      status: "supported" | "weakened" | "open";
      evidence_ids: string[];
    }[];
    open_questions?: string[];
    recommendations?: {
      kind: string;
      target_id: string | null;
      justification: string;
      priority: "low" | "medium" | "high";
      requires_human_approval: boolean;
    }[];
    executed: boolean;
  } | null;
  metrics: { tool_calls: number; duration_ms: number; degraded_reads: number; conflicts: number; mutations_attempted: number };
};

export type SourceCandidate = {
  id: string;
  title: string;
  type: string | null;
  tags: string[];
  snippet: string;
};

export type RuntimeVerdict = {
  verdict: string;
  intent_aligned?: boolean;
  recommendation_supported?: boolean;
  suggested_intent?: string | null;
  missing_sources?: string[];
  unsupported_claims?: string[];
  safe: boolean;
  grounded: boolean;
  complete: boolean;
  judge: string;
  reasons: string[];
  advisory_objections?: ReviewObjection[];
  safe_fallback_required?: boolean;
};

export type ReviewObjection = {
  kind: "intent_mismatch" | "missing_source" | "unsupported_claim" | "unsafe_recommendation" | "decisive_conflict" | "human_required";
  detail: string;
  claim?: string | null;
  source?: string | null;
  suggested_intent?: string | null;
};

export type Checkpoint = {
  id: number;
  node: string;
  created_at: string;
  state: Record<string, unknown>;
};
