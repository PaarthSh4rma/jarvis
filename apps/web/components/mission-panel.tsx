"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Ban, ChevronRight, ClipboardList, Pencil, Plus, RotateCcw, X } from "lucide-react";
import {
  createMission,
  getMission,
  listMissions,
  updateMission,
  type Mission,
  type MissionType,
  type Project,
} from "@/lib/api";

const missionTypes: MissionType[] = [
  "CODE_CHANGE", "PROJECT_REVIEW", "JOB_APPLICATION", "RESEARCH",
  "INTERVIEW_PREP", "MONEY_EXPERIMENT", "ADMIN",
];

export function MissionPanel({ projects }: { projects: Project[] }) {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<Mission | null>(null);
  const [editing, setEditing] = useState(false);
  const [type, setType] = useState<MissionType>("PROJECT_REVIEW");
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [context, setContext] = useState("");
  const [projectId, setProjectId] = useState("");

  const activeCount = useMemo(
    () => missions.filter((mission) => !["COMPLETED", "FAILED", "CANCELLED"].includes(mission.status)).length,
    [missions],
  );

  const load = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      setMissions(await listMissions(signal));
    } catch (reason) {
      if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Mission registry is unavailable.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void listMissions(controller.signal)
      .then((records) => setMissions(records))
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Mission registry is unavailable.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const resetForm = () => {
    setType("PROJECT_REVIEW");
    setTitle("");
    setGoal("");
    setContext("");
    setProjectId("");
  };

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !goal.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const mission = await createMission({
        type,
        title: title.trim(),
        goal: goal.trim(),
        context: context.trim() || null,
        project_id: projectId || null,
      });
      setMissions((current) => [mission, ...current]);
      setSelected(mission);
      setCreating(false);
      resetForm();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create mission.");
    } finally {
      setSaving(false);
    }
  };

  const inspect = async (missionId: string) => {
    setSaving(true);
    setError(null);
    try {
      const mission = await getMission(missionId);
      setSelected(mission);
      setEditing(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load mission.");
    } finally {
      setSaving(false);
    }
  };

  const startEdit = () => {
    if (!selected) return;
    setTitle(selected.title);
    setGoal(selected.goal);
    setContext(selected.context ?? "");
    setProjectId(selected.project_id ?? "");
    setEditing(true);
  };

  const saveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !title.trim() || !goal.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const mission = await updateMission(selected.id, {
        expected_revision: selected.revision,
        title: title.trim(),
        goal: goal.trim(),
        context: context.trim() || null,
        project_id: projectId || null,
      });
      replaceMission(mission);
      setEditing(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update mission.");
    } finally {
      setSaving(false);
    }
  };

  const cancelMission = async () => {
    if (!selected || saving) return;
    setSaving(true);
    setError(null);
    try {
      replaceMission(await updateMission(selected.id, {
        expected_revision: selected.revision,
        status: "CANCELLED",
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not cancel mission.");
    } finally {
      setSaving(false);
    }
  };

  const replaceMission = (mission: Mission) => {
    setMissions((current) => current.map((item) => item.id === mission.id ? mission : item));
    setSelected(mission);
  };

  const editable = selected && ["DRAFT", "READY"].includes(selected.status);

  return (
    <section className="missions control-panel" aria-labelledby="missions-title">
      <div className="section-label">
        <span>03</span><h2 id="missions-title">MISSIONS</h2><i />
        <p className="section-summary"><span>{activeCount}</span> ACTIVE RECORDS</p>
      </div>
      <div className="control-console">
        <header className="control-toolbar">
          <div><ClipboardList size={15} /><span>DURABLE RECORDS</span></div>
          <button type="button" onClick={() => { setCreating((value) => !value); setEditing(false); }}>
            {creating ? <X size={12} /> : <Plus size={12} />}{creating ? "CLOSE" : "CREATE MISSION"}
          </button>
        </header>

        {error && <div className="control-error" role="alert"><span>{error}</span><button type="button" onClick={() => void load()} disabled={loading}><RotateCcw size={12} /> RETRY</button></div>}

        {creating && (
          <MissionForm
            legend="NEW MISSION RECORD"
            type={type}
            title={title}
            goal={goal}
            context={context}
            projectId={projectId}
            projects={projects}
            saving={saving}
            submitLabel="SAVE MISSION"
            onType={setType}
            onTitle={setTitle}
            onGoal={setGoal}
            onContext={setContext}
            onProject={setProjectId}
            onSubmit={submitCreate}
          />
        )}

        {selected && !creating && (
          <div className="record-detail" aria-label="Mission details">
            <div className="record-heading">
              <div><span>{selected.type.replaceAll("_", " ")}</span><h3>{selected.title}</h3></div>
              <span className={`record-status status-${selected.status.toLowerCase()}`}>{selected.status}</span>
            </div>
            {editing ? (
              <MissionForm
                legend="EDIT MISSION RECORD"
                type={selected.type}
                title={title}
                goal={goal}
                context={context}
                projectId={projectId}
                projects={projects}
                saving={saving}
                submitLabel="SAVE CHANGES"
                lockType
                onType={() => undefined}
                onTitle={setTitle}
                onGoal={setGoal}
                onContext={setContext}
                onProject={setProjectId}
                onSubmit={saveEdit}
              />
            ) : (
              <>
                <p className="record-goal">{selected.goal}</p>
                {selected.context && <p className="record-context">{selected.context}</p>}
                <dl><div><dt>PROJECT</dt><dd>{projectName(projects, selected.project_id)}</dd></div><div><dt>REVISION</dt><dd>{selected.revision}</dd></div></dl>
                <div className="record-actions">
                  {editable && <button type="button" onClick={startEdit}><Pencil size={12} /> EDIT</button>}
                  {editable && <button className="danger-action" type="button" onClick={() => void cancelMission()} disabled={saving}><Ban size={12} /> CANCEL MISSION</button>}
                  <button type="button" onClick={() => setSelected(null)}><X size={12} /> CLOSE</button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="record-list" aria-live="polite">
          {loading ? <p className="control-empty">LOADING MISSIONS...</p>
            : missions.length === 0 ? <p className="control-empty">NO MISSION RECORDS</p>
            : missions.map((mission) => (
              <article key={mission.id} className={selected?.id === mission.id ? "selected" : ""}>
                <div><span>{mission.type.replaceAll("_", " ")}</span><h3>{mission.title}</h3><small>{projectName(projects, mission.project_id)}</small></div>
                <span className={`record-status status-${mission.status.toLowerCase()}`}>{mission.status}</span>
                <button type="button" onClick={() => void inspect(mission.id)} disabled={saving} aria-label={`View mission ${mission.title}`}><ChevronRight size={14} /></button>
              </article>
            ))}
        </div>
      </div>
    </section>
  );
}

type MissionFormProps = {
  legend: string;
  type: MissionType;
  title: string;
  goal: string;
  context: string;
  projectId: string;
  projects: Project[];
  saving: boolean;
  submitLabel: string;
  lockType?: boolean;
  onType: (value: MissionType) => void;
  onTitle: (value: string) => void;
  onGoal: (value: string) => void;
  onContext: (value: string) => void;
  onProject: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
};

function MissionForm(props: MissionFormProps) {
  return (
    <form className="record-form" onSubmit={props.onSubmit}>
      <p>{props.legend}</p>
      <div className="field-row">
        <label>TYPE<select aria-label="Mission type" value={props.type} disabled={props.lockType} onChange={(event) => props.onType(event.target.value as MissionType)}>{missionTypes.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>
        <label>PROJECT<select aria-label="Mission project" value={props.projectId} onChange={(event) => props.onProject(event.target.value)}><option value="">NO PROJECT</option>{props.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      </div>
      <label>TITLE<input aria-label="Mission title" maxLength={160} value={props.title} onChange={(event) => props.onTitle(event.target.value)} /></label>
      <label>GOAL<textarea aria-label="Mission goal" maxLength={4000} rows={3} value={props.goal} onChange={(event) => props.onGoal(event.target.value)} /></label>
      <label>CONTEXT <span>OPTIONAL</span><textarea aria-label="Mission context" maxLength={4000} rows={2} value={props.context} onChange={(event) => props.onContext(event.target.value)} /></label>
      <button type="submit" disabled={!props.title.trim() || !props.goal.trim() || props.saving}>{props.saving ? "SAVING" : props.submitLabel}</button>
    </form>
  );
}

function projectName(projects: Project[], projectId: string | null): string {
  if (!projectId) return "NO PROJECT";
  return projects.find((project) => project.id === projectId)?.name ?? projectId;
}
