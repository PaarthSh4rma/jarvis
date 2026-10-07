"use client";

import { Code2, ExternalLink, FolderOpen, GitBranch, RotateCcw } from "lucide-react";
import type { Project, ProjectsResponse } from "@/lib/api";

type ProjectPanelProps = {
  data: ProjectsResponse | null;
  loading: boolean;
  unavailable: boolean;
  actionsDisabled: boolean;
  onRetry: () => void;
  onCommand: (command: string) => void;
};

export function ProjectPanel({ data, loading, unavailable, actionsDisabled, onRetry, onCommand }: ProjectPanelProps) {
  const cards = uniqueProjects(data?.projects.length ? data.projects : data?.recent_projects ?? []);
  const recentIds = new Set(data?.recent_projects.map((project) => project.id) ?? []);

  return (
    <section className="projects" aria-labelledby="projects-title">
      <div className="section-label">
        <span>02</span><h2 id="projects-title">PROJECTS</h2><i />
        {data && <p className="section-summary"><span>{data.count}</span> DISCOVERED // <span>{data.dirty_count}</span> DIRTY</p>}
      </div>
      {unavailable ? (
        <div className="panel-empty panel-unavailable" role="status">
          <p>PROJECT INDEX UNAVAILABLE</p>
          <button type="button" onClick={onRetry} disabled={loading}>
            <RotateCcw size={12} />{loading ? "RETRYING PROJECT INDEX" : "RETRY PROJECT INDEX"}
          </button>
        </div>
      ) : loading && !data ? (
        <div className="panel-empty">PROJECT INDEX SYNCHRONISING</div>
      ) : cards.length === 0 ? (
        <div className="panel-empty">NO PROJECTS DISCOVERED</div>
      ) : (
        <div className="project-grid">
          {cards.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              recent={recentIds.has(project.id)}
              disabled={actionsDisabled}
              onCommand={onCommand}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ProjectCard({ project, recent, disabled, onCommand }: { project: Project; recent: boolean; disabled: boolean; onCommand: (command: string) => void }) {
  const repoState = project.is_dirty === null ? "STATE UNKNOWN" : project.is_dirty ? "DIRTY" : "CLEAN";
  return (
    <article className="project-card">
      <header>
        <div>
          <span className="project-kicker">{recent ? "RECENT ACTIVITY" : project.is_git_repository ? "GIT REPOSITORY" : "LOCAL PROJECT"}</span>
          <h3>{project.name}</h3>
        </div>
        <span className={`repo-state ${project.is_dirty ? "dirty" : ""}`}>{repoState}</span>
      </header>
      <div className="project-branch"><GitBranch size={13} aria-hidden="true" /><span>{project.branch ?? "NO BRANCH"}</span></div>
      <p className="project-commit">{project.latest_commit_message ?? "No Git commit recorded"}</p>
      <div className="tech-list" aria-label={`${project.name} technologies`}>
        {project.technologies.length > 0 ? project.technologies.map((technology) => <span key={technology}>{technology}</span>) : <span>LOCAL</span>}
      </div>
      <div className="project-actions">
        <button type="button" disabled={disabled} onClick={() => onCommand(`Check the status of ${project.name}.`)} aria-label={`Check ${project.name} status`}>
          <Code2 size={13} /> STATUS
        </button>
        <button type="button" disabled={disabled} onClick={() => onCommand(`Open ${project.name} in VS Code.`)} aria-label={`Open ${project.name} in VS Code`}>
          <ExternalLink size={13} /> VS CODE
        </button>
        <button type="button" disabled={disabled} onClick={() => onCommand(`Open ${project.name} in Finder.`)} aria-label={`Show ${project.name} in Finder`}>
          <FolderOpen size={13} /> FINDER
        </button>
      </div>
    </article>
  );
}

function uniqueProjects(projects: Project[]): Project[] {
  return Array.from(new Map(projects.map((project) => [project.id, project])).values());
}
