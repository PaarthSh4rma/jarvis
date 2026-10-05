"use client";

import { useEffect, useState } from "react";
import { Radio } from "lucide-react";
import { getHermesCapabilities, getHermesHealth, type HermesStatus as Status } from "@/lib/api";

export function HermesStatus() {
  const [health, setHealth] = useState<Status | null>(null);
  const [capabilities, setCapabilities] = useState<Status | null>(null);
  const [checking, setChecking] = useState(true);
  const [failed, setFailed] = useState(false);
  const [check, setCheck] = useState(0);
  const [lastSuccess, setLastSuccess] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    // Bound browser waiting even when the local JARVIS API is unresponsive.
    const timeout = window.setTimeout(() => controller.abort(), 6000);
    void Promise.allSettled([
      getHermesHealth(controller.signal), getHermesCapabilities(controller.signal),
    ]).then(([healthResult, capabilitiesResult]) => {
      if (!active) return;
      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
        if (healthResult.value.last_successful_check) setLastSuccess(healthResult.value.last_successful_check);
      } else {
        setHealth(null);
      }
      setFailed(healthResult.status === "rejected");
      setCapabilities(capabilitiesResult.status === "fulfilled" ? capabilitiesResult.value : null);
      setChecking(false);
      window.clearTimeout(timeout);
    });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [check]);

  const state = checking ? "CHECKING" : failed ? "UNKNOWN" : health?.state ?? "UNKNOWN";
  return (
    <article className="system-item hermes-status" aria-label="Hermes system status">
      <div className="system-icon"><Radio aria-hidden="true" /></div>
      <div>
        <h3>Hermes</h3>
        <p aria-live="polite">HERMES {state}{health?.version && !checking ? ` / ${health.version}` : ""}</p>
        <p>Gateway liveness · read-only connection</p>
        {!checking && capabilities?.state === "ONLINE" && <p>Advertised: {capabilities.capabilities.join(", ") || "none"}</p>}
        {!checking && capabilities?.reason === "authentication_required" && <p>Capabilities require authentication</p>}
        {!checking && (!capabilities || (capabilities.state !== "ONLINE" && capabilities.reason !== "authentication_required")) && <p>Capabilities unavailable</p>}
        {lastSuccess && <p>Last successful health check: <time dateTime={lastSuccess}>{new Date(lastSuccess).toLocaleString()}</time></p>}
        <button type="button" disabled={checking} onClick={() => { setChecking(true); setCheck((value) => value + 1); }}>
          {checking ? "CHECKING HERMES" : "CHECK HERMES"}
        </button>
      </div>
    </article>
  );
}
