import type { OperatorRun } from "./types";

/** One-glance operator sentence for the status hero. */
export function buildStatusLead(run: OperatorRun): string {
  const { session, progress, proposal, candidates, summary } = run;
  const blockers =
    progress.blockers > 0
      ? `${progress.blockers} blocker${progress.blockers === 1 ? "" : "s"}`
      : "0 blockers";

  if (session.status === "blocked" || session.status === "failed") {
    return `${summary} · ${blockers} · use Retry from checkpoint when safe.`;
  }
  if (session.status === "paused") {
    return `Run paused at a safe boundary · ${progress.completed} of ${progress.total} work items done · ${blockers}.`;
  }
  if (session.status === "recovering") {
    return `Recovering from checkpoint · ${progress.completed} of ${progress.total} work items · ${blockers}.`;
  }
  if (proposal?.status === "pending_approval") {
    const top = candidates[0]?.name;
    return top
      ? `Comparison ready · recommended ${top} · approve the exact RFQ — nothing is sent on approve.`
      : `Comparison ready · approve the exact RFQ — nothing is sent on approve.`;
  }
  if (proposal?.status === "approved" && session.status === "completed") {
    return `Run finished · RFQ approved (no send on approve) · downloads are ready.`;
  }
  if (session.status === "completed") {
    return summary || "Run finished. Review outputs and any pending decision.";
  }
  if (session.status === "queued") {
    return "Run is queued · waiting for the worker to start durable execution.";
  }

  const active = progress.active > 0 ? `${progress.active} active` : "working";
  return `${summary} · ${progress.completed} of ${progress.total} work items · ${active} · ${blockers}.`;
}

export function buildStatusEyebrow(run: OperatorRun): string {
  if (run.proposal?.status === "pending_approval") {
    return "Needs your decision";
  }
  if (run.session.status === "completed") {
    return "Complete";
  }
  if (run.session.status === "paused") {
    return "Paused";
  }
  if (run.session.status === "blocked" || run.session.status === "failed") {
    return "Needs attention";
  }
  if (run.session.status === "recovering") {
    return "Recovering";
  }
  return "Active run";
}

export type WorkbenchMode = "running" | "approval" | "done" | "attention";

export function resolveWorkbenchMode(run: OperatorRun): WorkbenchMode {
  if (
    run.session.status === "blocked" ||
    run.session.status === "failed" ||
    run.session.status === "recovering"
  ) {
    return "attention";
  }
  if (run.proposal?.status === "pending_approval") {
    return "approval";
  }
  if (run.session.status === "completed") {
    return "done";
  }
  return "running";
}
