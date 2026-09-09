"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Braces, CircleDot, Cpu, FolderGit2, Github, Radio, RotateCcw, ShieldCheck, Square, TerminalSquare } from "lucide-react";
import { ApiError, cancelRun, createConversation, createRun, deleteConversation, getHealth, getProjects, streamRun, type HealthResponse, type ProjectsResponse, type RunEvent } from "@/lib/api";
import { MemoryPanel } from "@/components/memory-panel";

type Connection = { state: "checking" | "online" | "offline"; health?: HealthResponse };
type Message = { id: number; role: "user" | "assistant" | "error"; content: string };
const SESSION_STORAGE_KEY = "jarvis.conversation-id";
const TRANSCRIPT_STORAGE_KEY = "jarvis.completed-transcript.v1";
const MAX_STORED_MESSAGES = 24;
const MAX_STORED_CHARACTERS = 12000;

export function Dashboard() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });
  const [command, setCommand] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const completedMessages = useRef<Message[]>([]);
  const streamController = useRef<AbortController | null>(null);
  const [sending, setSending] = useState(false);
  const [projects, setProjects] = useState<ProjectsResponse | null>(null);
  const [projectsUnavailable, setProjectsUnavailable] = useState(false);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [conversationId, setConversationId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(SESSION_STORAGE_KEY),
  );
  const initialConversationId = useRef(conversationId);
  const [resetting, setResetting] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [progress, setProgress] = useState("IDLE");

  useEffect(() => {
    const restored = restoreCompletedTranscript(initialConversationId.current);
    completedMessages.current = restored;
    setMessages(restored);
  }, []);

  const loadProjects = useCallback(async (signal?: AbortSignal) => {
    setProjectsLoading(true);
    try {
      const discovered = await getProjects(signal);
      if (signal?.aborted) return;
      setProjects(discovered);
      setProjectsUnavailable(false);
    } catch {
      if (!signal?.aborted) setProjectsUnavailable(true);
    } finally {
      if (!signal?.aborted) setProjectsLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setConnection({ state: "online", health }))
      .catch(() => {
        if (!controller.signal.aborted) setConnection({ state: "offline" });
      });
    void loadProjects(controller.signal);
    return () => {
      controller.abort();
      streamController.current?.abort();
    };
  }, [loadProjects]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const message = command.trim();
    if (!message || sending || connection.health?.ollama !== "online") return;

    const userMessage: Message = { id: Date.now(), role: "user", content: message };
    setMessages((current) => [...current, userMessage]);
    setCommand("");
    setSending(true);
    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const conversation = await createConversation();
        activeConversationId = conversation.conversation_id;
        setConversationId(activeConversationId);
        window.localStorage.setItem(SESSION_STORAGE_KEY, activeConversationId);
      }
      const run = await createRun(message, activeConversationId);
      setActiveRunId(run.run_id);
      const assistantMessageId = Date.now() + 1;
      let assembledResponse = "";
      let completed = false;
      const controller = new AbortController();
      streamController.current = controller;
      await streamRun(run.run_id, activeConversationId, (runEvent: RunEvent) => {
        if (runEvent.type === "assistant.delta" && typeof runEvent.data.content === "string") {
          assembledResponse += runEvent.data.content;
          setMessages((current) => {
            const existing = current.some((item) => item.id === assistantMessageId);
            return existing
              ? current.map((item) => item.id === assistantMessageId ? { ...item, content: item.content + runEvent.data.content } : item)
              : [...current, { id: assistantMessageId, role: "assistant", content: runEvent.data.content as string }];
          });
        }
        if (runEvent.type.startsWith("tool.") && typeof runEvent.data.message === "string") setProgress(runEvent.data.message.toUpperCase());
        if (runEvent.type === "run.started") setProgress("PROCESSING");
        if (runEvent.type === "run.completed") completed = true;
        if (["run.failed", "run.cancelled", "run.timed_out"].includes(runEvent.type)) {
          const labels: Record<string, string> = { "run.failed": "EXECUTION FAILED SAFELY", "run.cancelled": "EXECUTION CANCELLED", "run.timed_out": "EXECUTION TIMED OUT" };
          setMessages((current) => [...current, { id: Date.now() + 2, role: "error", content: labels[runEvent.type] }]);
        }
      }, controller.signal);
      if (completed && assembledResponse) {
        const committed = boundCompletedTranscript([
          ...completedMessages.current,
          userMessage,
          { id: assistantMessageId, role: "assistant", content: assembledResponse },
        ]);
        completedMessages.current = committed;
        setMessages(committed);
        storeCompletedTranscript(activeConversationId, committed);
      }
    } catch (error) {
      const unavailable = error instanceof ApiError && error.status === 503;
      const sessionFailure = error instanceof ApiError && [404, 410, 422].includes(error.status ?? 0);
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: "error",
          content: sessionFailure
            ? "SESSION UNAVAILABLE — START A NEW SESSION"
            : unavailable
            ? "OLLAMA RUNTIME UNAVAILABLE — CHECK LOCAL SERVICE"
            : error instanceof Error ? error.message : "JARVIS could not complete the request.",
        },
      ]);
      if (unavailable) {
        setConnection((current) => current.health
          ? { ...current, health: { ...current.health, ollama: "offline" } }
          : current);
      }
      if (sessionFailure) {
        setConversationId(null);
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
        window.sessionStorage.removeItem(TRANSCRIPT_STORAGE_KEY);
        completedMessages.current = [];
      }
    } finally {
      setSending(false);
      setActiveRunId(null);
      setProgress("IDLE");
      streamController.current = null;
    }
  };

  const stopRun = async () => {
    if (!activeRunId || !conversationId) return;
    setProgress("CANCELLING");
    try {
      await cancelRun(activeRunId, conversationId);
    } catch (error) {
      setMessages((current) => [...current, { id: Date.now(), role: "error", content: error instanceof Error ? error.message : "Could not cancel execution." }]);
    }
  };

  const startNewSession = async () => {
    if (sending || resetting) return;
    setResetting(true);
    try {
      if (conversationId) await deleteConversation(conversationId);
      const conversation = await createConversation();
      setConversationId(conversation.conversation_id);
      window.localStorage.setItem(SESSION_STORAGE_KEY, conversation.conversation_id);
      setMessages([]);
      completedMessages.current = [];
      window.sessionStorage.removeItem(TRANSCRIPT_STORAGE_KEY);
      setCommand("");
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: Date.now(),
          role: "error",
          content: error instanceof Error ? error.message : "Could not start a new session.",
        },
      ]);
    } finally {
      setResetting(false);
    }
  };

  const online = connection.state === "online";
  const assistantOnline = online && connection.health?.ollama === "online";

  return (
    <main className="shell">
      <div className="scanline" aria-hidden="true" />
      <header className="topbar">
        <div className="wordmark"><span className="mark">J</span><span>JARVIS</span><small>LOCAL SYSTEM</small></div>
        <div className="system-time"><span>PRIMARY NODE</span><strong>MACOS // LOCAL</strong></div>
      </header>

      <section className="hero" aria-labelledby="assistant-name">
        <div className="identity">
          <div className={`orb ${assistantOnline ? "orb-online" : ""}`} aria-hidden="true">
            <div className="orb-core" /><div className="orbit orbit-one" /><div className="orbit orbit-two" />
          </div>
          <div>
            <p className="eyebrow">ASSISTANT CORE / 01</p>
            <h1 id="assistant-name">JARVIS</h1>
            <div className={`status ${connection.state === "checking" ? "checking" : assistantOnline ? "online" : "offline"}`}>
              <span /> {connection.state === "checking" ? "CONNECTING" : assistantOnline ? "ONLINE" : "OFFLINE"}
            </div>
          </div>
        </div>

        <div className="readout" aria-label="System readout">
          <div><span>MODEL</span><strong>{online ? connection.health?.model.toUpperCase() : "UNKNOWN"}</strong></div>
          <div><span>API</span><strong>{online ? "ONLINE" : "UNREACHABLE"}</strong></div>
          <div><span>OLLAMA</span><strong>{online ? connection.health?.ollama.toUpperCase() : "UNKNOWN"}</strong></div>
        </div>
      </section>

      <section className="command-zone" aria-labelledby="command-title">
        <div className="section-label"><span>01</span><h2 id="command-title">COMMAND INTERFACE</h2><i /><button className="session-reset" type="button" onClick={startNewSession} disabled={sending || resetting}><RotateCcw size={12} />{resetting ? "RESETTING" : "NEW SESSION"}</button></div>
        {messages.length > 0 && (
          <div className="transcript" aria-live="polite" aria-label="Conversation transcript">
            {messages.map((message) => (
              <div className={`message message-${message.role}`} key={message.id}>
                <span>{message.role === "user" ? "YOU" : message.role === "assistant" ? "JARVIS" : "SYSTEM"}</span>
                <p>{message.content}</p>
              </div>
            ))}
            {sending && <div className="message message-assistant message-loading"><span>EXECUTION</span><p>{progress}</p></div>}
          </div>
        )}
        <form onSubmit={submit} className="command-form">
          <TerminalSquare aria-hidden="true" size={19} />
          <label htmlFor="command" className="sr-only">Enter a command</label>
          <input id="command" value={command} onChange={(event) => setCommand(event.target.value)} placeholder={assistantOnline ? "Awaiting directive..." : "Ollama runtime unavailable"} autoComplete="off" maxLength={4000} disabled={!assistantOnline || sending} />
          {sending ? <button type="button" onClick={stopRun} disabled={!activeRunId} aria-label="Stop execution"><Square size={15} /> STOP</button> : <button type="submit" disabled={!command.trim() || !assistantOnline} aria-label="Send message"><ArrowUp size={18} /></button>}
        </form>
        <p className="command-note">LOCAL EXECUTION RUNTIME // {sending ? progress : "READY"}</p>
      </section>

      <section className="systems" aria-labelledby="systems-title">
        <div className="section-label"><span>02</span><h2 id="systems-title">SYSTEMS</h2><i /></div>
        <div className="system-grid">
          <System icon={<Cpu />} title="Assistant model" value={connection.health?.model ?? "Awaiting runtime"} state={connection.health?.ollama ?? "standby"} />
          <System icon={<Braces />} title="Coding specialist" value="Codex / separate" state="isolated" />
          <System icon={<CircleDot />} title="Persistence" value="SQLite / ready" state="ready" />
          <System icon={<Radio />} title="External links" value="No connections" state="offline" />
        </div>
      </section>

      <section className="projects" aria-labelledby="projects-title">
        <div className="section-label"><span>03</span><h2 id="projects-title">PROJECTS</h2><i /></div>
        {projectsUnavailable ? (
          <div className="project-empty project-unavailable" role="status">
            <p>PROJECT INDEX UNAVAILABLE</p>
            <button type="button" onClick={() => void loadProjects()} disabled={projectsLoading}>
              {projectsLoading ? "RETRYING PROJECT INDEX" : "RETRY PROJECT INDEX"}
            </button>
          </div>
        ) : projectsLoading && !projects ? (
          <div className="project-empty">PROJECT INDEX SYNCHRONISING</div>
        ) : (
          <div className="project-console">
            <div className="project-metric"><FolderGit2 size={18} /><span>DISCOVERED</span><strong>{projects?.count ?? "—"}</strong></div>
            <div className="project-metric"><CircleDot size={18} /><span>DIRTY REPOSITORIES</span><strong>{projects?.dirty_count ?? "—"}</strong></div>
            <div className="project-recent">
              <span>RECENT ACTIVITY</span>
              <div>
                {projects?.recent_projects.map((project) => (
                  <p key={project.id}><strong>{project.name}</strong><small>{project.branch ?? project.technologies[0] ?? "LOCAL"}</small></p>
                )) ?? <p><strong>SCANNING</strong></p>}
                {projects?.count === 0 && <p><strong>NO PROJECTS DISCOVERED</strong></p>}
              </div>
            </div>
          </div>
        )}
      </section>

      <MemoryPanel projects={projects?.projects ?? []} />

      <footer>
        <span><ShieldCheck size={14} /> LOCAL-FIRST // NO CLOUD UPLINK</span>
        <span><Github size={14} /> EXECUTION BUILD 0.6.0</span>
      </footer>
    </main>
  );
}

