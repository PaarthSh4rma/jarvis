"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, RotateCcw, ShieldAlert, X } from "lucide-react";
import { listApprovals, resolveApproval, type Approval, type ApprovalResolution } from "@/lib/api";

export function ApprovalPanel() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const pendingCount = useMemo(() => approvals.filter((approval) => approval.status === "PENDING").length, [approvals]);

  const load = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      setApprovals(await listApprovals(signal));
    } catch (reason) {
      if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Approval registry is unavailable.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void listApprovals(controller.signal)
      .then((records) => setApprovals(records))
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Approval registry is unavailable.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const resolve = async (approval: Approval, status: ApprovalResolution["status"]) => {
    if (savingId) return;
    setSavingId(approval.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await resolveApproval(approval.id, {
        status,
        resolution_note: notes[approval.id]?.trim() || null,
      });
      setApprovals((current) => current.map((item) => item.id === updated.id ? updated : item));
      setNotice("Decision recorded. No action executed.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not record approval decision.");
    } finally {
      setSavingId(null);
    }
  };

  return (
    <section className="approvals control-panel" aria-labelledby="approvals-title">
      <div className="section-label">
        <span>04</span><h2 id="approvals-title">APPROVALS</h2><i />
        <p className="section-summary"><span>{pendingCount}</span> PENDING</p>
      </div>
      <div className="control-console">
        <header className="control-toolbar">
          <div><ShieldAlert size={15} /><span>HUMAN DECISIONS</span></div>
          <small>RECORD ONLY // NO EXECUTION</small>
        </header>
        {notice && <p className="decision-notice" role="status">{notice}</p>}
        {error && <div className="control-error" role="alert"><span>{error}</span><button type="button" onClick={() => void load()} disabled={loading}><RotateCcw size={12} /> RETRY</button></div>}
        <div className="approval-list" aria-live="polite">
          {loading ? <p className="control-empty">LOADING APPROVALS...</p>
            : approvals.length === 0 ? <p className="control-empty">NO APPROVAL RECORDS</p>
            : approvals.map((approval) => (
              <article key={approval.id}>
                <div className="record-heading">
                  <div><span>{approval.action_type.replaceAll("_", " ")}</span><h3>{approval.summary}</h3></div>
                  <span className={`record-status status-${approval.status.toLowerCase()}`}>{approval.status}</span>
                </div>
                <dl><div><dt>MISSION</dt><dd>{approval.mission_id}</dd></div></dl>
                <p className="risk-context"><strong>RISK / CONTEXT</strong>{approval.risk_context}</p>
                {approval.status === "PENDING" ? (
                  <>
                    <label className="resolution-note">DECISION NOTE <span>OPTIONAL</span><textarea aria-label={`Decision note for ${approval.summary}`} maxLength={2000} rows={2} value={notes[approval.id] ?? ""} onChange={(event) => setNotes((current) => ({ ...current, [approval.id]: event.target.value }))} /></label>
                    <div className="record-actions approval-actions">
                      <button type="button" onClick={() => void resolve(approval, "APPROVED")} disabled={Boolean(savingId)}><Check size={12} /> RECORD APPROVAL</button>
                      <button type="button" onClick={() => void resolve(approval, "REJECTED")} disabled={Boolean(savingId)}><X size={12} /> REJECT</button>
                      <button className="danger-action" type="button" onClick={() => void resolve(approval, "CANCELLED")} disabled={Boolean(savingId)}>CANCEL REQUEST</button>
                    </div>
                  </>
                ) : approval.resolution_note && <p className="resolution-summary">DECISION NOTE // {approval.resolution_note}</p>}
              </article>
            ))}
        </div>
      </div>
    </section>
  );
}
