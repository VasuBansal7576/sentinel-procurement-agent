import { createRun as createWalkingSkeletonRun } from "../api";
import type { RunView } from "../api";
import type {
  AutonomyMode,
  OperatorRun,
  OperatorWorkbenchGateway,
  ProposalEdit,
  SessionSummary,
  WorkNode,
} from "./types";
import { DEFAULT_AUTONOMY_OPTIONS } from "./types";

const ACTIVE_RUN_ID = "run-industrial-printers";

function clone<T>(value: T): T {
  return structuredClone(value);
}

function activeFixture(): OperatorRun {
  return {
    session: {
      id: ACTIVE_RUN_ID,
      title: "Replace warehouse label printers",
      requestLabel: "12 industrial thermal printers",
      status: "running",
      updatedLabel: "just now",
      revision: 3,
    },
    summary:
      "Comparing serviceable 300 dpi printers after the operator added a five-year parts requirement.",
    runtimeDisclosure:
      "FIXTURE MODE: typed local projection, deterministic evidence, and fake email. Approval never sends.",
    honestyBanner:
      "Deterministic local suppliers · not live market data · approval records permission only and never sends",
    sourceBoundary:
      "Fixture projection boundary: local typed data, no live market research, no email send.",
    activePhase: "Supplier verification",
    autonomyMode: "ask_before_external",
    autonomyLabel: "Ask before external contact",
    autonomyOptions: DEFAULT_AUTONOMY_OPTIONS,
    policyLabel: "Ask before external contact · rev 4",
    elapsedLabel: "38m active",
    progress: { completed: 14, total: 21, active: 2, blockers: 1 },
    workTree: [
      {
        id: "phase-intake",
        label: "Request definition",
        kind: "phase",
        status: "completed",
        summary: "Revision 3 accepted; two prior findings retained.",
        progress: { completed: 4, total: 4, unit: "items" },
        children: [
          {
            id: "work-normalize",
            label: "Normalize requirements",
            kind: "work",
            status: "completed",
            summary: "8 typed requirements, 5 mandatory.",
          },
          {
            id: "work-invalidation",
            label: "Apply revision impact",
            kind: "work",
            status: "completed",
            summary: "11 observations retained; ranking invalidated.",
          },
        ],
      },
      {
        id: "phase-research",
        label: "Supplier verification",
        kind: "phase",
        status: "active",
        summary: "Two research branches are checking shortlisted suppliers.",
        progress: { completed: 7, total: 11, unit: "checks" },
        children: [
          {
            id: "agent-north",
            label: "North America supplier desk",
            kind: "subagent",
            status: "active",
            summary: "Isolated browser · search, fetch, evidence.read",
            progress: { completed: 3, total: 5, unit: "suppliers" },
            children: [
              {
                id: "work-zebra",
                label: "Verify Zebra ZT411",
                kind: "work",
                status: "completed",
                summary: "Specification and reseller price captured.",
              },
              {
                id: "work-sato",
                label: "Verify SATO CL4NX Plus",
                kind: "work",
                status: "active",
                summary: "Checking service coverage and lead time.",
              },
            ],
          },
          {
            id: "agent-service",
            label: "Serviceability research",
            kind: "subagent",
            status: "blocked",
            summary: "Parts-availability evidence needs a different source.",
            blocker: "Manufacturer support portal ended the browser session.",
            children: [
              {
                id: "work-honeywell",
                label: "Verify Honeywell PM45",
                kind: "work",
                status: "failed",
                summary: "Browser process ended after 2 successful captures.",
                retry: {
                  attempt: 1,
                  maxAttempts: 3,
                  classification: "TRANSIENT",
                  safeToRetry: true,
                },
              },
              {
                id: "work-service-term",
                label: "Confirm five-year parts term",
                kind: "work",
                status: "remaining",
                summary: "Waiting for the research branch to recover.",
              },
            ],
          },
        ],
      },
      {
        id: "phase-evaluate",
        label: "Evaluate & recommend",
        kind: "phase",
        status: "remaining",
        summary: "Starts when mandatory evidence gaps are resolved.",
        progress: { completed: 3, total: 6, unit: "outputs" },
        children: [
          {
            id: "work-comparison",
            label: "Recalculate comparison",
            kind: "work",
            status: "remaining",
            summary: "Queued behind supplier verification.",
          },
          {
            id: "work-rfq",
            label: "Prepare exact RFQ proposal",
            kind: "work",
            status: "remaining",
            summary: "Draft v3 is available for operator inspection.",
          },
        ],
      },
    ],
    requirements: [
      {
        id: "resolution",
        label: "Print resolution",
        value: "≥ 300 dpi",
        mandatory: true,
      },
      {
        id: "network",
        label: "Network",
        value: "Ethernet included",
        mandatory: true,
      },
      {
        id: "parts",
        label: "Parts availability",
        value: "5 years",
        mandatory: true,
      },
      {
        id: "lead",
        label: "Delivery",
        value: "≤ 6 weeks",
        mandatory: false,
      },
    ],
    candidates: [
      {
        id: "zebra",
        name: "Zebra ZT411",
        location: "Chicago reseller",
        totalCost: "$18,744",
        leadTime: "3–4 weeks",
        evidenceCoverage: "4 of 4",
        mandatoryStatus: "pass",
        claims: [
          {
            requirementId: "resolution",
            displayValue: "300 dpi",
            state: "supported",
            observationIds: ["ev-zebra-spec"],
          },
          {
            requirementId: "network",
            displayValue: "Included",
            state: "supported",
            observationIds: ["ev-zebra-spec"],
          },
          {
            requirementId: "parts",
            displayValue: "5 years",
            state: "supported",
            observationIds: ["ev-zebra-parts"],
          },
          {
            requirementId: "lead",
            displayValue: "3–4 weeks",
            state: "supported",
            observationIds: ["ev-zebra-price"],
          },
        ],
      },
      {
        id: "sato",
        name: "SATO CL4NX Plus",
        location: "National distributor",
        totalCost: "$20,196",
        leadTime: "5 weeks",
        evidenceCoverage: "3 of 4",
        mandatoryStatus: "review",
        claims: [
          {
            requirementId: "resolution",
            displayValue: "305 dpi",
            state: "supported",
            observationIds: ["ev-sato-spec"],
          },
          {
            requirementId: "network",
            displayValue: "Included",
            state: "supported",
            observationIds: ["ev-sato-spec"],
          },
          {
            requirementId: "parts",
            displayValue: "Unverified",
            state: "unknown",
            observationIds: [],
          },
          {
            requirementId: "lead",
            displayValue: "5 weeks",
            state: "supported",
            observationIds: ["ev-sato-lead"],
          },
        ],
      },
      {
        id: "honeywell",
        name: "Honeywell PM45",
        location: "Regional integrator",
        totalCost: "$17,988",
        leadTime: "4–7 weeks",
        evidenceCoverage: "2 of 4",
        mandatoryStatus: "review",
        claims: [
          {
            requirementId: "resolution",
            displayValue: "300 dpi",
            state: "supported",
            observationIds: ["ev-honeywell-spec"],
          },
          {
            requirementId: "network",
            displayValue: "Included",
            state: "supported",
            observationIds: ["ev-honeywell-spec"],
          },
          {
            requirementId: "parts",
            displayValue: "3 or 5 years",
            state: "conflicting",
            observationIds: ["ev-honeywell-parts"],
          },
          {
            requirementId: "lead",
            displayValue: "4–7 weeks",
            state: "conflicting",
            observationIds: ["ev-honeywell-lead"],
          },
        ],
      },
    ],
    evidence: [
      {
        id: "ev-zebra-spec",
        candidateId: "zebra",
        requirementId: "resolution",
        title: "Manufacturer specification",
        value: "300 dpi; Ethernet",
        state: "supported",
        sourceLabel: "Zebra product specification",
        sourceUrl: "https://www.zebra.com/",
        observedAt: "29 Jul · 14:16",
        excerpt:
          "Available print resolution: 203 dpi and 300 dpi. Connectivity includes 10/100 Ethernet.",
        contentHash: "sha256:8ca4…93f1",
      },
      {
        id: "ev-zebra-parts",
        candidateId: "zebra",
        requirementId: "parts",
        title: "Service parts commitment",
        value: "5 years",
        state: "supported",
        sourceLabel: "Authorized reseller service sheet",
        sourceUrl: "https://www.zebra.com/",
        observedAt: "29 Jul · 14:21",
        excerpt:
          "Parts and depot repair coverage available for five years from purchase.",
        contentHash: "sha256:7db2…1aa8",
      },
      {
        id: "ev-zebra-price",
        candidateId: "zebra",
        requirementId: "lead",
        title: "Reseller written quote",
        value: "$1,562 each; 3–4 weeks",
        state: "supported",
        sourceLabel: "Quote capture Q-4107",
        sourceUrl: "https://example.com/quotes/Q-4107",
        observedAt: "29 Jul · 14:24",
        excerpt:
          "Twelve units at $1,562; estimated ship window three to four weeks.",
        contentHash: "sha256:f718…e4d0",
      },
      {
        id: "ev-sato-spec",
        candidateId: "sato",
        requirementId: "resolution",
        title: "Manufacturer data sheet",
        value: "305 dpi; Ethernet",
        state: "supported",
        sourceLabel: "SATO CL4NX Plus data sheet",
        sourceUrl: "https://www.sato-global.com/",
        observedAt: "29 Jul · 14:31",
        excerpt: "305 dpi model with LAN interface installed as standard.",
        contentHash: "sha256:c304…88bd",
      },
      {
        id: "ev-sato-lead",
        candidateId: "sato",
        requirementId: "lead",
        title: "Distributor stock response",
        value: "5 weeks",
        state: "supported",
        sourceLabel: "Distributor catalog capture",
        sourceUrl: "https://example.com/distributor/sato",
        observedAt: "29 Jul · 14:36",
        excerpt: "Current factory fulfillment estimate is five weeks.",
        contentHash: "sha256:2621…32c7",
      },
      {
        id: "ev-honeywell-spec",
        candidateId: "honeywell",
        requirementId: "resolution",
        title: "Manufacturer specification",
        value: "300 dpi; Ethernet",
        state: "supported",
        sourceLabel: "Honeywell PM45 specification",
        sourceUrl: "https://automation.honeywell.com/",
        observedAt: "29 Jul · 14:39",
        excerpt: "300 dpi printhead configuration and Ethernet connectivity.",
        contentHash: "sha256:5d80…c981",
      },
      {
        id: "ev-honeywell-parts",
        candidateId: "honeywell",
        requirementId: "parts",
        title: "Conflicting service terms",
        value: "3 or 5 years",
        state: "conflicting",
        sourceLabel: "Integrator and manufacturer terms",
        sourceUrl: "https://automation.honeywell.com/",
        observedAt: "29 Jul · 14:43",
        excerpt:
          "Integrator lists three years; the manufacturer program page lists an optional five-year term.",
        contentHash: "sha256:6a93…0d75",
      },
      {
        id: "ev-honeywell-lead",
        candidateId: "honeywell",
        requirementId: "lead",
        title: "Delivery estimate conflict",
        value: "4–7 weeks",
        state: "conflicting",
        sourceLabel: "Regional integrator catalog",
        sourceUrl: "https://example.com/integrator/pm45",
        observedAt: "29 Jul · 14:45",
        excerpt:
          "Stock feed says four weeks; written sales note says up to seven.",
        contentHash: "sha256:b144…4fb0",
      },
    ],
    artifacts: [
      {
        id: "artifact-requirements",
        filename: "requirements-r3.md",
        kind: "Requirements",
        mediaType: "text/markdown",
        sizeLabel: "18 KB",
        version: 3,
        status: "ready",
        downloadUrl: "#requirements-r3",
        digest: "sha256:2b91…771a",
      },
      {
        id: "artifact-comparison",
        filename: "supplier-comparison-r2.xlsx",
        kind: "Workbook",
        mediaType:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sizeLabel: "146 KB",
        version: 2,
        status: "building",
        downloadUrl: "#comparison-r2",
        digest: "sha256:pending",
      },
      {
        id: "artifact-report",
        filename: "recommendation-r2.pdf",
        kind: "Report",
        mediaType: "application/pdf",
        sizeLabel: "884 KB",
        version: 2,
        status: "ready",
        downloadUrl: "#recommendation-r2",
        digest: "sha256:13ce…ab82",
      },
    ],
    proposal: {
      id: "proposal-rfq-001",
      status: "pending_approval",
      riskClass: "Controlled external communication",
      policyDecision: "Approval required · demo recipient allowlisted",
      previous: {
        version: 2,
        recipient: "procurement-demo@example.com",
        subject: "RFQ — twelve industrial label printers",
        body: "Please quote twelve 300 dpi networked label printers with standard warranty.",
        attachmentIds: ["artifact-requirements"],
        digest: "sha256:401c…a21e",
        createdLabel: "14:28",
      },
      current: {
        version: 3,
        recipient: "procurement-demo@example.com",
        subject: "RFQ — twelve serviceable industrial label printers",
        body: "Please quote twelve 300 dpi networked label printers. Confirm five-year parts availability, delivery within six weeks, warranty, and delivered pricing.",
        attachmentIds: ["artifact-requirements", "artifact-report"],
        digest: "sha256:780f…813b",
        createdLabel: "14:47",
      },
    },
    commands: [
      {
        id: "command-1",
        mode: "redirect",
        text: "Require five-year parts availability; preserve valid price evidence.",
        status: "applied",
        createdLabel: "14:46",
      },
      {
        id: "command-2",
        mode: "queue",
        text: "Prefer suppliers with a service depot in the Midwest.",
        status: "queued",
        createdLabel: "14:49",
      },
    ],
  };
}