function System({ icon, title, value, state }: { icon: React.ReactNode; title: string; value: string; state: string }) {
  return <article className="system-item"><div className="system-icon">{icon}</div><div><h3>{title}</h3><p>{value}</p></div><span className="tag">{state}</span></article>;
}

function restoreCompletedTranscript(conversationId: string | null): Message[] {
  if (!conversationId || typeof window === "undefined") return [];
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(TRANSCRIPT_STORAGE_KEY) ?? "null") as {
      conversationId?: unknown;
      messages?: unknown;
    } | null;
    if (stored?.conversationId !== conversationId || !Array.isArray(stored.messages)) return [];
    const messages = stored.messages.filter((item): item is Message => {
      if (!item || typeof item !== "object") return false;
      const candidate = item as Partial<Message>;
      return typeof candidate.id === "number"
        && (candidate.role === "user" || candidate.role === "assistant")
        && typeof candidate.content === "string";
    });
    return boundCompletedTranscript(messages);
  } catch {
    window.sessionStorage.removeItem(TRANSCRIPT_STORAGE_KEY);
    return [];
  }
}

function storeCompletedTranscript(conversationId: string, messages: Message[]): void {
  try {
    window.sessionStorage.setItem(
      TRANSCRIPT_STORAGE_KEY,
      JSON.stringify({ conversationId, messages: boundCompletedTranscript(messages) }),
    );
  } catch {
    // Browser storage is a best-effort UI cache, never execution authority.
  }
}

function boundCompletedTranscript(messages: Message[]): Message[] {
  const bounded = messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .slice(-MAX_STORED_MESSAGES);
  while (
    bounded.length > 0
    && bounded.reduce((total, message) => total + message.content.length, 0)
      > MAX_STORED_CHARACTERS
  ) {
    bounded.splice(0, 2);
  }
  return bounded;
}
