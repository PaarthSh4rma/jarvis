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
  conversation_id: string;
};

export type RunState = "QUEUED" | "RUNNING" | "WAITING_FOR_TOOL" | "CANCELLING" | "COMPLETED" | "FAILED" | "CANCELLED" | "TIMED_OUT";
export type RunResponse = {
  run_id: string;
  conversation_id: string;
  state: RunState;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};
export type RunEvent = {
  sequence: number;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
};

export type ConversationResponse = {
  conversation_id: string;
  expires_in_seconds: number;
  max_turns: number;
  max_characters: number;
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

export type MemoryScope = "user" | "project";

export type MemoryEntry = {
  id: string;
  scope: MemoryScope;
  project_id: string | null;
  project_name: string | null;
  content: string;
  created_at: string;
  updated_at: string;
};

export type MemoryListResponse = {
  memories: MemoryEntry[];
  max_user_entries: number;
  max_project_entries: number;
  max_characters: number;
  max_injected_characters: number;
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

export async function createConversation(signal?: AbortSignal): Promise<ConversationResponse> {
  const response = await fetch(`${getApiUrl()}/conversations`, {
    method: "POST",
    signal,
  });
  if (!response.ok) throw new ApiError("Could not create a conversation.", response.status);
  const data = (await response.json()) as Partial<ConversationResponse>;
  if (
    typeof data.conversation_id !== "string" ||
    typeof data.expires_in_seconds !== "number" ||
    typeof data.max_turns !== "number" ||
    typeof data.max_characters !== "number"
  ) {
    throw new ApiError("The conversation service returned an invalid response.");
  }
  return data as ConversationResponse;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`${getApiUrl()}/conversations/${conversationId}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404 && response.status !== 410) {
    throw new ApiError("Could not reset the conversation.", response.status);
  }
}

export async function sendChat(
  message: string,
  conversationId: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch(`${getApiUrl()}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
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
  if (
    typeof data.response !== "string" ||
    typeof data.model !== "string" ||
    data.assistant !== "jarvis" ||
    typeof data.conversation_id !== "string"
  ) {
    throw new ApiError("The assistant returned an invalid response.");
  }
  return data as ChatResponse;
}

export async function createRun(message: string, conversationId: string): Promise<RunResponse> {
  const response = await fetch(`${getApiUrl()}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!response.ok) throw await apiError(response, "Could not start execution.");
  const data = (await response.json()) as Partial<RunResponse>;
  if (typeof data.run_id !== "string" || typeof data.conversation_id !== "string" || typeof data.state !== "string") {
    throw new ApiError("The execution service returned an invalid response.");
  }
  return data as RunResponse;
}

export async function streamRun(
  runId: string,
  conversationId: string,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const query = new URLSearchParams({ conversation_id: conversationId });
  const response = await fetch(`${getApiUrl()}/runs/${runId}/events?${query}`, { signal });
  if (!response.ok || !response.body) throw await apiError(response, "Execution stream unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6)) as RunEvent;
      if (typeof event.sequence !== "number" || typeof event.type !== "string") throw new ApiError("Invalid execution event.");
      terminal = terminal || ["run.completed", "run.failed", "run.cancelled", "run.timed_out"].includes(event.type);
      onEvent(event);
    }
    if (done) break;
  }
  if (!terminal) throw new ApiError("Execution stream ended before a terminal state.");
}

export async function cancelRun(runId: string, conversationId: string): Promise<RunResponse> {
  const response = await fetch(`${getApiUrl()}/runs/${runId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
  if (!response.ok) throw await apiError(response, "Could not cancel execution.");
  return response.json() as Promise<RunResponse>;
}

async function apiError(response: Response, fallback: string): Promise<ApiError> {
  let detail = fallback;
  try {
    const data = (await response.json()) as { detail?: string };
    if (typeof data.detail === "string") detail = data.detail;
  } catch {}
  return new ApiError(detail, response.status);
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

export async function getMemory(
  scope: MemoryScope,
  projectId?: string,
  signal?: AbortSignal,
): Promise<MemoryListResponse> {
  const query = projectId
    ? `?scope=project&project_id=${encodeURIComponent(projectId)}`
    : `?scope=${scope}`;
  const response = await fetch(`${getApiUrl()}/memory${query}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new ApiError("Memory is unavailable.", response.status);
  const data = (await response.json()) as Partial<MemoryListResponse>;
  if (!Array.isArray(data.memories) || typeof data.max_characters !== "number") {
    throw new ApiError("The memory service returned an invalid response.");
  }
  return data as MemoryListResponse;
}

export async function addMemory(
  scope: MemoryScope,
  content: string,
  projectId?: string,
): Promise<MemoryEntry> {
  const response = await fetch(`${getApiUrl()}/memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope, content, project_id: projectId ?? null }),
  });
  return memoryMutationResponse(response, "Could not save memory.");
}

export async function updateMemory(memoryId: string, content: string): Promise<MemoryEntry> {
  const response = await fetch(`${getApiUrl()}/memory/${memoryId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return memoryMutationResponse(response, "Could not update memory.");
}

export async function deleteMemory(memoryId: string): Promise<void> {
  const response = await fetch(`${getApiUrl()}/memory/${memoryId}`, { method: "DELETE" });
  if (!response.ok) throw new ApiError("Could not delete memory.", response.status);
}

async function memoryMutationResponse(
  response: Response,
  fallback: string,
): Promise<MemoryEntry> {
  if (!response.ok) {
    let detail = fallback;
    try {
      const data = (await response.json()) as { detail?: string };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {}
    throw new ApiError(detail, response.status);
  }
  const data = (await response.json()) as Partial<MemoryEntry>;
  if (
    typeof data.id !== "string" ||
    !["user", "project"].includes(data.scope ?? "") ||
    typeof data.content !== "string"
  ) {
    throw new ApiError("The memory service returned an invalid response.");
  }
  return data as MemoryEntry;
}
