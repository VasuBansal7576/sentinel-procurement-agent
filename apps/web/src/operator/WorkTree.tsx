import { useState } from "react";

import type { WorkNode, WorkState } from "./types";

const stateLabels: Record<WorkState, string> = {
  remaining: "Remaining",
  active: "Active",
  completed: "Complete",
  blocked: "Blocked",
  failed: "Failed",
  recovering: "Recovering",
};

interface WorkTreeProps {
  nodes: WorkNode[];
  onRetry: (workId: string) => Promise<void>;
}

export function WorkTree({ nodes, onRetry }: WorkTreeProps) {
  const [openNodes, setOpenNodes] = useState<Set<string>>(
    () =>
      new Set(
        nodes
          .filter((node) => node.status !== "completed")
          .map((node) => node.id),
      ),
  );

  function toggle(nodeId: string) {
    setOpenNodes((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }

  return (
    <div className="work-tree" role="tree" aria-label="Run work tree">
      {nodes.map((node) => (
        <WorkTreeNode
          key={node.id}
          node={node}
          depth={1}
          isOpen={openNodes.has(node.id)}
          openNodes={openNodes}
          onToggle={toggle}
          onRetry={onRetry}
        />
      ))}
    </div>
  );
}

interface WorkTreeNodeProps {
  node: WorkNode;
  depth: number;
  isOpen: boolean;
  openNodes: Set<string>;
  onToggle: (nodeId: string) => void;
  onRetry: (workId: string) => Promise<void>;
}

function WorkTreeNode({
  node,
  depth,
  isOpen,
  openNodes,
  onToggle,
  onRetry,
}: WorkTreeNodeProps) {
  const hasChildren = Boolean(node.children?.length);

  return (
    <div
      className={`tree-node tree-node-${node.kind}`}
      role="treeitem"
      aria-level={depth}
      aria-expanded={hasChildren ? isOpen : undefined}
    >
      <div className="tree-node-row">
        {hasChildren ? (
          <button
            className="tree-disclosure"
            type="button"
            aria-label={`${isOpen ? "Collapse" : "Expand"} ${node.label}`}
            onClick={() => onToggle(node.id)}
          >
            <span aria-hidden="true">{isOpen ? "−" : "+"}</span>
          </button>
        ) : (
          <span className="tree-connector" aria-hidden="true" />
        )}
        <span className={`state-mark ${node.status}`} aria-hidden="true" />
        <div className="tree-node-copy">
          <div className="tree-node-title">
            <strong>{node.label}</strong>
            <span className={`state-label ${node.status}`}>
              {stateLabels[node.status]}
            </span>
          </div>
          <p>{node.summary}</p>
          {node.progress ? (
            <p className="work-progress">
              {node.progress.completed} of {node.progress.total}{" "}
              {node.progress.unit}
            </p>
          ) : null}
          {node.blocker ? (
            <p className="blocker-copy">
              <span>Blocker</span> {node.blocker}
            </p>
          ) : null}
          {node.retry ? (
            <div className="retry-state">
              <p>
                {node.retry.classification} · attempt {node.retry.attempt} of{" "}
                {node.retry.maxAttempts}
              </p>
              <button
                type="button"
                disabled={!node.retry.safeToRetry}
                onClick={() => void onRetry(node.id)}
              >
                Retry from checkpoint
              </button>
            </div>
          ) : null}
        </div>
      </div>
      {hasChildren && isOpen ? (
        <div className="tree-children" role="group">
          {node.children?.map((child) => (
            <WorkTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              isOpen={openNodes.has(child.id)}
              openNodes={openNodes}
              onToggle={onToggle}
              onRetry={onRetry}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
