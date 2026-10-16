export interface HealthStatus {
  status: string;
  app_env: string;
  database: string;
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch('/api/v1/health');
  if (!response.ok) {
    throw new Error(`Health check request failed with HTTP status ${response.status}`);
  }
  return response.json();
}
