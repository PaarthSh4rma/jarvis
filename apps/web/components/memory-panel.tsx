"use client";

import { FormEvent, useEffect, useState } from "react";
import { Check, Database, Pencil, Plus, Trash2, X } from "lucide-react";
import {
  addMemory,
  deleteMemory,
  getMemory,
  updateMemory,
  type MemoryEntry,
  type MemoryScope,
  type Project,
} from "@/lib/api";

export function MemoryPanel({ projects }: { projects: Project[] }) {
  const [scope, setScope] = useState<MemoryScope>("user");
  const [projectId, setProjectId] = useState("");
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [content, setContent] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedProjectId = projectId || projects[0]?.id || "";
  const visibleEntries = scope === "project" && !selectedProjectId ? [] : entries;
  const visibleLoading = loading && !(scope === "project" && !selectedProjectId);

  useEffect(() => {
    if (scope === "project" && !selectedProjectId) return;
    const controller = new AbortController();
    getMemory(scope, scope === "project" ? selectedProjectId : undefined, controller.signal)
      .then((result) => setEntries(result.memories))
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : "Memory is unavailable.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scope, selectedProjectId]);

  const changeScope = (nextScope: MemoryScope) => {
    setScope(nextScope);
    setLoading(true);
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!content.trim() || saving || (scope === "project" && !selectedProjectId)) return;
    setSaving(true);
    setError(null);
    try {
      const entry = await addMemory(
        scope,
        content.trim(),
        scope === "project" ? selectedProjectId : undefined,
      );
      setEntries((current) => [...current, entry]);
      setContent("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save memory.");
    } finally {
      setSaving(false);
    }
  };

  const saveEdit = async (id: string) => {
    if (!editingContent.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMemory(id, editingContent.trim());
      setEntries((current) => current.map((entry) => (entry.id === id ? updated : entry)));
      setEditingId(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update memory.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    setSaving(true);
    setError(null);
    try {
      await deleteMemory(id);
      setEntries((current) => current.filter((entry) => entry.id !== id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete memory.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="memory" aria-labelledby="memory-title">
      <div className="section-label">
        <span>04</span><h2 id="memory-title">MEMORY</h2><i />
        <div className="memory-tabs" aria-label="Memory scope">
          <button className={scope === "user" ? "active" : ""} onClick={() => changeScope("user")}>USER MEMORY</button>
          <button className={scope === "project" ? "active" : ""} onClick={() => changeScope("project")}>PROJECT MEMORY</button>
        </div>
      </div>
      {scope === "project" && (
        <label className="memory-project">PROJECT
          <select aria-label="Memory project" value={selectedProjectId} onChange={(event) => { setProjectId(event.target.value); setLoading(true); setError(null); }}>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
      )}
      <div className="memory-console">
        <form className="memory-add" onSubmit={submit}>
          <Database size={16} />
          <label className="sr-only" htmlFor="memory-content">Memory content</label>
          <input id="memory-content" value={content} onChange={(event) => setContent(event.target.value)} maxLength={500} placeholder={scope === "user" ? "Add a durable preference..." : "Add a project fact..."} />
          <button type="submit" disabled={!content.trim() || saving || (scope === "project" && !selectedProjectId)}><Plus size={15} /> SAVE</button>
        </form>
        {error && <p className="memory-error" role="alert">{error}</p>}
        <div className="memory-list" aria-live="polite">
          {visibleLoading ? <p className="memory-empty">LOADING MEMORY...</p> : visibleEntries.length === 0 ? <p className="memory-empty">NO {scope.toUpperCase()} MEMORY</p> : visibleEntries.map((entry) => (
            <article key={entry.id}>
              {editingId === entry.id ? (
                <input aria-label="Edit memory" value={editingContent} maxLength={500} onChange={(event) => setEditingContent(event.target.value)} />
              ) : <p>{entry.content}</p>}
              <div>
                {editingId === entry.id ? <>
                  <button aria-label="Save memory edit" onClick={() => saveEdit(entry.id)} disabled={saving}><Check size={14} /></button>
                  <button aria-label="Cancel memory edit" onClick={() => setEditingId(null)}><X size={14} /></button>
                </> : <button aria-label="Edit memory" onClick={() => { setEditingId(entry.id); setEditingContent(entry.content); }}><Pencil size={14} /></button>}
                <button aria-label="Delete memory" onClick={() => remove(entry.id)} disabled={saving}><Trash2 size={14} /></button>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
