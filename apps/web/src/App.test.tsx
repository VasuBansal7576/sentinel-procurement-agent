import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { createFixtureGateway } from "./operator/fixtureGateway";

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("structural operator workbench", () => {
  it("restores a durable session and navigates run history", async () => {
    const view = render(<App gateway={createFixtureGateway()} />);

    expect(
      await screen.findByRole("heading", {
        name: "Replace warehouse label printers",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("14 of 21 work items")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Fixture projection · deterministic local data · no external effects",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/FIXTURE MODE: typed local projection/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Deterministic local suppliers · not live market data/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radiogroup", {
        name: /How much autonomy this run may use/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /Ask before external contact/i }),
    ).toBeChecked();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Source chemical-resistant gloves/i,
      }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Source chemical-resistant gloves",
      }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("sentinel.active-run-id")).toBe(
      "run-gloves",
    );
    expect(screen.getByText("21 of 21 work items")).toBeInTheDocument();

    view.unmount();
    render(<App gateway={createFixtureGateway()} />);
    expect(
      await screen.findByRole("heading", {
        name: "Source chemical-resistant gloves",
      }),
    ).toBeInTheDocument();
  });

  it("discloses nested subagent work and retries a safe failure from checkpoint", async () => {
    render(<App gateway={createFixtureGateway()} />);
    await screen.findByRole("heading", {
      name: "Replace warehouse label printers",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Expand Serviceability research" }),
    );
    expect(
      screen.getByText("Browser process ended after 2 successful captures."),
    ).toBeInTheDocument();
    expect(screen.getByText(/TRANSIENT · attempt 1 of 3/)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Retry from checkpoint" }),
    );

    await waitFor(() =>
      expect(screen.getAllByText("Recovering").length).toBeGreaterThan(0),
    );
    expect(
      screen
        .getAllByRole("status")
        .some((status) => status.textContent?.includes("recovering")),
    ).toBe(true);
    expect(screen.getByText(/0 blockers/)).toBeInTheDocument();
  });

  it("supports keyboard navigation across comparison, evidence, and requirements", async () => {
    render(<App gateway={createFixtureGateway()} />);
    await screen.findByRole("heading", { name: "Candidate ledger" });

    const comparisonTab = screen.getByRole("tab", { name: "Comparison" });
    comparisonTab.focus();
    fireEvent.keyDown(comparisonTab, { key: "ArrowRight" });

    const evidenceTab = screen.getByRole("tab", { name: "Evidence" });
    expect(evidenceTab).toHaveFocus();
    expect(evidenceTab).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("heading", { name: "Manufacturer specification" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(evidenceTab, { key: "End" });
    expect(screen.getByRole("tab", { name: "Requirements" })).toHaveFocus();
    expect(screen.getByText("5 years")).toBeInTheDocument();
  });

  it("lets the operator change autonomy without engineer vocabulary", async () => {
    render(<App gateway={createFixtureGateway()} />);
    await screen.findByRole("heading", {
      name: "Replace warehouse label printers",
    });

    fireEvent.click(
      screen.getByRole("radio", { name: /Research only · no external contact/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("radio", {
          name: /Research only · no external contact/i,
        }),
      ).toBeChecked(),
    );
    expect(
      screen.queryByRole("heading", { name: "RFQ proposal" }),
    ).not.toBeInTheDocument();
  });

  it("queues context and applies a redirect as acknowledged operator commands", async () => {
    render(<App gateway={createFixtureGateway()} />);
    await screen.findByRole("heading", {
      name: "Replace warehouse label printers",
    });

    const composer = screen.getByRole("region", {
      name: "Operator instructions",
    });
    const instruction = within(composer).getByLabelText("Operator instruction");
    fireEvent.change(instruction, {
      target: { value: "Confirm on-site installation pricing." },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "Queue instruction" }),
    );

    await waitFor(() =>
      expect(
        screen.getByText("Confirm on-site installation pricing."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/queued · just now/i)).toBeInTheDocument();

    fireEvent.click(within(composer).getByLabelText("Redirect"));
    fireEvent.change(instruction, {
      target: { value: "Require installation before 30 September." },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "Apply redirect" }),
    );

    await waitFor(() =>
      expect(screen.getByText("Revision 4")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Require installation before 30 September."),
    ).toBeInTheDocument();
  });

  it("shows a semantic version diff, saves a new proposal version, and binds approval", async () => {
    render(<App gateway={createFixtureGateway()} />);
    await screen.findByRole("heading", { name: "RFQ proposal" });

    fireEvent.click(screen.getByRole("tab", { name: "v2 → v3" }));
    expect(
      screen.getByText(/Editing invalidated sha256:401c…a21e/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Attachment set changed from 1 to 2/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Edit proposal" }));
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "RFQ — twelve printers with on-site setup" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save as new version" }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Approve exact v4 — no send",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("sha256:fixture-v4")).toBeInTheDocument();
    expect(screen.getAllByText("recommendation-r2.pdf")).toHaveLength(2);

    fireEvent.click(
      screen.getByRole("button", { name: "Approve exact v4 — no send" }),
    );
    expect(
      await screen.findByText(/Approved by Current operator.*No dispatch occurred/),
    ).toBeInTheDocument();
    expect(screen.getByText("approved")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Edit and revoke approval" }),
    );
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "RFQ — changed after approval" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save as new version" }),
    );
    expect(
      await screen.findByRole("button", {
        name: "Approve exact v5 — no send",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("approved")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation across proposal preview and diff tabs", async () => {
    render(<App gateway={createFixtureGateway()} />);
    const preview = await screen.findByRole("tab", { name: "Exact preview" });
    preview.focus();

    fireEvent.keyDown(preview, { key: "ArrowRight" });

    const diff = screen.getByRole("tab", { name: "v2 → v3" });
    expect(diff).toHaveFocus();
    expect(diff).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/Editing invalidated/)).toBeInTheDocument();
  });

  it("keeps the walking-skeleton create path behind the gateway boundary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          id: "new-run",
          case_id: "case-1",
          request_revision_id: "request-1",
          title: "Renew calibration service",
          status: "completed",
          current_phase: "intake complete",
          created_at: "2026-07-29T10:00:00Z",
          completed_at: "2026-07-29T10:00:01Z",
          events: [
            {
              event_id: "event-1",
              run_id: "new-run",
              sequence: 1,
              event_type: "run.created",
              status: "completed",
              summary: "Procurement run created",
              created_at: "2026-07-29T10:00:00Z",
            },
          ],
          artifacts: [
            {
              id: "artifact-1",
              kind: "requirements_specification",
              filename: "requirements.md",
              media_type: "text/markdown",
              size_bytes: 128,
              download_url: "/api/runs/new-run/artifacts/artifact-1",
            },
          ],
        }),
      }),
    );
    render(<App gateway={createFixtureGateway()} />);
    await screen.findByRole("heading", {
      name: "Replace warehouse label printers",
    });

    fireEvent.click(screen.getByRole("button", { name: "Create new request" }));
    fireEvent.change(screen.getByLabelText("Request title"), {
      target: { value: "Renew calibration service" },
    });
    fireEvent.change(screen.getByLabelText("Item or service"), {
      target: { value: "Calibration service" },
    });
    fireEvent.change(screen.getByLabelText("Need"), {
      target: { value: "Annual accredited calibration for 18 instruments" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    expect(
      await screen.findByRole("heading", {
        name: "Renew calibration service",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/runs/new-run/artifacts/artifact-1",
    );
  });
});
