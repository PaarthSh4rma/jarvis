"use client";

import { FormEvent, type RefObject } from "react";
import { ArrowUp, Check, RotateCcw, Square, TerminalSquare } from "lucide-react";

export type ConsoleMessage = {
  id: number;
  role: "user" | "assistant" | "error" | "tool";
  content: string;
  state?: "running" | "completed" | "failed";
};

type CommandConsoleProps = {
  command: string;
  messages: ConsoleMessage[];
  online: boolean;
  sending: boolean;
  resetting: boolean;
  activeRun: boolean;
  progress: string;
  toolActive: boolean;
  transcriptEnd: RefObject<HTMLDivElement | null>;
  projectName?: string;
  onCommandChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onRunCommand: (command: string) => void;
  onStop: () => void;
  onNewSession: () => void;
};

export function CommandConsole({
  command,
  messages,
  online,
  sending,
  resetting,
  activeRun,
  progress,
  toolActive,
  transcriptEnd,
  projectName,
  onCommandChange,
  onSubmit,
  onRunCommand,
  onStop,
  onNewSession,
}: CommandConsoleProps) {
  const prompts = projectName
    ? [
        "What projects am I working on?",
        `Check the status of ${projectName}.`,
        `Summarize ${projectName}.`,
      ]
    : ["What projects am I working on?"];

  return (
    <section className="command-zone" aria-labelledby="command-title">
      <div className="section-label">
        <span>01</span><h2 id="command-title">COMMAND</h2><i />
        <button className="session-reset" type="button" onClick={onNewSession} disabled={sending || resetting}>
          <RotateCcw size={12} />{resetting ? "RESETTING" : "NEW SESSION"}
        </button>
      </div>

      <div className="command-console">
        <div className="run-bar" aria-live="polite">
          <div className={`run-indicator ${sending ? "active" : ""}`} aria-hidden="true" />
          <span>EXECUTION</span>
          <strong>{sending ? progress : "READY"}</strong>
          {sending && <small>RUN ACTIVE</small>}
        </div>

        <div className="transcript" aria-live="polite" aria-label="Conversation transcript">
          {messages.length === 0 ? (
            <div className="command-empty">
              <div className="empty-mark" aria-hidden="true"><span /></div>
              <p className="eyebrow">LOCAL COMMAND CHANNEL</p>
              <h3>What needs attention?</h3>
              <p>Ask JARVIS to inspect a discovered project, summarize its state, or run a registered project skill.</p>
              <div className="prompt-list" aria-label="Suggested commands">
                {prompts.map((prompt) => (
                  <button key={prompt} type="button" onClick={() => onRunCommand(prompt)} disabled={!online || sending}>
                    <ArrowUp size={13} aria-hidden="true" />{prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : messages.map((message) => (
            <article className={`message message-${message.role}`} key={message.id}>
              <span>{message.role === "user" ? "YOU" : message.role === "assistant" ? "JARVIS" : message.role === "tool" ? "APPROVED TOOL" : "SYSTEM"}</span>
              {message.role === "tool" ? (
                <p><Check aria-hidden="true" size={14} />{message.content}<small>{message.state === "completed" ? "VERIFIED" : message.state === "failed" ? "FAILED SAFELY" : "RUNNING"}</small></p>
              ) : <MessageContent content={message.content} />}
            </article>
          ))}
          {sending && !toolActive && <span className="sr-only">Execution in progress: {progress}</span>}
          <div ref={transcriptEnd} />
        </div>

        <form onSubmit={onSubmit} className="command-form">
          <TerminalSquare aria-hidden="true" size={19} />
          <label htmlFor="command" className="sr-only">Enter a command</label>
          <input
            id="command"
            value={command}
            onChange={(event) => onCommandChange(event.target.value)}
            placeholder={online ? "Enter a directive..." : "Ollama runtime unavailable"}
            autoComplete="off"
            maxLength={4000}
            disabled={!online || sending}
          />
          {sending ? (
            <button className="stop-button" type="button" onClick={onStop} disabled={!activeRun} aria-label="Stop execution">
              <Square size={13} /> <span>STOP</span>
            </button>
          ) : (
            <button type="submit" disabled={!command.trim() || !online} aria-label="Send message"><ArrowUp size={18} /></button>
          )}
        </form>
        <p className="command-note">ENTER TO SEND // RESPONSES STREAM FROM THE LOCAL RUNTIME</p>
      </div>
    </section>
  );
}

function MessageContent({ content }: { content: string }) {
  const blocks: Array<{ type: "text" | "code"; content: string; language?: string }> = [];
  const pattern = /```([\w+-]*)\n?([\s\S]*?)```/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(content)) !== null) {
    if (match.index > cursor) blocks.push({ type: "text", content: content.slice(cursor, match.index) });
    blocks.push({ type: "code", language: match[1], content: match[2].replace(/\n$/, "") });
    cursor = pattern.lastIndex;
  }
  if (cursor < content.length) blocks.push({ type: "text", content: content.slice(cursor) });
  if (blocks.length === 0) blocks.push({ type: "text", content });

  return (
    <div className="message-content">
      {blocks.map((block, index) => block.type === "code" ? (
        <div className="code-block" key={`${block.type}-${index}`}>
          {block.language && <span>{block.language}</span>}
          <pre><code>{block.content}</code></pre>
        </div>
      ) : <p key={`${block.type}-${index}`}>{block.content}</p>)}
    </div>
  );
}
