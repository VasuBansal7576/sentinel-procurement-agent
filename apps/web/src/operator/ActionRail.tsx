import { FormEvent, KeyboardEvent, useRef, useState } from "react";

import type { OperatorRun, ProposalEdit } from "./types";

interface ActionRailProps {
  run: OperatorRun;
  /** decision-first puts the RFQ card above the stage for approval mode */
  layout?: "rail" | "decision-first";
  onSaveProposal: (edit: ProposalEdit) => Promise<void>;
  onDecideProposal: (decision: "approve" | "reject") => Promise<void>;
  onExecuteProposal?: () => Promise<void>;
}

export function ActionRail({
  run,
  layout = "rail",
  onSaveProposal,
  onDecideProposal,
  onExecuteProposal,
}: ActionRailProps) {
  const [proposalView, setProposalView] = useState<"preview" | "diff">(
    "preview",
  );
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [edit, setEdit] = useState<ProposalEdit>(() => ({
    recipient: run.proposal?.current.recipient ?? "",
    subject: run.proposal?.current.subject ?? "",
    body: run.proposal?.current.body ?? "",
  }));
  const proposal = run.proposal;
  const proposalTabs = useRef<Array<HTMLButtonElement | null>>([]);

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    await onSaveProposal(edit);
    setIsSaving(false);
    setIsEditing(false);
  }

  function handleProposalTabKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    const availableTabs = proposalTabs.current.filter(
      (tab): tab is HTMLButtonElement => Boolean(tab && !tab.disabled),
    );
    const current = availableTabs.indexOf(proposalTabs.current[index]!);
    let next = current;
    if (event.key === "ArrowRight") {
      next = (current + 1) % availableTabs.length;
    } else if (event.key === "ArrowLeft") {
      next = (current - 1 + availableTabs.length) % availableTabs.length;
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = availableTabs.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    const target = availableTabs[next];
    setProposalView(target.dataset.view === "diff" ? "diff" : "preview");
    target.focus();
  }

  const proposalBlock = (
    <>
      {!proposal && run.autonomyMode === "research_only" ? (
        <section className="proposal-card" aria-labelledby="proposal-heading">
          <header>
            <div>
              <p className="section-index">Protected action</p>
              <h2 id="proposal-heading">External contact disabled</h2>
            </div>
            <span className="proposal-status rejected">research only</span>
          </header>
          <p className="policy-decision">
            This run is set to research only. Sentinel may compare candidates
            and produce files, but it will not open an RFQ proposal or authorize
            external contact.
          </p>
        </section>
      ) : null}

      {proposal ? (
        <section
          className={
            layout === "decision-first"
              ? "proposal-card proposal-card-decision"
              : "proposal-card"
          }
          aria-labelledby="proposal-heading"
        >
          <header>
            <div>
              <p className="section-index">
                {layout === "decision-first"
                  ? "Needs your decision"
                  : "Protected action"}
              </p>
              <h2 id="proposal-heading">
                {layout === "decision-first"
                  ? "RFQ ready for exact approval"
                  : "RFQ proposal"}
              </h2>
            </div>
            <span className={`proposal-status ${proposal.status}`}>
              {proposal.status.replace("_", " ")}
            </span>
          </header>

          <div className="proposal-meta">
            <span>Version {proposal.current.version}</span>
            <span>{proposal.riskClass}</span>
          </div>
          <p className="policy-decision">{proposal.policyDecision}</p>

          {isEditing ? (
            <form className="proposal-form" onSubmit={handleSave}>
              <label>
                Recipient
                <input
                  required
                  type="email"
                  value={edit.recipient}
                  onChange={(event) =>
                    setEdit({ ...edit, recipient: event.target.value })
                  }
                />
              </label>
              <label>
                Subject
                <input
                  required
                  value={edit.subject}
                  onChange={(event) =>
                    setEdit({ ...edit, subject: event.target.value })
                  }
                />
              </label>
              <label>
                Exact body
                <textarea
                  required
                  rows={6}
                  value={edit.body}
                  onChange={(event) =>
                    setEdit({ ...edit, body: event.target.value })
                  }
                />
              </label>
              <div className="button-pair">
                <button type="submit" disabled={isSaving}>
                  {isSaving ? "Saving…" : "Save as new version"}
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setIsEditing(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <>
              <div
                className="proposal-tabs"
                role="tablist"
                aria-label="Proposal version views"
              >
                <button
                  ref={(node) => {
                    proposalTabs.current[0] = node;
                  }}
                  id="proposal-preview-tab"
                  data-view="preview"
                  type="button"
                  role="tab"
                  aria-selected={proposalView === "preview"}
                  aria-controls="proposal-preview-panel"
                  tabIndex={proposalView === "preview" ? 0 : -1}
                  onClick={() => setProposalView("preview")}
                  onKeyDown={(event) => handleProposalTabKeyDown(event, 0)}
                >
                  Exact preview
                </button>
                <button
                  ref={(node) => {
                    proposalTabs.current[1] = node;
                  }}
                  id="proposal-diff-tab"
                  data-view="diff"
                  type="button"
                  role="tab"
                  aria-selected={proposalView === "diff"}
                  aria-controls="proposal-diff-panel"
                  tabIndex={proposalView === "diff" ? 0 : -1}
                  disabled={!proposal.previous}
                  onClick={() => setProposalView("diff")}
                  onKeyDown={(event) => handleProposalTabKeyDown(event, 1)}
                >
                  v{proposal.previous?.version ?? "–"} → v
                  {proposal.current.version}
                </button>
              </div>
              {proposalView === "preview" ? (
                <div
                  className="proposal-preview"
                  id="proposal-preview-panel"
                  role="tabpanel"
                  aria-labelledby="proposal-preview-tab"
                >
                  <dl>
                    <div>
                      <dt>To</dt>
                      <dd>{proposal.current.recipient}</dd>
                    </div>
                    <div>
                      <dt>Subject</dt>
                      <dd>{proposal.current.subject}</dd>
                    </div>
                  </dl>
                  <p>{proposal.current.body}</p>
                  <div className="proposal-attachments">
                    <strong>Bound attachments</strong>
                    <ul>
                      {proposal.current.attachmentIds.map((artifactId) => {
                        const artifact = run.artifacts.find(
                          (item) => item.id === artifactId,
                        );
                        return (
                          <li key={artifactId}>
                            <span>{artifact?.filename ?? artifactId}</span>
                            <small>
                              {artifact?.digest ?? "Digest unavailable"}
                            </small>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                  <small>{proposal.current.digest}</small>
                </div>
              ) : (
                <div
                  className="proposal-diff"
                  id="proposal-diff-panel"
                  role="tabpanel"
                  aria-labelledby="proposal-diff-tab"
                >
                  <p>
                    <del>
                      {proposal.previous?.subject ?? "No prior subject"}
                    </del>
                    <ins>{proposal.current.subject}</ins>
                  </p>
                  <p>
                    <del>{proposal.previous?.body ?? "No prior body"}</del>
                    <ins>{proposal.current.body}</ins>
                  </p>
                  <small>
                    Editing invalidated {proposal.previous?.digest}. Approval
                    binds only {proposal.current.digest}. Attachment set changed
                    from {proposal.previous?.attachmentIds.length ?? 0} to{" "}
                    {proposal.current.attachmentIds.length}.
                  </small>
                </div>
              )}
              {proposal.status === "pending_approval" ? (
                <>
                  <button
                    className="edit-proposal"
                    type="button"
                    onClick={() => {
                      setEdit({
                        recipient: proposal.current.recipient,
                        subject: proposal.current.subject,
                        body: proposal.current.body,
                      });
                      setIsEditing(true);
                    }}
                  >
                    Edit proposal
                  </button>
                  <div className="approval-actions">
                    <button
                      type="button"
                      onClick={() => void onDecideProposal("approve")}
                    >
                      Approve exact v{proposal.current.version} — no send
                    </button>
                    <button
                      className="danger-button"
                      type="button"
                      onClick={() => void onDecideProposal("reject")}
                    >
                      Reject
                    </button>
                  </div>
                </>
              ) : proposal.status === "approved" ? (
                <>
                  <p className="decision-receipt" role="status">
                    Approved by {proposal.approvedBy}. Approval itself did not
                    send. Execution is a separate gated action.
                  </p>
                  {proposal.canExecute && onExecuteProposal ? (
                    <button
                      type="button"
                      onClick={() => void onExecuteProposal()}
                    >
                      {proposal.executionLabel ??
                        "Execute approved RFQ (separate gate)"}
                    </button>
                  ) : null}
                  <button
                    className="edit-proposal"
                    type="button"
                    onClick={() => {
                      setEdit({
                        recipient: proposal.current.recipient,
                        subject: proposal.current.subject,
                        body: proposal.current.body,
                      });
                      setIsEditing(true);
                    }}
                  >
                    Edit and revoke approval
                  </button>
                </>
              ) : (
                <p className="decision-receipt" role="status">
                  Proposal rejected; no action is authorized.
                </p>
              )}
            </>
          )}
        </section>
      ) : null}
    </>
  );

  return (
    <aside
      className={
        layout === "decision-first"
          ? "action-rail action-rail-decision"
          : "action-rail"
      }
      aria-labelledby="output-heading"
    >
      {layout === "decision-first" ? proposalBlock : null}

      <section className="artifact-section">
        <div className="rail-heading">
          <div>
            <p className="section-index">Outputs</p>
            <h2 id="output-heading">
              {layout === "decision-first" ? "Files" : "Artifact rail"}
            </h2>
          </div>
          <span>{run.artifacts.length}</span>
        </div>
        {run.artifacts.length ? (
          <ul className="artifact-list">
            {run.artifacts.map((artifact) => (
              <li key={artifact.id}>
                <span className="file-mark" aria-hidden="true">
                  {artifact.kind.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <strong>{artifact.filename}</strong>
                  <small>
                    v{artifact.version} · {artifact.sizeLabel}
                  </small>
                  <span className={`artifact-status ${artifact.status}`}>
                    {artifact.status}
                  </span>
                </div>
                {artifact.status !== "building" ? (
                  <a href={artifact.downloadUrl}>Download</a>
                ) : (
                  <span className="building-label">Rebuilding</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="rail-empty">
            Artifacts appear here as outputs stabilize.
          </p>
        )}
      </section>

      {layout === "rail" ? proposalBlock : null}
    </aside>
  );
}
