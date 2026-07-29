import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const run = {
  id: "00000000-0000-0000-0000-000000000001",
  case_id: "00000000-0000-0000-0000-000000000002",
  request_revision_id: "00000000-0000-0000-0000-000000000003",
  title: "Replace warehouse printers",
  status: "completed",
  current_phase: "intake complete",
  created_at: "2026-07-29T10:00:00Z",
  completed_at: "2026-07-29T10:00:01Z",
  events: [
    {
      event_id: "00000000-0000-0000-0000-000000000004",
      run_id: "00000000-0000-0000-0000-000000000001",
      sequence: 1,
      event_type: "run.created",
      status: "running",
      summary: "Procurement run created",
      created_at: "2026-07-29T10:00:00Z",
    },
  ],
  artifacts: [
    {
      id: "00000000-0000-0000-0000-000000000005",
      kind: "requirements_specification",
      filename: "requirements.md",
      media_type: "text/markdown",
      size_bytes: 128,
      download_url: "/api/runs/1/artifacts/1",
    },
  ],
} as const;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("starts as a category-generic procurement intake", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Procurement control room" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Item or service")).toBeInTheDocument();
    expect(screen.getByText("No active run")).toBeInTheDocument();
  });

  it("creates and renders an observable procurement run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => run,
      }),
    );
    render(<App />);

    fireEvent.change(screen.getByLabelText("Request title"), {
      target: { value: run.title },
    });
    fireEvent.change(screen.getByLabelText("Item or service"), {
      target: { value: "Industrial label printer" },
    });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Networked thermal printer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create procurement run" }));

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("completed"),
    );
    expect(screen.getByText("Procurement run created")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Download" }),
    ).toHaveAttribute("href", run.artifacts[0].download_url);
  });
});
