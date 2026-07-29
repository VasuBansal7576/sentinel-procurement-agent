import { afterEach, describe, expect, it, vi } from "vitest";

import { createApiFirstGateway, createHttpGateway } from "./httpGateway";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HTTP operator gateway", () => {
  it("maps sessions, intake, controls, messages, redirects, and decisions", async () => {
    const projection = {
      session: { id: "run-1" },
      workTree: [],
      artifacts: [],
      candidates: [],
      evidence: [],
      requirements: [],
      commands: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([{ id: "run-1" }]))
      .mockImplementation(() => Promise.resolve(jsonResponse(projection)));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" });
    const gateway = createHttpGateway();

    await gateway.listSessions();
    await gateway.createRun({
      title: "Renew service",
      item_name: "Calibration",
      description: "Annual service",
      quantity: "10",
      unit: "instrument",
    });
    await gateway.controlRun("run-1", "pause");
    await gateway.sendCommand("run-1", "queue", "Preserve evidence");
    await gateway.sendCommand("run-1", "redirect", "Require twenty days");
    await gateway.decideProposal("run-1", "approve");

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/operator/sessions",
      "/api/operator/runs",
      "/api/operator/runs/run-1/controls/pause",
      "/api/operator/runs/run-1/messages",
      "/api/operator/runs/run-1/redirect",
      "/api/operator/runs/run-1/proposal/decision",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toMatchObject({
      text: "Require twenty days",
      changed_dependencies: ["request:scope"],
    });
    expect(JSON.parse(fetchMock.mock.calls[5][1].body)).toMatchObject({
      decision: "approve",
    });
  });

  it("uses the explicit fixture only when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const gateway = createApiFirstGateway();

    const sessions = await gateway.listSessions();

    expect(sessions.length).toBeGreaterThan(0);
    expect(gateway.isFixture).toBe(true);
    expect(gateway.sourceLabel).toContain("fixture");
  });

  it("does not hide an acknowledged command conflict behind demo data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "unsafe retry" }, 409)),
    );
    const gateway = createApiFirstGateway();

    await expect(gateway.retryWork("run-1", "work-1")).rejects.toThrow(
      "unsafe retry",
    );
    expect(gateway.isFixture).toBe(false);
  });

  it("does not switch to demo data after the API session index succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ detail: "Run not found" }, 404));
    vi.stubGlobal("fetch", fetchMock);
    const gateway = createApiFirstGateway();

    await gateway.listSessions();

    await expect(gateway.getRun("missing")).rejects.toThrow("Run not found");
    expect(gateway.isFixture).toBe(false);
  });

  it("does not treat a missing API resource as infrastructure unavailability", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Run not found" }, 404)),
    );
    const gateway = createApiFirstGateway();

    await expect(gateway.getRun("missing")).rejects.toThrow("Run not found");
    expect(gateway.isFixture).toBe(false);
  });
});
