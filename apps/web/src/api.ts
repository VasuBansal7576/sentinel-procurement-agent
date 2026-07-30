export type RunStatus = "running" | "completed" | "failed";

export interface RunEvent {
  event_id: string;
  run_id: string;
  sequence: number;
  event_type: string;
  status: string;
  summary: string;
  created_at: string;
}

export interface ArtifactSummary {
  id: string;
  kind: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  download_url: string;
}

export interface RunView {
  id: string;
  case_id: string;
  request_revision_id: string;
  title: string;
  status: RunStatus;
  current_phase: string;
  created_at: string;
  completed_at: string | null;
  events: RunEvent[];
  artifacts: ArtifactSummary[];
}

export type AutonomyMode =
  | "research_only"
  | "ask_before_external"
  | "approve_and_hold";

export interface CreateRunInput {
  title: string;
  item_name: string;
  description: string;
  quantity: string;
  unit: string;
  autonomy_mode: AutonomyMode;
}

export async function createRun(input: CreateRunInput): Promise<RunView> {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? "The procurement run could not be created.");
  }
  return (await response.json()) as RunView;
}
