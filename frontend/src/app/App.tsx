import { useEffect, useState } from "react";
import tractianWordmark from "../assets/tractian-wordmark.svg";
import { AnalysisDashboard } from "../features/AnalysisDashboard";
import { BrandIcon } from "../components/BrandIcon";
import { api } from "../lib/api";
import type { DemoCase, Persona } from "../types";

export function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [cases, setCases] = useState<DemoCase[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([api.personas(), api.cases()])
      .then(([people, examples]) => { setPersonas(people); setCases(examples); })
      .catch((cause: Error) => setError(cause.message));
  }, []);

  return <div className="app">
    <header className="topbar">
      <div className="topbar-inner">
        <a className="brand" href="#" aria-label="TRACTIAN Intelligence">
          <img className="brand-logo" src={tractianWordmark} alt="TRACTIAN" />
          <span className="product-name">Intelligence</span>
        </a>
        <div className="topbar-actions">
          <div className="environment-label">Demonstração</div>
          <div className="profile-badge"><BrandIcon name="ai" /><span>Ambiente interno<small>Suporte e confiabilidade</small></span></div>
        </div>
      </div>
    </header>
    {error ? <div className="boot-error"><h1>Backend indisponível</h1><p>{error}</p><code>make dev</code></div> : !personas.length ? <div className="loader"><i /><p>Preparando contexto industrial…</p></div> : <AnalysisDashboard personas={personas} cases={cases} />}
    <footer><span>TRACTIAN Intelligence · ambiente demonstrativo</span><span>Dados sintéticos · ações apenas recomendadas</span></footer>
  </div>;
}
