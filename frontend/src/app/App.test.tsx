import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.restoreAllMocks());

test("renderiza somente a área interna de análises", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: string) => ({
    ok: true,
    json: async () => input.includes("personas") ? [{ id: "ana", user_id: "usr_ana", name: "Ana", role: "Gerente", company_id: "c", company_name: "Forja" }] : [],
  })));
  render(<App />);
  expect(screen.getByAltText("TRACTIAN")).toBeInTheDocument();
  expect(await screen.findByText("Investigações e relatórios")).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Navegação principal" })).not.toBeInTheDocument();
  expect(screen.queryByText("Atendimento")).not.toBeInTheDocument();
});
