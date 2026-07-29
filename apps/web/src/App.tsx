import { FormEvent, useEffect, useState } from "react";

import { createRun, type CreateRunInput, type RunEvent, type RunView } from "./api";

const initialRequest: CreateRunInput = {
  title: "",
  item_name: "",
  description: "",
  quantity: "1",
  unit: "each",
};

const streamedEventTypes = [
  "run.created",
  "request.normalized",
  "artifact.created",
  "run.completed",
];

function mergeEvent(run: RunView, event: RunEvent): RunView {
  if (run.events.some((existing) => existing.event_id === event.event_id)) {
    return run;
  }
  return {
    ...run,
    events: [...run.events, event].sort((left, right) => left.sequence - right.sequence),
  };
}

export function App() {
  const [request, setRequest] = useState<CreateRunInput>(initialRequest);
  const [run, setRun] = useState<RunView | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const runId = run?.id;

  useEffect(() => {
    if (!runId || typeof EventSource === "undefined") {
      return;
    }
    const stream = new EventSource(`/api/runs/${runId}/events`);
    const receive = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as RunEvent;
      setRun((current) => (current ? mergeEvent(current, event) : current));
    };
    streamedEventTypes.forEach((eventType) => stream.addEventListener(eventType, receive));
    return () => stream.close();
  }, [runId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      setRun(await createRun(request));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unexpected request failure.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="workbench">
      <header className="topbar">
        <div>
          <p className="eyebrow">Sentinel</p>
          <h1>Procurement control room</h1>
        </div>
        <div className="environment">
          <span aria-hidden="true" />
          Credential-free development
        </div>
      </header>

      <main className="workspace">
        <section className="intake" aria-labelledby="intake-heading">
          <p className="section-index">01 / Intake</p>
          <h2 id="intake-heading">Start with the need.</h2>
          <p className="section-copy">
            Describe any product or service. Sentinel converts it into a versioned
            procurement request before research begins.
          </p>

          <form onSubmit={handleSubmit}>
            <label>
              Request title
              <input
                required
                minLength={3}
                value={request.title}
                onChange={(event) =>
                  setRequest({ ...request, title: event.target.value })
                }
                placeholder="Replace warehouse label printers"
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
                placeholder="Industrial label printer"
              />
            </label>
            <label>
              Description
              <textarea
                required
                minLength={3}
                rows={4}
                value={request.description}
                onChange={(event) =>
                  setRequest({ ...request, description: event.target.value })
                }
                placeholder="Networked thermal printer, 300 dpi, compatible with..."
              />
            </label>
            <div className="field-pair">
              <label>
                Quantity
                <input
                  required
                  type="number"
                  min="0.0001"
                  step="any"
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
            {error ? <p className="error">{error}</p> : null}
            <button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating run…" : "Create procurement run"}
            </button>
          </form>
        </section>

        <section className="run-panel" aria-labelledby="run-heading">
          <div className="run-heading">
            <div>
              <p className="section-index">02 / Observable run</p>
              <h2 id="run-heading">{run?.title ?? "No active run"}</h2>
            </div>
            <span className={`run-state ${run?.status ?? "idle"}`} role="status">
              {run?.status ?? "waiting"}
            </span>
          </div>

          {run ? (
            <>
              <dl className="run-facts">
                <div>
                  <dt>Phase</dt>
                  <dd>{run.current_phase}</dd>
                </div>
                <div>
                  <dt>Revision</dt>
                  <dd>01</dd>
                </div>
                <div>
                  <dt>Events</dt>
                  <dd>{run.events.length.toString().padStart(2, "0")}</dd>
                </div>
              </dl>
              <ol className="event-list" aria-label="Run activity">
                {run.events.map((event) => (
                  <li key={event.event_id}>
                    <span className="event-sequence">
                      {event.sequence.toString().padStart(2, "0")}
                    </span>
                    <div>
                      <strong>{event.summary}</strong>
                      <small>{event.event_type}</small>
                    </div>
                    <span className="event-status">{event.status}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <div className="empty-state">
              <span>⌁</span>
              <p>Submit a request to create a typed run and inspect its event trail.</p>
            </div>
          )}
        </section>

        <aside className="artifact-rail" aria-labelledby="artifact-heading">
          <p className="section-index">03 / Output</p>
          <h2 id="artifact-heading">Artifacts</h2>
          {run?.artifacts.length ? (
            <ul>
              {run.artifacts.map((artifact) => (
                <li key={artifact.id}>
                  <span>MD</span>
                  <div>
                    <strong>{artifact.filename}</strong>
                    <small>{artifact.size_bytes} bytes</small>
                  </div>
                  <a href={artifact.download_url}>Download</a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rail-empty">Generated files will collect here.</p>
          )}
        </aside>
      </main>
    </div>
  );
}