function historyFixture(): OperatorRun {
  const run = activeFixture();
  run.session = {
    id: "run-gloves",
    title: "Source chemical-resistant gloves",
    requestLabel: "2,400 pairs · recurring",
    status: "completed",
    updatedLabel: "yesterday",
    revision: 2,
  };
  run.summary =
    "Completed with three compliant candidates and an approved recommendation.";
  run.activePhase = "Complete";
  run.elapsedLabel = "1h 12m";
  run.progress = { completed: 21, total: 21, active: 0, blockers: 0 };
  run.workTree = run.workTree.map((node) => markCompleted(node));
  run.proposal = undefined;
  run.commands = [];
  return run;
}

function blockedFixture(): OperatorRun {
  const run = activeFixture();
  run.session = {
    id: "run-forklifts",
    title: "Renew forklift maintenance",
    requestLabel: "4 sites · 36 vehicles",
    status: "paused",
    updatedLabel: "2 days ago",
    revision: 1,
  };
  run.summary =
    "Paused by operator while site coverage requirements are clarified.";
  run.activePhase = "Request definition";
  run.elapsedLabel = "16m active";
  run.progress = { completed: 3, total: 18, active: 0, blockers: 1 };
  run.proposal = undefined;
  run.commands = [];
  return run;
}

function markCompleted(node: WorkNode): WorkNode {
  return {
    ...node,
    status: "completed",
    blocker: undefined,
    retry: undefined,
    progress: node.progress
      ? { ...node.progress, completed: node.progress.total }
      : undefined,
    children: node.children?.map((child) => markCompleted(child)),
  };
}

