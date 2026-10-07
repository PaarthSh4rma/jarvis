export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
  ollama: "online" | "offline";
  model: string;
  demo_mode: boolean;
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

export type Skill = {
  name: string;
  description: string;
  scope: "project";
  version: number;
};

export type SkillsResponse = {
  skills: Skill[];
  count: number;
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

export type HermesStatus = {
  state: "ONLINE" | "OFFLINE" | "DEGRADED" | "UNKNOWN";
  version: string | null;
  capabilities: string[];
  checked_at: string;
  last_successful_check: string | null;
  reason: "verified" | "unavailable" | "authentication_required" | "invalid_response" | "http_error";
};

const hermesCapabilities = new Set([
  "run_submission", "run_status", "run_events_sse", "run_stop",
  "run_approval_response", "session_resources",
]);

async function getHermesStatus(path: "health" | "capabilities", signal?: AbortSignal): Promise<HermesStatus> {
  const response = await fetch(`${getApiUrl()}/integrations/hermes/${path}`, { cache: "no-store", signal });
  if (!response.ok) throw new ApiError("Hermes status is unavailable.", response.status);
  const data = (await response.json()) as Partial<HermesStatus> | null;
  if (!data || !["ONLINE", "OFFLINE", "DEGRADED", "UNKNOWN"].includes(data.state ?? "")
    || !(data.version === null || (typeof data.version === "string" && /^[a-zA-Z0-9.+_-]{1,64}$/.test(data.version)))
    || !Array.isArray(data.capabilities) || data.capabilities.length > 6
    || !data.capabilities.every((item) => hermesCapabilities.has(item))
    || typeof data.checked_at !== "string" || !Number.isFinite(Date.parse(data.checked_at))
    || !(data.last_successful_check === null || (typeof data.last_successful_check === "string" && Number.isFinite(Date.parse(data.last_successful_check))))
    || !["verified", "unavailable", "authentication_required", "invalid_response", "http_error"].includes(data.reason ?? "")) {
    throw new ApiError("Hermes returned an invalid status response.");
  }
  return data as HermesStatus;
}

export const getHermesHealth = (signal?: AbortSignal) => getHermesStatus("health", signal);
export const getHermesCapabilities = (signal?: AbortSignal) => getHermesStatus("capabilities", signal);

export type MissionType = "CODE_CHANGE" | "PROJECT_REVIEW" | "JOB_APPLICATION" | "RESEARCH" | "INTERVIEW_PREP" | "MONEY_EXPERIMENT" | "ADMIN";
export type MissionStatus = "DRAFT" | "READY" | "RUNNING" | "WAITING_FOR_APPROVAL" | "COMPLETED" | "FAILED" | "CANCELLED";

export type Mission = {
  id: string;
  type: MissionType;
  title: string;
  goal: string;
  project_id: string | null;
  context: string | null;
  requested_by: string;
  status: MissionStatus;
  created_at: string;
  updated_at: string;
  revision: number;
  external_execution_id: string | null;
  result_summary: string | null;
  failure_summary: string | null;
};

export type MissionCreateInput = {
  type: MissionType;
  title: string;
  goal: string;
  project_id: string | null;
  context: string | null;
};

export type MissionPatchInput = Partial<Pick<Mission, "title" | "goal" | "project_id" | "context">> & {
  expected_revision: number;
  status?: "DRAFT" | "READY" | "CANCELLED";
};

export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED";

export type Approval = {
  id: string;
  mission_id: string;
  action_type: string;
  summary: string;
  risk_context: string;
  status: ApprovalStatus;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
};

export type ApprovalResolution = {
  status: "APPROVED" | "REJECTED" | "CANCELLED";
  resolution_note: string | null;
};

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

export async function listMissions(signal?: AbortSignal): Promise<Mission[]> {
  const response = await fetch(`${getApiUrl()}/missions`, { cache: "no-store", signal });
  if (!response.ok) throw await apiError(response, "Mission registry is unavailable.");
  const data = (await response.json()) as unknown;
  if (!Array.isArray(data) || !data.every(isMission)) throw new ApiError("The mission registry returned an invalid response.");
  return data;
}

export async function getMission(missionId: string, signal?: AbortSignal): Promise<Mission> {
  const response = await fetch(`${getApiUrl()}/missions/${encodeURIComponent(missionId)}`, { cache: "no-store", signal });
  if (!response.ok) throw await apiError(response, "Could not load mission.");
  return parseMission(await response.json());
}

export async function createMission(input: MissionCreateInput): Promise<Mission> {
  const response = await fetch(`${getApiUrl()}/missions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "Could not create mission.");
  return parseMission(await response.json());
}

export async function updateMission(missionId: string, input: MissionPatchInput): Promise<Mission> {
  const response = await fetch(`${getApiUrl()}/missions/${encodeURIComponent(missionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "Could not update mission.");
  return parseMission(await response.json());
}

export async function listApprovals(signal?: AbortSignal): Promise<Approval[]> {
  const response = await fetch(`${getApiUrl()}/approvals`, { cache: "no-store", signal });
  if (!response.ok) throw await apiError(response, "Approval registry is unavailable.");
  const data = (await response.json()) as unknown;
  if (!Array.isArray(data) || !data.every(isApproval)) throw new ApiError("The approval registry returned an invalid response.");
  return data;
}

export async function resolveApproval(approvalId: string, input: ApprovalResolution): Promise<Approval> {
  const response = await fetch(`${getApiUrl()}/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "Could not record approval decision.");
  const data = (await response.json()) as unknown;
  if (!isApproval(data)) throw new ApiError("The approval registry returned an invalid response.");
  return data;
}

function parseMission(data: unknown): Mission {
  if (!isMission(data)) throw new ApiError("The mission registry returned an invalid response.");
  return data;
}

function isMission(data: unknown): data is Mission {
  if (!data || typeof data !== "object") return false;
  const item = data as Partial<Mission>;
  return typeof item.id === "string"
    && typeof item.title === "string"
    && typeof item.goal === "string"
    && typeof item.revision === "number"
    && ["DRAFT", "READY", "RUNNING", "WAITING_FOR_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"].includes(item.status ?? "");
}

function isApproval(data: unknown): data is Approval {
  if (!data || typeof data !== "object") return false;
  const item = data as Partial<Approval>;
  return typeof item.id === "string"
    && typeof item.mission_id === "string"
    && typeof item.summary === "string"
    && typeof item.risk_context === "string"
    && ["PENDING", "APPROVED", "REJECTED", "CANCELLED"].includes(item.status ?? "");
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
    || (data.demo_mode !== undefined && typeof data.demo_mode !== "boolean")
  ) {
    throw new Error("Invalid health response");
  }
  return { ...data, demo_mode: data.demo_mode ?? false } as HealthResponse;
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

export async function getSkills(signal?: AbortSignal): Promise<SkillsResponse> {
  const response = await fetch(`${getApiUrl()}/skills`, { cache: "no-store", signal });
  if (!response.ok) throw new ApiError("Skill registry is unavailable.", response.status);
  const data = (await response.json()) as Partial<SkillsResponse>;
  if (!Array.isArray(data.skills) || typeof data.count !== "number") {
    throw new ApiError("The skill registry returned an invalid response.");
  }
  return data as SkillsResponse;
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
