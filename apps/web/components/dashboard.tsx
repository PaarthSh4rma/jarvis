"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowUp, Braces, CircleDot, Cpu, Github, Radio, ShieldCheck, TerminalSquare } from "lucide-react";
import { getHealth, type HealthResponse } from "@/lib/api";

type Connection = { state: "checking" | "online" | "offline"; health?: HealthResponse };

export function Dashboard() {
  const [connection, setConnection] = useState<Connection>({ state: "checking" });
  const [command, setCommand] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setConnection({ state: "online", health }))
      .catch(() => {
        if (!controller.signal.aborted) setConnection({ state: "offline" });
      });
    return () => controller.abort();
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
  };

  const online = connection.state === "online";

  return (
    <main className="shell">
      <div className="scanline" aria-hidden="true" />
      <header className="topbar">
        <div className="wordmark"><span className="mark">J</span><span>JARVIS</span><small>LOCAL SYSTEM</small></div>
        <div className="system-time"><span>PRIMARY NODE</span><strong>MACOS // LOCAL</strong></div>
      </header>

      <section className="hero" aria-labelledby="assistant-name">
        <div className="identity">
          <div className={`orb ${online ? "orb-online" : ""}`} aria-hidden="true">
            <div className="orb-core" /><div className="orbit orbit-one" /><div className="orbit orbit-two" />
          </div>
          <div>
            <p className="eyebrow">ASSISTANT CORE / 01</p>
            <h1 id="assistant-name">JARVIS</h1>
            <div className={`status ${connection.state}`}>
              <span /> {connection.state === "checking" ? "CONNECTING" : online ? "ONLINE" : "OFFLINE"}
            </div>
          </div>
        </div>

        <div className="readout" aria-label="System readout">
          <div><span>MODEL</span><strong>NOT CONFIGURED</strong></div>
          <div><span>API</span><strong>{online ? connection.health?.service.toUpperCase() : "UNREACHABLE"}</strong></div>
          <div><span>RUNTIME</span><strong>LOCAL</strong></div>
        </div>
      </section>

      <section className="command-zone" aria-labelledby="command-title">
        <div className="section-label"><span>01</span><h2 id="command-title">COMMAND INTERFACE</h2><i /></div>
        <form onSubmit={submit} className="command-form">
          <TerminalSquare aria-hidden="true" size={19} />
          <label htmlFor="command" className="sr-only">Enter a command</label>
          <input id="command" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="Awaiting directive..." autoComplete="off" />
          <button type="submit" disabled={!command.trim()} aria-label="Submit command (not yet available)"><ArrowUp size={18} /></button>
        </form>
        <p className="command-note">COMMAND EXECUTION DISABLED IN FOUNDATION MODE</p>
      </section>

      <section className="systems" aria-labelledby="systems-title">
        <div className="section-label"><span>02</span><h2 id="systems-title">SYSTEMS</h2><i /></div>
        <div className="system-grid">
          <System icon={<Cpu />} title="Assistant model" value="Awaiting provider" state="standby" />
          <System icon={<Braces />} title="Coding specialist" value="Codex / separate" state="isolated" />
          <System icon={<CircleDot />} title="Persistence" value="SQLite / ready" state="ready" />
          <System icon={<Radio />} title="External links" value="No connections" state="offline" />
        </div>
      </section>

      <footer>
        <span><ShieldCheck size={14} /> LOCAL-FIRST // NO CLOUD UPLINK</span>
        <span><Github size={14} /> FOUNDATION BUILD 0.1.0</span>
      </footer>
    </main>
  );
}

function System({ icon, title, value, state }: { icon: React.ReactNode; title: string; value: string; state: string }) {
  return <article className="system-item"><div className="system-icon">{icon}</div><div><h3>{title}</h3><p>{value}</p></div><span className="tag">{state}</span></article>;
}