function runViewAdapter(run: RunView): OperatorRun {
  return {
    session: {
      id: run.id,
      title: run.title,
      requestLabel: "New procurement request",
      status: run.status,
      updatedLabel: "just now",
      revision: 1,
    },
    summary: "Request normalized by the walking-skeleton API.",
    runtimeDisclosure:
      "FIXTURE MODE: walking-skeleton projection and fake external effects.",
    honestyBanner:
      "Deterministic local suppliers · not live market data · approval records permission only and never sends",
    activePhase: run.current_phase,
    autonomyMode: "ask_before_external",
    autonomyLabel: "Ask before external contact",
    autonomyOptions: DEFAULT_AUTONOMY_OPTIONS,
    policyLabel: "Ask before external contact · rev 1",
    elapsedLabel: run.completed_at ? "complete" : "new",
    progress: {
      completed: run.events.filter((event) => event.status === "completed")
        .length,
      total: run.events.length,
      active: run.status === "running" ? 1 : 0,
      blockers: run.status === "failed" ? 1 : 0,
    },
    workTree: [
      {
        id: `${run.id}-activity`,
        label: "Walking-skeleton activity",
        kind: "phase",
        status: run.status === "completed" ? "completed" : "active",
        summary: `${run.events.length} durable events recorded.`,
        children: run.events.map((event) => ({
          id: event.event_id,
          label: event.summary,
          kind: "work",
          status: event.status === "completed" ? "completed" : "active",
          summary: event.event_type,
        })),
      },
    ],
    requirements: [],
    candidates: [],
    evidence: [],
    artifacts: run.artifacts.map((artifact) => ({
      id: artifact.id,
      filename: artifact.filename,
      kind: artifact.kind,
      mediaType: artifact.media_type,
      sizeLabel: `${artifact.size_bytes} bytes`,
      version: 1,
      status: "ready",
      downloadUrl: artifact.download_url,
      digest: "Digest available from artifact projection",
    })),
    commands: [],
  };
}

