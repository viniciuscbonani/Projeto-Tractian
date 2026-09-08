import { BrandIcon } from "./BrandIcon";
import { StatusPill } from "./StatusPill";
import type { Evidence } from "../types";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue => value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const sources = [
  { name: "Vibração", detail: "RMS, espectro e referência", icon: "vibration", match: /\/(rms|spectrum|baseline)(?:[/?]|$)/ },
  { name: "Temperatura", detail: "Medições térmicas", icon: "temperature", match: /temperature|temperatura|thermal/ },
  { name: "Histórico do ativo", detail: "Insights e análises anteriores", icon: "asset", match: /\/(analyses|analysis)(?:[/?]|$)/ },
  { name: "Manutenção", detail: "Intervenções e ordens de serviço", icon: "report", match: /maintenance|work.order|manutencao/ },
  { name: "Documentação", detail: "Manuais e conhecimento técnico", icon: "report", match: /knowledge|documents|\/model/ },
  { name: "Qualidade do sinal", detail: "Cobertura e integridade da coleta", icon: "signal", match: /data.quality|sensor/ },
] as const;

const modeLabels: Record<string, string> = { complete: "Disponível", partial: "Parcial", inconclusive: "Inconclusiva", conflict: "Conflito", unavailable: "Indisponível", failed: "Falha na consulta" };

function signalCount(value: unknown): number {
  const data = record(value);
  const nestedSpectrum = record(data.spectrum);
  const collections = [data.samples, data.peaks, data.analyses, data.documents, nestedSpectrum.peaks];
  return Math.max(0, ...collections.map(item => Array.isArray(item) ? item.length : 0));
}

function plural(count: number, singular: string, pluralForm: string) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

export function collectionWindow(events: RecordValue[], assetId?: string) {
  const times = events.filter(event => assetId && String(event.path).includes(`/assets/${assetId}/`) && !event.error).flatMap(event => {
    const data = record(record(event.envelope).data);
    const samples = Array.isArray(data.samples) ? data.samples.map(sample => record(sample).ts) : [];
    return [data.collected_at, ...samples].filter((value): value is string => typeof value === "string" && Number.isFinite(Date.parse(value)));
  }).sort((a, b) => Date.parse(a) - Date.parse(b));
  return { first: times[0], last: times.at(-1) };
}

export function formatCollection(value?: string) {
  return value ? new Date(value).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Não informada";
}

export function EvidenceSources({ events, evidence, started, finished }: { events: RecordValue[]; evidence: Evidence[]; started: boolean; finished: boolean }) {
  const ungrouped = evidence.filter(item => !sources.some(source => source.match.test(item.source_path)));
  return <section className="evidence-sources" aria-labelledby="evidence-title" id="evidencias">
    <div className="section-heading"><h3 id="evidence-title">Evidências e fontes</h3><span>{evidence.length} evidências registradas</span></div>
    <div className="source-list">
      {sources.map(source => {
        const reads = events.filter(event => source.match.test(String(event.path)));
        const items = evidence.filter(item => source.match.test(item.source_path));
        const modes = [...reads.map(event => event.error ? "failed" : String(record(event.envelope).mode ?? "complete")), ...items.map(item => item.mode)];
        const mode = ["failed", "unavailable", "conflict", "inconclusive", "partial", "complete"].find(value => modes.includes(value));
        const issueCount = modes.filter(value => ["failed", "unavailable", "conflict", "inconclusive", "partial"].includes(value)).length;
        const signals = reads.reduce((total, event) => total + signalCount(record(event.envelope).data), 0);
        const quantities = [
          signals ? plural(signals, "sinal", "sinais") : "",
          reads.length ? plural(reads.length, "consulta", "consultas") : "",
          items.length ? plural(items.length, "evidência", "evidências") : "",
        ].filter(Boolean);
        const label = mode ? modeLabels[mode] : finished ? "Não consultada" : started ? "Aguardando" : "A consultar";
        return <details className="source-item" key={source.name}>
          <summary><BrandIcon name={source.icon} /><span className="source-name"><strong>{source.name}</strong><small>{quantities.length ? quantities.join(" · ") : source.detail}</small></span><span className={`source-state${mode ? ` source-state--${mode}` : ""}`}>{label}{issueCount > 0 && ` · ${plural(issueCount, "problema", "problemas")}`}</span><span className="source-chevron" aria-hidden="true">›</span></summary>
          <div className="source-content">
            {!reads.length && !items.length && <p>{finished ? "Esta fonte não foi consultada nesta investigação." : "A disponibilidade será verificada conforme o plano de investigação."}</p>}
            {items.map(item => <div className="evidence-entry" key={item.id}><strong>{item.id}{item.decisive ? " · Decisiva" : ""}</strong><p>{item.claim}</p><code>{item.source_path}</code></div>)}
            {reads.map((event, index) => <div className="source-read" key={String(event.id ?? index)}><code>{String(event.path)}</code><span>{modeLabels[String(event.error ? "failed" : record(event.envelope).mode ?? "complete")] ?? "Disponível"}</span>{Boolean(record(event.envelope).notes) && <p>{String(record(event.envelope).notes)}</p>}</div>)}
          </div>
        </details>;
      })}
      {ungrouped.length > 0 && <details className="other-evidence"><summary>Outras evidências ({ungrouped.length})</summary>{ungrouped.map(item => <div className="evidence-entry" key={item.id}><StatusPill value={item.mode} label={modeLabels[item.mode] ?? item.mode} /><p>{item.claim}</p><code>{item.source_path}</code></div>)}</details>}
    </div>
  </section>;
}
