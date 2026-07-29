import type { CreateRunInput } from "../api";

export type RunState =
  | "queued"
  | "running"
  | "paused"
  | "blocked"
  | "recovering"
  | "completed"
  | "failed";

export type WorkState =
  "remaining" | "active" | "completed" | "blocked" | "failed" | "recovering";

export interface SessionSummary {
  id: string;
  title: string;
  requestLabel: string;
  status: RunState;
  updatedLabel: string;
  revision: number;
}

export interface WorkProgress {
  completed: number;
  total: number;
  unit: string;
}

export interface WorkNode {
  id: string;
  label: string;
  kind: "phase" | "subagent" | "work" | "tool";
  status: WorkState;
  summary: string;
  progress?: WorkProgress;
  blocker?: string;
  retry?: {
    attempt: number;
    maxAttempts: number;
    classification: string;
    safeToRetry: boolean;
  };
  children?: WorkNode[];
}

export type EvidenceState =
  "supported" | "conflicting" | "unknown" | "operator-provided" | "calculated";

export interface Requirement {
  id: string;
  label: string;
  value: string;
  mandatory: boolean;
}

export interface CandidateClaim {
  requirementId: string;
  displayValue: string;
  state: EvidenceState;
  observationIds: string[];
}

export interface Candidate {
  id: string;
  name: string;
  location: string;
  totalCost: string;
  leadTime: string;
  evidenceCoverage: string;
  mandatoryStatus: "pass" | "review" | "fail";
  claims: CandidateClaim[];
}

export interface EvidenceObservation {
  id: string;
  candidateId: string;
  requirementId: string;
  title: string;
  value: string;
  state: EvidenceState;
  sourceLabel: string;
  sourceUrl: string;
  observedAt: string;
  excerpt: string;
  contentHash: string;
}

export interface Artifact {
  id: string;
  filename: string;
  kind: string;
  mediaType: string;
  sizeLabel: string;
  version: number;
  status: "ready" | "building" | "approved";
  downloadUrl: string;
  digest: string;
}

export interface ProposalVersion {
  version: number;
  recipient: string;
  subject: string;
  body: string;
  attachmentIds: string[];
  digest: string;
  createdLabel: string;
}

export interface Proposal {
  id: string;
  status: "draft" | "pending_approval" | "approved" | "rejected";
  riskClass: string;
  policyDecision: string;
  current: ProposalVersion;
  previous?: ProposalVersion;
  approvedBy?: string;
}

export interface OperatorCommand {
  id: string;
  mode: "queue" | "redirect";
  text: string;
  status: "queued" | "acknowledged" | "applied";
  createdLabel: string;
}

export interface OperatorRun {
  session: SessionSummary;
  summary: string;
  activePhase: string;
  policyLabel: string;
  elapsedLabel: string;
  progress: {
    completed: number;
    total: number;
    active: number;
    blockers: number;
  };
  workTree: WorkNode[];
  requirements: Requirement[];
  candidates: Candidate[];
  evidence: EvidenceObservation[];
  artifacts: Artifact[];
  proposal?: Proposal;
  commands: OperatorCommand[];
}

export interface ProposalEdit {
  recipient: string;
  subject: string;
  body: string;
}

export interface OperatorWorkbenchGateway {
  readonly sourceLabel: string;
  readonly isFixture: boolean;
  listSessions(): Promise<SessionSummary[]>;
  getRun(runId: string): Promise<OperatorRun>;
  subscribeRun?(
    runId: string,
    onProjection: (run: OperatorRun) => void,
  ): () => void;
  createRun(input: CreateRunInput): Promise<OperatorRun>;
  controlRun(runId: string, action: "pause" | "resume"): Promise<OperatorRun>;
  retryWork(runId: string, workId: string): Promise<OperatorRun>;
  sendCommand(
    runId: string,
    mode: "queue" | "redirect",
    text: string,
  ): Promise<OperatorRun>;
  saveProposal(runId: string, edit: ProposalEdit): Promise<OperatorRun>;
  decideProposal(
    runId: string,
    decision: "approve" | "reject",
  ): Promise<OperatorRun>;
}
