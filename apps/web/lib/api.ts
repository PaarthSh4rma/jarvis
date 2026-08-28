export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
  ollama: "online" | "offline";
  model: string;
};

export type ChatResponse = {
  response: string;
  model: string;
  assistant: "jarvis";
};

export type Project = {
  id: string;
  name: string;
  is_git_repository: boolean;
  branch: string | null;
  is_dirty: boolean | null;
  latest_commit_message: string | null;
  latest_commit_timestamp: string | null;
  technologies: string[];
};

export type ProjectsResponse = {
  projects: Project[];
  recent_projects: Project[];
  count: number;
  dirty_count: number;
};

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
  }
}

type BrowserLocation = Pick<Location, "hostname" | "protocol">;

export function resolveApiUrl(
  configuredUrl: string | undefined,
  browserLocation?: BrowserLocation,
): string {
  if (configuredUrl?.trim()) return configuredUrl.replace(/\/$/, "");
  if (browserLocation) return `${browserLocation.protocol}//${browserLocation.hostname}:8000`;
  return "http://localhost:8000";
}

function getApiUrl(): string {
  const browserLocation = typeof window === "undefined" ? undefined : window.location;
  return resolveApiUrl(process.env.NEXT_PUBLIC_API_URL, browserLocation);
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${getApiUrl()}/health`, { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
  const data = (await response.json()) as Partial<HealthResponse>;
  if (
    data.status !== "ok" ||
    typeof data.service !== "string" ||
    typeof data.version !== "string" ||
    !["online", "offline"].includes(data.ollama ?? "") ||
    typeof data.model !== "string"
  ) {
    throw new Error("Invalid health response");
  }
  return data as HealthResponse;
}

export async function sendChat(message: string, signal?: AbortSignal): Promise<ChatResponse> {
  const response = await fetch(`${getApiUrl()}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!response.ok) {
    let detail = "JARVIS could not complete the request.";
    try {
      const data = (await response.json()) as { detail?: string };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {}
    throw new ApiError(detail, response.status);
  }
  const data = (await response.json()) as Partial<ChatResponse>;
  if (typeof data.response !== "string" || typeof data.model !== "string" || data.assistant !== "jarvis") {
    throw new ApiError("The assistant returned an invalid response.");
  }
  return data as ChatResponse;
}

export async function getProjects(signal?: AbortSignal): Promise<ProjectsResponse> {
  const response = await fetch(`${getApiUrl()}/projects`, { cache: "no-store", signal });
  if (!response.ok) throw new ApiError("Project index is unavailable.", response.status);
  const data = (await response.json()) as Partial<ProjectsResponse>;
  if (!Array.isArray(data.projects) || !Array.isArray(data.recent_projects) || typeof data.count !== "number" || typeof data.dirty_count !== "number") {
    throw new ApiError("The project index returned an invalid response.");
  }
  return data as ProjectsResponse;
}
