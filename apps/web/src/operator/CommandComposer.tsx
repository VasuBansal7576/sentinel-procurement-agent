import { FormEvent, useState } from "react";

import type { OperatorCommand } from "./types";

interface CommandComposerProps {
  commands: OperatorCommand[];
  onSend: (mode: "queue" | "redirect", text: string) => Promise<void>;
}

export function CommandComposer({ commands, onSend }: CommandComposerProps) {
  const [mode, setMode] = useState<"queue" | "redirect">("queue");
  const [text, setText] = useState("");
  const [isSending, setIsSending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const commandText = text.trim();
    if (!commandText) {
      return;
    }
    setIsSending(true);
    await onSend(mode, commandText);
    setText("");
    setIsSending(false);
  }

  return (
    <section className="command-dock" aria-labelledby="command-heading">
      <div className="command-history">
        <p className="section-index" id="command-heading">
          Operator instructions
        </p>
        {commands.length ? (
          <ol>
            {commands.slice(0, 2).map((command) => (
              <li key={command.id}>
                <span className={`command-mode ${command.mode}`}>
                  {command.mode}
                </span>
                <p>{command.text}</p>
                <small>
                  {command.status} · {command.createdLabel}
                </small>
              </li>
            ))}
          </ol>
        ) : (
          <p className="command-empty">No operator instructions yet.</p>
        )}
      </div>
      <form onSubmit={submit}>
        <fieldset>
          <legend className="sr-only">Instruction behavior</legend>
          <label>
            <input
              type="radio"
              name="instruction-mode"
              value="queue"
              checked={mode === "queue"}
              onChange={() => setMode("queue")}
            />
            Queue
          </label>
          <label>
            <input
              type="radio"
              name="instruction-mode"
              value="redirect"
              checked={mode === "redirect"}
              onChange={() => setMode("redirect")}
            />
            Redirect
          </label>
        </fieldset>
        <label className="sr-only" htmlFor="operator-instruction">
          Operator instruction
        </label>
        <textarea
          id="operator-instruction"
          rows={2}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={
            mode === "queue"
              ? "Add context for the next safe checkpoint…"
              : "Revise the request while retaining unaffected evidence…"
          }
        />
        <button type="submit" disabled={isSending || !text.trim()}>
          {isSending
            ? "Acknowledging…"
            : mode === "queue"
              ? "Queue instruction"
              : "Apply redirect"}
        </button>
      </form>
    </section>
  );
}
