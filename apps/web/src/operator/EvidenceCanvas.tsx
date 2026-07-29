import { KeyboardEvent, useMemo, useRef, useState } from "react";

import type { Candidate, EvidenceObservation, OperatorRun } from "./types";

type CanvasTab = "comparison" | "evidence" | "requirements";

const tabs: { id: CanvasTab; label: string }[] = [
  { id: "comparison", label: "Comparison" },
  { id: "evidence", label: "Evidence" },
  { id: "requirements", label: "Requirements" },
];

interface EvidenceCanvasProps {
  run: OperatorRun;
}

export function EvidenceCanvas({ run }: EvidenceCanvasProps) {
  const [activeTab, setActiveTab] = useState<CanvasTab>("comparison");
  const [selectedEvidenceId, setSelectedEvidenceId] = useState(
    run.evidence[0]?.id ?? "",
  );
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedEvidence = useMemo(
    () =>
      run.evidence.find((evidence) => evidence.id === selectedEvidenceId) ??
      run.evidence[0],
    [run.evidence, selectedEvidenceId],
  );

  function selectEvidence(evidenceId: string) {
    setSelectedEvidenceId(evidenceId);
    setActiveTab("evidence");
  }

  function handleTabKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    let nextIndex: number | undefined;
    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % tabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    }
    if (nextIndex === undefined) {
      return;
    }
    event.preventDefault();
    setActiveTab(tabs[nextIndex].id);
    tabRefs.current[nextIndex]?.focus();
  }

  return (
    <section className="evidence-canvas" aria-labelledby="canvas-heading">
      <div className="canvas-heading">
        <div>
          <p className="section-index">Evidence & decision</p>
          <h2 id="canvas-heading">Candidate ledger</h2>
        </div>
        <p>
          {run.evidence.length} observations ·{" "}
          {run.evidence.filter((item) => item.state === "conflicting").length}{" "}
          conflicts
        </p>
      </div>

      <div className="canvas-tabs" role="tablist" aria-label="Decision views">
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            id={`${tab.id}-tab`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`${tab.id}-panel`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "comparison" ? (
        <ComparisonPanel run={run} onSelectEvidence={selectEvidence} />
      ) : null}
      {activeTab === "evidence" ? (
        <EvidencePanel
          evidence={run.evidence}
          selected={selectedEvidence}
          onSelect={setSelectedEvidenceId}
        />
      ) : null}
      {activeTab === "requirements" ? (
        <div
          className="requirements-panel"
          id="requirements-panel"
          role="tabpanel"
          aria-labelledby="requirements-tab"
        >
          <header>
            <strong>Request revision {run.session.revision}</strong>
            <span>{run.requirements.length} typed criteria</span>
          </header>
          <dl>
            {run.requirements.map((requirement) => (
              <div key={requirement.id}>
                <dt>
                  {requirement.label}
                  {requirement.mandatory ? <span>Mandatory</span> : null}
                </dt>
                <dd>{requirement.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </section>
  );
}

function ComparisonPanel({
  run,
  onSelectEvidence,
}: {
  run: OperatorRun;
  onSelectEvidence: (evidenceId: string) => void;
}) {
  if (!run.candidates.length) {
    return (
      <div
        className="canvas-empty"
        id="comparison-panel"
        role="tabpanel"
        aria-labelledby="comparison-tab"
      >
        Comparison begins when candidate evidence is available.
      </div>
    );
  }

  return (
    <div
      className="comparison-panel"
      id="comparison-panel"
      role="tabpanel"
      aria-labelledby="comparison-tab"
    >
      <div className="comparison-scroll">
        <table>
          <caption className="sr-only">
            Candidate comparison with evidence coverage
          </caption>
          <thead>
            <tr>
              <th scope="col">Candidate</th>
              <th scope="col">Delivered cost</th>
              <th scope="col">Lead time</th>
              <th scope="col">Mandatory</th>
              <th scope="col">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {run.candidates.map((candidate) => (
              <CandidateRow
                key={candidate.id}
                candidate={candidate}
                evidence={run.evidence}
                onSelectEvidence={onSelectEvidence}
              />
            ))}
          </tbody>
        </table>
      </div>
      <div className="comparison-note">
        <span aria-hidden="true">i</span>
        <p>
          Ranking is withheld until every mandatory criterion is supported or
          explicitly unresolved. No confidence percentage is inferred.
        </p>
      </div>
    </div>
  );
}

function CandidateRow({
  candidate,
  evidence,
  onSelectEvidence,
}: {
  candidate: Candidate;
  evidence: EvidenceObservation[];
  onSelectEvidence: (evidenceId: string) => void;
}) {
  const firstInspectable = candidate.claims
    .flatMap((claim) => claim.observationIds)
    .find((id) => evidence.some((item) => item.id === id));

  return (
    <tr>
      <th scope="row">
        <strong>{candidate.name}</strong>
        <small>{candidate.location}</small>
      </th>
      <td>{candidate.totalCost}</td>
      <td>{candidate.leadTime}</td>
      <td>
        <span className={`evidence-state ${candidate.mandatoryStatus}`}>
          {candidate.mandatoryStatus}
        </span>
      </td>
      <td>
        {firstInspectable ? (
          <button
            className="evidence-link"
            type="button"
            onClick={() => onSelectEvidence(firstInspectable)}
          >
            {candidate.evidenceCoverage} verified
          </button>
        ) : (
          candidate.evidenceCoverage
        )}
      </td>
    </tr>
  );
}

function EvidencePanel({
  evidence,
  selected,
  onSelect,
}: {
  evidence: EvidenceObservation[];
  selected?: EvidenceObservation;
  onSelect: (evidenceId: string) => void;
}) {
  return (
    <div
      className="evidence-panel"
      id="evidence-panel"
      role="tabpanel"
      aria-labelledby="evidence-tab"
    >
      <div className="evidence-index" aria-label="Evidence observations">
        {evidence.map((item) => (
          <button
            key={item.id}
            type="button"
            className={selected?.id === item.id ? "selected" : ""}
            aria-pressed={selected?.id === item.id}
            onClick={() => onSelect(item.id)}
          >
            <span className={`state-mark ${item.state}`} aria-hidden="true" />
            <span>
              <strong>{item.title}</strong>
              <small>{item.sourceLabel}</small>
            </span>
          </button>
        ))}
      </div>
      {selected ? (
        <article className="evidence-detail" aria-live="polite">
          <header>
            <div>
              <p className="section-index">{selected.state}</p>
              <h3>{selected.title}</h3>
            </div>
            <strong>{selected.value}</strong>
          </header>
          <blockquote>{selected.excerpt}</blockquote>
          <dl>
            <div>
              <dt>Source</dt>
              <dd>
                <a href={selected.sourceUrl}>{selected.sourceLabel}</a>
              </dd>
            </div>
            <div>
              <dt>Observed</dt>
              <dd>{selected.observedAt}</dd>
            </div>
            <div>
              <dt>Content hash</dt>
              <dd>{selected.contentHash}</dd>
            </div>
          </dl>
        </article>
      ) : (
        <p className="canvas-empty">No evidence has been recorded yet.</p>
      )}
    </div>
  );
}
