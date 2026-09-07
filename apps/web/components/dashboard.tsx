"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowUp, Braces, CircleDot, Cpu, FolderGit2, Github, Radio, RotateCcw, ShieldCheck, TerminalSquare } from "lucide-react";
import { ApiError, createConversation, deleteConversation, getHealth, getProjects, sendChat, type HealthResponse, type ProjectsResponse } from "@/lib/api";
import { MemoryPanel } from "@/components/memory-panel";

type Connection = { state: "checking" | "online" | "offline"; health?: HealthResponse };
type Message = { id: number; role: "user" | "assistant" | "error"; content: string };
const SESSION_STORAGE_KEY = "jarvis.conversation-id";

export function Dashboard() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });
  const [command, setCommand] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [projects, setProjects] = useState<ProjectsResponse | null>(null);
  const [projectsUnavailable, setProjectsUnavailable] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(SESSION_STORAGE_KEY),
  );
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setConnection({ state: "online", health }))
      .catch(() => {
        if (!controller.signal.aborted) setConnection({ state: "offline" });
      });
    getProjects(controller.signal)
      .then(setProjects)
      .catch(() => {
        if (!controller.signal.aborted) setProjectsUnavailable(true);
      });
    return () => controller.abort();
  }, []);

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
      const result = await sendChat(message, activeConversationId);
      setMessages((current) => [
        ...current,
        { id: Date.now() + 1, role: "assistant", content: result.response },
      ]);
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
      }
    } finally {
      setSending(false);
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
            {sending && <div className="message message-assistant message-loading"><span>JARVIS</span><p>Thinking</p></div>}
          </div>
        )}
        <form onSubmit={submit} className="command-form">
          <TerminalSquare aria-hidden="true" size={19} />
          <label htmlFor="command" className="sr-only">Enter a command</label>
          <input id="command" value={command} onChange={(event) => setCommand(event.target.value)} placeholder={assistantOnline ? "Awaiting directive..." : "Ollama runtime unavailable"} autoComplete="off" maxLength={4000} disabled={!assistantOnline || sending} />
          <button type="submit" disabled={!command.trim() || !assistantOnline || sending} aria-label="Send message"><ArrowUp size={18} /></button>
        </form>
        <p className="command-note">LOCAL CONVERSATION // COMMAND AND TOOL EXECUTION REMAIN DISABLED</p>
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
          <div className="project-empty">PROJECT INDEX UNAVAILABLE</div>
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
        <span><Github size={14} /> MEMORY BUILD 0.5.0</span>
      </footer>
    </main>
  );
}

function System({ icon, title, value, state }: { icon: React.ReactNode; title: string; value: string; state: string }) {
  return <article className="system-item"><div className="system-icon">{icon}</div><div><h3>{title}</h3><p>{value}</p></div><span className="tag">{state}</span></article>;
}
