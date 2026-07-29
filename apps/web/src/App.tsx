import { FormEvent, useCallback, useEffect, useState } from "react";

import type { CreateRunInput } from "./api";
import { ActionRail } from "./operator/ActionRail";
import { CommandComposer } from "./operator/CommandComposer";
import { EvidenceCanvas } from "./operator/EvidenceCanvas";
import { createApiFirstGateway } from "./operator/httpGateway";
import type {
  OperatorRun,
  OperatorWorkbenchGateway,
  SessionSummary,
} from "./operator/types";
import { WorkTree } from "./operator/WorkTree";

const ACTIVE_RUN_STORAGE_KEY = "sentinel.active-run-id";

const initialRequest: CreateRunInput = {
  title: "",
  item_name: "",
  description: "",
  quantity: "1",
  unit: "each",
};

interface AppProps {
  gateway?: OperatorWorkbenchGateway;
}

export function App({ gateway }: AppProps) {
  const [workbenchGateway] = useState(() => gateway ?? createApiFirstGateway());
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [run, setRun] = useState<OperatorRun | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [request, setRequest] = useState<CreateRunInput>(initialRequest);

  const applyRun = useCallback((nextRun: OperatorRun) => {
    setRun(nextRun);
    setSessions((current) => {
      const remaining = current.filter(
        (session) => session.id !== nextRun.session.id,
      );
      return [nextRun.session, ...remaining];
    });
    window.localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, nextRun.session.id);
  }, []);

  const loadWorkbench = useCallback(async () => {
    setError(null);
    try {
      const nextSessions = await workbenchGateway.listSessions();
      setSessions(nextSessions);
      const restoredId = window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY);
      const selectedId =
        nextSessions.find((session) => session.id === restoredId)?.id ??
        nextSessions[0]?.id;
      if (selectedId) {
        setRun(await workbenchGateway.getRun(selectedId));
        window.localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, selectedId);
      } else {
        setRun(null);
      }
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The durable session index could not be loaded.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [workbenchGateway]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadWorkbench(), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkbench]);

  useEffect(() => {
    if (!run?.session.id || !workbenchGateway.subscribeRun) {
      return;
    }
    return workbenchGateway.subscribeRun(run.session.id, applyRun);
  }, [applyRun, run?.session.id, workbenchGateway]);

  async function selectSession(runId: string) {
    setIsLoading(true);
    setError(null);
    try {
      const selected = await workbenchGateway.getRun(runId);
      setRun(selected);
      window.localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, runId);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The run could not be opened.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  function retryLoad() {
    setIsLoading(true);
    void loadWorkbench();
  }

  async function mutate(operation: () => Promise<OperatorRun>): Promise<void> {
    setIsMutating(true);
    setError(null);
    try {
      applyRun(await operation());
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The operator command was not acknowledged.",
      );
    } finally {
      setIsMutating(false);
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await mutate(() => workbenchGateway.createRun(request));
    setRequest(initialRequest);
    setIsCreating(false);
  }

  const controlAction = run?.session.status === "paused" ? "resume" : "pause";

  return (
    <div className="operator-shell">
      <a className="skip-link" href="#run-workspace">
        Skip to active run
      </a>

      <aside className="session-sidebar" aria-labelledby="session-heading">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <div>
            <p>Sentinel</p>
            <span>Procurement operations</span>
          </div>
        </div>

        <div className="session-heading">
          <div>
            <p className="section-index">Durable sessions</p>
            <h2 id="session-heading">Run history</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label={
              isCreating ? "Close new request form" : "Create new request"
            }
            aria-expanded={isCreating}
            onClick={() => setIsCreating((current) => !current)}
          >
            {isCreating ? "×" : "+"}
          </button>
        </div>

        {isCreating ? (
          <form className="new-request-form" onSubmit={handleCreate}>
            <label>
              Request title
              <input
                required
                minLength={3}
                value={request.title}
                onChange={(event) =>
                  setRequest({ ...request, title: event.target.value })
                }
                placeholder="Renew field equipment"
              />
            </label>
            <label>
              Item or service
              <input
                required
                minLength={2}
                value={request.item_name}
                onChange={(event) =>
                  setRequest({ ...request, item_name: event.target.value })
                }
                placeholder="Equipment or service"
              />
            </label>
            <label>
              Need
              <textarea
                required
                minLength={3}
                rows={3}
                value={request.description}
                onChange={(event) =>
                  setRequest({ ...request, description: event.target.value })
                }
              />
            </label>
            <div className="field-pair">
              <label>
                Quantity
                <input
                  required
                  min="0.0001"
                  step="any"
                  type="number"
                  value={request.quantity}
                  onChange={(event) =>
                    setRequest({ ...request, quantity: event.target.value })
                  }
                />
              </label>
              <label>
                Unit
                <input
                  required
                  value={request.unit}
                  onChange={(event) =>
                    setRequest({ ...request, unit: event.target.value })
                  }
                />
              </label>
            </div>
            <button type="submit" disabled={isMutating}>
              {isMutating ? "Starting…" : "Start run"}
            </button>
          </form>
        ) : null}

        <nav className="session-list" aria-label="Procurement sessions">
          {sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              className={run?.session.id === session.id ? "selected" : ""}
              aria-current={run?.session.id === session.id ? "page" : undefined}
              onClick={() => void selectSession(session.id)}
            >
              <span
                className={`session-state ${session.status}`}
                aria-hidden="true"
              />
              <span>
                <strong>{session.title}</strong>
                <small>{session.requestLabel}</small>
              </span>
              <span className="session-meta">
                r{session.revision} · {session.updatedLabel}
              </span>
            </button>
          ))}
        </nav>

        <div className="source-disclosure">
          <span aria-hidden="true">◇</span>
          <p>
            <strong>Projection source</strong>
            {workbenchGateway.sourceLabel}
          </p>
        </div>
      </aside>

      <main id="run-workspace" className="run-workspace" tabIndex={-1}>
        {error ? (
          <div className="load-failure" role="alert">
            <div>
              <strong>Workbench data unavailable</strong>
              <p>{error}</p>
            </div>
            <button type="button" onClick={retryLoad}>
              Retry session load
            </button>
          </div>
        ) : null}

        {isLoading && !run ? (
          <div className="workbench-loading" role="status">
            Restoring durable session…
          </div>
        ) : run ? (
          <>
            <header className="run-header">
              <div className="run-title">
                <div className="run-breadcrumb">
                  <span>Run history</span>
                  <span aria-hidden="true">/</span>
                  <span>{run.session.id}</span>
                </div>
                <h1>{run.session.title}</h1>
                <p>{run.summary}</p>
              </div>
              <div className="run-controls">
                <span
                  className={`run-status ${run.session.status}`}
                  role="status"
                >
                  <span aria-hidden="true" />
                  {run.session.status}
                </span>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={
                    isMutating ||
                    !["running", "paused", "recovering"].includes(
                      run.session.status,
                    )
                  }
                  onClick={() =>
                    void mutate(() =>
                      workbenchGateway.controlRun(
                        run.session.id,
                        controlAction,
                      ),
                    )
                  }
                >
                  {controlAction === "pause" ? "Pause run" : "Resume run"}
                </button>
              </div>
              <dl className="run-facts">
                <div>
                  <dt>Active phase</dt>
                  <dd>{run.activePhase}</dd>
                </div>
                <div>
                  <dt>Request</dt>
                  <dd>Revision {run.session.revision}</dd>
                </div>
                <div>
                  <dt>Policy</dt>
                  <dd>{run.policyLabel}</dd>
                </div>
                <div>
                  <dt>Elapsed</dt>
                  <dd>{run.elapsedLabel}</dd>
                </div>
                <div>
                  <dt>Progress</dt>
                  <dd>
                    {run.progress.completed} of {run.progress.total} work items
                  </dd>
                </div>
                <div>
                  <dt>Attention</dt>
                  <dd>
                    {run.progress.active} active · {run.progress.blockers}{" "}
                    blocker
                    {run.progress.blockers === 1 ? "" : "s"}
                  </dd>
                </div>
              </dl>
            </header>

            <div className="workbench-grid" aria-busy={isMutating}>
              <section
                className="work-tree-panel"
                aria-labelledby="tree-heading"
              >
                <div className="panel-heading">
                  <div>
                    <p className="section-index">Execution structure</p>
                    <h2 id="tree-heading">Work tree</h2>
                  </div>
                  <span>Glance → inspect</span>
                </div>
                <div className="tree-legend" aria-label="Work state legend">
                  {(
                    ["active", "completed", "remaining", "blocked"] as const
                  ).map((state) => (
                    <span key={state}>
                      <i className={`state-mark ${state}`} aria-hidden="true" />
                      {state}
                    </span>
                  ))}
                </div>
                <WorkTree
                  key={run.session.id}
                  nodes={run.workTree}
                  onRetry={(workId) =>
                    mutate(() =>
                      workbenchGateway.retryWork(run.session.id, workId),
                    )
                  }
                />
              </section>

              <EvidenceCanvas key={run.session.id} run={run} />

              <ActionRail
                key={`${run.session.id}-${run.proposal?.current.version ?? 0}`}
                run={run}
                onSaveProposal={(edit) =>
                  mutate(() =>
                    workbenchGateway.saveProposal(run.session.id, edit),
                  )
                }
                onDecideProposal={(decision) =>
                  mutate(() =>
                    workbenchGateway.decideProposal(run.session.id, decision),
                  )
                }
              />
            </div>

            <CommandComposer
              key={run.session.id}
              commands={run.commands}
              onSend={(mode, text) =>
                mutate(() =>
                  workbenchGateway.sendCommand(run.session.id, mode, text),
                )
              }
            />
          </>
        ) : (
          <div className="workbench-loading">
            No durable sessions yet. Start a procurement run from the session
            rail.
          </div>
        )}
      </main>
    </div>
  );
}
