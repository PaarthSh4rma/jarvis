"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Activity, Cpu, Database, FolderGit2, Github, ShieldCheck } from "lucide-react";
import { ApiError, cancelRun, createConversation, createRun, deleteConversation, getHealth, getProjects, getSkills, streamRun, type HealthResponse, type ProjectsResponse, type RunEvent, type SkillsResponse } from "@/lib/api";
import { CommandConsole, type ConsoleMessage } from "@/components/command-console";
import { ApprovalPanel } from "@/components/approval-panel";
import { HermesStatus } from "@/components/hermes-status";
import { MemoryPanel } from "@/components/memory-panel";
import { MissionPanel } from "@/components/mission-panel";
import { ProjectPanel } from "@/components/project-panel";
import { SkillsPanel } from "@/components/skills-panel";

type Connection = { state: "checking" | "online" | "offline"; health?: HealthResponse };
type Message = ConsoleMessage;
const SESSION_STORAGE_KEY = "jarvis.conversation-id";
const TRANSCRIPT_STORAGE_KEY = "jarvis.completed-transcript.v1";
const MAX_STORED_MESSAGES = 24;
const MAX_STORED_CHARACTERS = 12000;

export function Dashboard() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });
  const [command, setCommand] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const completedMessages = useRef<Message[]>([]);
  const transcriptEnd = useRef<HTMLDivElement | null>(null);
  const streamController = useRef<AbortController | null>(null);
  const [sending, setSending] = useState(false);
  const [projects, setProjects] = useState<ProjectsResponse | null>(null);
  const [projectsUnavailable, setProjectsUnavailable] = useState(false);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [skills, setSkills] = useState<SkillsResponse | null>(null);
  const [skillsUnavailable, setSkillsUnavailable] = useState(false);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [conversationId, setConversationId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(SESSION_STORAGE_KEY),
  );
  const initialConversationId = useRef(conversationId);
  const [resetting, setResetting] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [progress, setProgress] = useState("IDLE");
  const [toolActive, setToolActive] = useState(false);

  useEffect(() => {
    const restored = restoreCompletedTranscript(initialConversationId.current);
    completedMessages.current = restored;
    setMessages(restored);
  }, []);

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages, progress]);

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

  const loadSkills = useCallback(async (signal?: AbortSignal) => {
    setSkillsLoading(true);
    try {
      const discovered = await getSkills(signal);
      if (signal?.aborted) return;
      setSkills(discovered);
      setSkillsUnavailable(false);
    } catch {
      if (!signal?.aborted) setSkillsUnavailable(true);
    } finally {
      if (!signal?.aborted) setSkillsLoading(false);
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
    void loadSkills(controller.signal);
    return () => {
      controller.abort();
      streamController.current?.abort();
    };
  }, [loadProjects, loadSkills]);

  const runCommand = async (rawCommand: string) => {
    const message = rawCommand.trim();
    const runtimeReady = connection.state === "online" && (
      connection.health?.ollama === "online" || connection.health?.demo_mode === true
    );
    if (!message || sending || !runtimeReady) return;

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
      const toolMessageId = assistantMessageId - 1;
      let toolDescription = "Approved local tool";
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
        if (runEvent.type.startsWith("tool.") && typeof runEvent.data.message === "string") {
          setProgress(runEvent.data.message.toUpperCase());
          if (runEvent.type === "tool.requested") {
            toolDescription = runEvent.data.message;
            setToolActive(true);
            setMessages((current) => [...current, { id: toolMessageId, role: "tool", content: toolDescription, state: "running" }]);
          }
          if (runEvent.type === "tool.completed" || runEvent.type === "tool.failed") {
            setMessages((current) => current.map((item) => item.id === toolMessageId
              ? { ...item, content: toolDescription, state: runEvent.type === "tool.completed" ? "completed" : "failed" }
              : item));
          }
        }
        if (runEvent.type.startsWith("skill.") && typeof runEvent.data.message === "string") {
          const skillName = typeof runEvent.data.skill === "string" ? runEvent.data.skill.replaceAll("-", " ").toUpperCase() : "PROCEDURE";
          setProgress(`SKILL // ${skillName} // ${runEvent.data.message.toUpperCase()}`);
        }
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
        setMessages((current) => boundVisibleTranscript(current));
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
      setToolActive(false);
      setActiveRunId(null);
      setProgress("IDLE");
      streamController.current = null;
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void runCommand(command);
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
  const assistantOnline = online && (
    connection.health?.ollama === "online" || connection.health?.demo_mode === true
  );

  return (
    <main className={`shell ${connection.health?.demo_mode ? "shell-demo" : ""}`}>
      <div className="scanline" aria-hidden="true" />
      <header className="console-header">
        <div className="wordmark">
          <span className={`core-mark ${assistantOnline ? "online" : ""}`} aria-hidden="true"><i /></span>
          <div><strong>JARVIS</strong><small>{connection.health?.demo_mode ? "SAFE DEMO WORKSPACE" : "LOCAL COMMAND CENTRE"}</small></div>
        </div>
        <div className="header-status" aria-live="polite">
          <span className={`status-dot ${connection.state === "checking" ? "checking" : assistantOnline ? "online" : "offline"}`} />
          <div><span>ASSISTANT</span><strong>{connection.state === "checking" ? "CONNECTING" : connection.health?.demo_mode ? "DEMO READY" : assistantOnline ? "ONLINE" : "OFFLINE"}</strong></div>
        </div>
      </header>

      <div className="workspace-grid">
        <CommandConsole
          command={command}
          messages={messages}
          online={assistantOnline}
          sending={sending}
          resetting={resetting}
          activeRun={Boolean(activeRunId)}
          progress={progress}
          toolActive={toolActive}
          transcriptEnd={transcriptEnd}
          projectName={projects?.recent_projects[0]?.name ?? projects?.projects[0]?.name}
          onCommandChange={setCommand}
          onSubmit={submit}
          onRunCommand={(nextCommand) => void runCommand(nextCommand)}
          onStop={() => void stopRun()}
          onNewSession={() => void startNewSession()}
        />

        <aside className="readiness" aria-labelledby="readiness-title">
          <div className="section-label"><span>LIVE</span><h2 id="readiness-title">READINESS</h2><i /></div>
          <div className="readiness-panel">
            <StatusItem icon={<Activity />} label="JARVIS API" value={online ? "ONLINE" : connection.state === "checking" ? "CHECKING" : "UNREACHABLE"} state={online ? "ready" : "error"} />
            <StatusItem icon={<Cpu />} label="OLLAMA" value={online ? connection.health?.ollama.toUpperCase() ?? "UNKNOWN" : "UNKNOWN"} state={assistantOnline ? "ready" : "error"} />
            <StatusItem icon={<FolderGit2 />} label="PROJECT INDEX" value={projectsLoading ? "SYNCING" : projectsUnavailable ? "UNAVAILABLE" : `${projects?.count ?? 0} DISCOVERED`} state={projectsUnavailable ? "error" : projectsLoading ? "busy" : "ready"} />
            <StatusItem icon={<Database />} label="LOCAL MODEL" value={online ? connection.health?.model.toUpperCase() ?? "UNKNOWN" : "UNKNOWN"} state={assistantOnline ? "ready" : "standby"} />
            <HermesStatus />
          </div>
          <div className="boundary-note">
            <ShieldCheck size={15} aria-hidden="true" />
            <div><strong>LOCAL EXECUTION</strong><p>Project tools stay inside discovered roots and validated actions.</p></div>
          </div>
        </aside>
      </div>

      <ProjectPanel
        data={projects}
        loading={projectsLoading}
        unavailable={projectsUnavailable}
        actionsDisabled={!assistantOnline || sending}
        onRetry={() => void loadProjects()}
        onCommand={(nextCommand) => void runCommand(nextCommand)}
      />

      <div className="control-grid">
        <MissionPanel projects={projects?.projects ?? []} />
        <ApprovalPanel />
      </div>

      <div className="secondary-grid">
        <MemoryPanel projects={projects?.projects ?? []} />
        <SkillsPanel data={skills} loading={skillsLoading} unavailable={skillsUnavailable} onRetry={() => void loadSkills()} />
      </div>

      <footer>
        <span><ShieldCheck size={14} /> LOCAL-FIRST // HUMAN-DIRECTED</span>
        <span><Github size={14} /> EXECUTION BUILD 0.8.0</span>
      </footer>
    </main>
  );
}

function StatusItem({ icon, label, value, state }: { icon: React.ReactNode; label: string; value: string; state: "ready" | "busy" | "standby" | "error" }) {
  return (
    <article className="status-item">
      <div className="status-icon">{icon}</div>
      <div><span>{label}</span><strong>{value}</strong></div>
      <i className={state} aria-hidden="true" />
    </article>
  );
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

function boundVisibleTranscript(messages: Message[]): Message[] {
  const bounded = messages.slice(-36);
  while (bounded.length > 0 && bounded.reduce((total, message) => total + message.content.length, 0) > MAX_STORED_CHARACTERS) {
    bounded.shift();
  }
  return bounded;
}
