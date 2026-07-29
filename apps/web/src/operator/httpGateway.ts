import type { CreateRunInput } from "../api";
import { createFixtureGateway } from "./fixtureGateway";
import type {
  OperatorRun,
  OperatorWorkbenchGateway,
  ProposalEdit,
  SessionSummary,
} from "./types";

class ApiUnavailableError extends Error {}

const projectionEventTypes = [
  "run.status_changed",
  "run.redirected",
  "run.recovery_available",
  "work.started",
  "work.completed",
  "work.failed",
  "work.invalidated",
  "work.retry_requested",
  "subagent.started",
  "subagent.completed",
  "subagent.failed",
  "tool.completed",
  "operator.message_applied",
  "proposal.edited",
  "proposal.approved",
  "proposal.rejected",
] as const;

function commandId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `command-${Date.now()}`;
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new ApiUnavailableError(
      error instanceof Error ? error.message : "Sentinel API is unavailable.",
    );
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    if ([502, 503, 504].includes(response.status)) {
      throw new ApiUnavailableError(
        body?.detail ?? "Sentinel API is unavailable.",
      );
    }
    throw new Error(body?.detail ?? `Sentinel API returned ${response.status}.`);
  }
  return (await response.json()) as T;
}

function jsonRequest(method: string, body: object): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function createHttpGateway(): OperatorWorkbenchGateway {
  const gateway: OperatorWorkbenchGateway = {
    sourceLabel: "Durable API projection · fake providers · no approval dispatch",
    isFixture: false,
    listSessions() {
      return requestJson<SessionSummary[]>("/api/operator/sessions");
    },
    getRun(runId) {
      return requestJson<OperatorRun>(`/api/operator/runs/${runId}`);
    },
    subscribeRun(runId, onProjection) {
      if (typeof EventSource === "undefined") {
        return () => undefined;
      }
      const source = new EventSource(`/api/runs/${runId}/events`);
      const refresh = () => {
        void gateway.getRun(runId).then(onProjection).catch(() => undefined);
      };
      source.onmessage = refresh;
      for (const eventType of projectionEventTypes) {
        source.addEventListener(eventType, refresh);
      }
      return () => source.close();
    },
    createRun(input: CreateRunInput) {
      return requestJson<OperatorRun>(
        "/api/operator/runs",
        jsonRequest("POST", input),
      );
    },
    controlRun(runId, action) {
      return requestJson<OperatorRun>(
        `/api/operator/runs/${runId}/controls/${action}`,
        jsonRequest("POST", {
          command_id: commandId(),
          reason:
            action === "pause"
              ? "Operator paused the run"
              : "Operator resumed the run",
        }),
      );
    },
    retryWork(runId, workId) {
      return requestJson<OperatorRun>(
        `/api/operator/runs/${runId}/work/${workId}/retry`,
        jsonRequest("POST", { command_id: commandId() }),
      );
    },
    sendCommand(runId, mode, text) {
      if (mode === "redirect") {
        return requestJson<OperatorRun>(
          `/api/operator/runs/${runId}/redirect`,
          jsonRequest("POST", {
            command_id: commandId(),
            text,
            changed_dependencies: ["request:requirements"],
          }),
        );
      }
      return requestJson<OperatorRun>(
        `/api/operator/runs/${runId}/messages`,
        jsonRequest("POST", {
          command_id: commandId(),
          message_id: commandId(),
          text,
        }),
      );
    },
    saveProposal(runId, edit: ProposalEdit) {
      return requestJson<OperatorRun>(
        `/api/operator/runs/${runId}/proposal`,
        jsonRequest("PUT", edit),
      );
    },
    decideProposal(runId, decision) {
      return requestJson<OperatorRun>(
        `/api/operator/runs/${runId}/proposal/decision`,
        jsonRequest("POST", {
          decision,
          approver_id: commandId(),
        }),
      );
    },
  };
  return gateway;
}

export function createApiFirstGateway(
  fallback: OperatorWorkbenchGateway = createFixtureGateway(),
): OperatorWorkbenchGateway {
  const api = createHttpGateway();
  let active = api;
  let apiConfirmed = false;

  async function withAvailabilityFallback<T>(
    operation: (gateway: OperatorWorkbenchGateway) => Promise<T>,
    confirmsAvailability = false,
  ): Promise<T> {
    try {
      const result = await operation(active);
      if (active === api && confirmsAvailability) {
        apiConfirmed = true;
      }
      return result;
    } catch (error) {
      if (
        active === api &&
        !apiConfirmed &&
        error instanceof ApiUnavailableError
      ) {
        active = fallback;
        return operation(active);
      }
      throw error;
    }
  }

  return {
    get sourceLabel() {
      return active.sourceLabel;
    },
    get isFixture() {
      return active.isFixture;
    },
    listSessions() {
      return withAvailabilityFallback(
        (gateway) => gateway.listSessions(),
        true,
      );
    },
    getRun(runId) {
      return withAvailabilityFallback((gateway) => gateway.getRun(runId));
    },
    subscribeRun(runId, onProjection) {
      return active.subscribeRun?.(runId, onProjection) ?? (() => undefined);
    },
    createRun(input) {
      return withAvailabilityFallback((gateway) => gateway.createRun(input));
    },
    controlRun(runId, action) {
      return withAvailabilityFallback((gateway) =>
        gateway.controlRun(runId, action),
      );
    },
    retryWork(runId, workId) {
      return withAvailabilityFallback((gateway) =>
        gateway.retryWork(runId, workId),
      );
    },
    sendCommand(runId, mode, text) {
      return withAvailabilityFallback((gateway) =>
        gateway.sendCommand(runId, mode, text),
      );
    },
    saveProposal(runId, edit) {
      return withAvailabilityFallback((gateway) =>
        gateway.saveProposal(runId, edit),
      );
    },
    decideProposal(runId, decision) {
      return withAvailabilityFallback((gateway) =>
        gateway.decideProposal(runId, decision),
      );
    },
  };
}
