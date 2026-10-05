"use client";

import { RotateCcw, Sparkles } from "lucide-react";
import type { SkillsResponse } from "@/lib/api";

export function SkillsPanel({ data, loading, unavailable, onRetry }: { data: SkillsResponse | null; loading: boolean; unavailable: boolean; onRetry: () => void }) {
  return (
    <section className="skills" aria-labelledby="skills-title">
      <div className="section-label"><span>04</span><h2 id="skills-title">SKILLS</h2><i /></div>
      {unavailable ? (
        <div className="panel-empty panel-unavailable" role="status">
          <p>SKILL REGISTRY UNAVAILABLE</p>
          <button type="button" onClick={onRetry} disabled={loading}>
            <RotateCcw size={12} />{loading ? "RETRYING SKILL REGISTRY" : "RETRY SKILL REGISTRY"}
          </button>
        </div>
      ) : loading && !data ? (
        <div className="panel-empty">SKILL REGISTRY SYNCHRONISING</div>
      ) : (
        <div className="skill-console">
          {data?.skills.map((skill) => (
            <article key={skill.name}>
              <Sparkles aria-hidden="true" size={15} />
              <div><h3>{skill.name.replaceAll("-", " ")}</h3><p>{skill.description}</p></div>
              <span>{`${skill.scope} // V${skill.version} // READY`}</span>
            </article>
          ))}
          {data?.count === 0 && <p className="skill-empty">NO SKILLS AVAILABLE</p>}
        </div>
      )}
    </section>
  );
}
