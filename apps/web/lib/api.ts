export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/health`, { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
  const data = (await response.json()) as Partial<HealthResponse>;
  if (data.status !== "ok" || typeof data.service !== "string" || typeof data.version !== "string") {
    throw new Error("Invalid health response");
  }
  return data as HealthResponse;
}
