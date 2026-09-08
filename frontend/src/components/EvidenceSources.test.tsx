import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { collectionWindow, EvidenceSources } from "./EvidenceSources";

test("separa fontes indisponíveis de fontes não consultadas e preserva as evidências", () => {
  render(<EvidenceSources started finished events={[
    { id: "read_1", path: "/assets/asset_1/spectrum", envelope: { mode: "unavailable", data: { samples: [{ value: 1 }, { value: 2 }] }, notes: "Sem cobertura na janela." } },
    { id: "read_2", path: "/knowledge/kb_1", envelope: { mode: "complete" } },
  ]} evidence={[{ id: "ev_1", source_path: "/knowledge/kb_1", claim: "Inspecionar a fixação.", mode: "complete", decisive: true }]} />);
  const vibration = screen.getByText("Vibração").closest("details")!;
  expect(within(vibration).getByText("2 sinais · 1 consulta")).toBeInTheDocument();
  expect(within(vibration.querySelector("summary")!).getByText("Indisponível · 1 problema")).toBeInTheDocument();
  expect(within(vibration).getByText("Sem cobertura na janela.")).toBeInTheDocument();
  expect(within(screen.getByText("Temperatura").closest("details")!).getByText("Não consultada")).toBeInTheDocument();
  expect(screen.getByText("Inspecionar a fixação.")).toBeInTheDocument();
  expect(screen.getByText("ev_1 · Decisiva")).toBeInTheDocument();
});

test("calcula a janela com coletas do ativo, sem usar horário de execução ou outro ativo", () => {
  const window = collectionWindow([
    { path: "/assets/asset_1/rms", started_at: "2026-09-06T15:00:00Z", envelope: { data: { samples: [{ ts: "2026-07-14T10:00:00Z" }, { ts: "2026-07-15T11:00:00Z" }] } } },
    { path: "/assets/asset_1/spectrum", envelope: { data: { collected_at: "2026-07-15T12:00:00Z" } } },
    { path: "/assets/asset_other/spectrum", envelope: { data: { collected_at: "2026-08-01T00:00:00Z" } } },
    { path: "/assets/asset_1/spectrum", error: { message: "Falha" }, envelope: { data: { collected_at: "2026-08-02T00:00:00Z" } } },
  ], "asset_1");
  expect(window).toEqual({ first: "2026-07-14T10:00:00Z", last: "2026-07-15T12:00:00Z" });
  expect(collectionWindow([], "asset_1")).toEqual({ first: undefined, last: undefined });
});