function setNodeStatus(
  nodes: WorkNode[],
  workId: string,
  status: WorkNode["status"],
): WorkNode[] {
  return nodes.map((node) => ({
    ...node,
    status: node.id === workId ? status : node.status,
    retry: node.id === workId ? undefined : node.retry,
    children: node.children
      ? setNodeStatus(node.children, workId, status)
      : undefined,
  }));
}

export function createFixtureGateway(): OperatorWorkbenchGateway {
  const runs = new Map(
    [activeFixture(), historyFixture(), blockedFixture()].map((run) => [
      run.session.id,
      run,
    ]),
  );

  function getMutable(runId: string): OperatorRun {
    const run = runs.get(runId);
    if (!run) {
      throw new Error("That durable session is no longer available.");
    }
    return run;
  }

  return {
    sourceLabel: "Fixture projection · deterministic local data · no external effects",
    isFixture: true,
    async listSessions(): Promise<SessionSummary[]> {
      return Array.from(runs.values()).map((run) => clone(run.session));
    },
    async getRun(runId) {
      return clone(getMutable(runId));
    },
    subscribeRun() {
      return () => undefined;
    },
    async createRun(input) {
      const created = runViewAdapter(await createWalkingSkeletonRun(input));
      runs.set(created.session.id, created);
      return clone(created);
    },
    async controlRun(runId, action) {
      const run = getMutable(runId);
      run.session.status = action === "pause" ? "paused" : "running";
      run.session.updatedLabel = "just now";
      return clone(run);
    },
    async setAutonomy(runId, mode: AutonomyMode) {
      const run = getMutable(runId);
      const option =
        DEFAULT_AUTONOMY_OPTIONS.find((entry) => entry.value === mode) ??
        DEFAULT_AUTONOMY_OPTIONS[1];
      run.autonomyMode = mode;
      run.autonomyLabel = option.label;
      run.policyLabel = `${option.label} · rev ${run.session.revision}`;
      run.session.updatedLabel = "just now";
      if (mode === "research_only") {
        run.proposal = undefined;
      }
      return clone(run);
    },
    async retryWork(runId, workId) {
      const run = getMutable(runId);
      run.workTree = setNodeStatus(run.workTree, workId, "recovering");
      run.session.status = "recovering";
      run.progress.active += 1;
      run.progress.blockers = Math.max(0, run.progress.blockers - 1);
      return clone(run);
    },
    async sendCommand(runId, mode, commandText) {
      const run = getMutable(runId);
      run.commands.unshift({
        id: `command-${run.commands.length + 1}`,
        mode,
        text: commandText,
        status: mode === "queue" ? "queued" : "acknowledged",
        createdLabel: "just now",
      });
      run.session.updatedLabel = "just now";
      if (mode === "redirect") {
        run.session.revision += 1;
      }
      return clone(run);
    },
    async saveProposal(runId, edit: ProposalEdit) {
      const run = getMutable(runId);
      if (!run.proposal) {
        throw new Error("This run has no editable proposal.");
      }
      const previous = run.proposal.current;
      run.proposal.previous = previous;
      run.proposal.current = {
        ...previous,
        ...edit,
        version: previous.version + 1,
        digest: `sha256:fixture-v${previous.version + 1}`,
        createdLabel: "just now",
      };
      run.proposal.status = "pending_approval";
      run.proposal.approvedBy = undefined;
      return clone(run);
    },
    async decideProposal(runId, decision) {
      const run = getMutable(runId);
      if (!run.proposal) {
        throw new Error("This run has no proposal to decide.");
      }
      run.proposal.status = decision === "approve" ? "approved" : "rejected";
      run.proposal.approvedBy =
        decision === "approve" ? "Current operator" : undefined;
      if (decision === "approve") {
        run.proposal.canExecute = true;
        run.proposal.executionLabel =
          "Execute approved RFQ (fake provider only)";
      }
      return clone(run);
    },
    async executeApprovedEmail(runId) {
      const run = getMutable(runId);
      if (!run.proposal || run.proposal.status !== "approved") {
        throw new Error("Approve the exact proposal before execution.");
      }
      run.proposal.canExecute = false;
      run.proposal.executionLabel = "Executed on fake provider · no real send";
      run.session.updatedLabel = "just now";
      return clone(run);
    },
  };
}
