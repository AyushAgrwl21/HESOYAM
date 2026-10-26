export class ApiRequestError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly detail: string;

  constructor(status: number, errorCode: string, detail: string) {
    super(detail);
    this.name = "ApiRequestError";
    this.status = status;
    this.errorCode = errorCode;
    this.detail = detail;
  }
}

export function apiUrl(path: string): string {
  const configuredBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  return `${configuredBase}${path}`;
}

export async function getJson(path: string, abortSignal: AbortSignal): Promise<unknown> {
  const url = apiUrl(path);
  let response: Response;
  try {
    response = await fetch(url, {
      signal: abortSignal,
      headers: { Accept: "application/json" },
    });
  } catch (networkError: unknown) {
    if (abortSignal.aborted) {
      throw networkError;
    }
    throw new Error(
      `Could not reach the API at ${url}. Start the backend, or set VITE_API_BASE_URL to the API origin.`,
    );
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const parsed = readErrorBody(body);
    throw new ApiRequestError(
      response.status,
      parsed?.errorCode ?? "http_error",
      parsed?.detail ?? `The request failed with HTTP ${response.status}.`,
    );
  }
  return response.json() as Promise<unknown>;
}

export function messageFrom(error: unknown): string {
  if (error instanceof ApiRequestError) {
    return `${error.detail} (HTTP ${error.status}, ${error.errorCode})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "The request failed without an error message.";
}

function readErrorBody(body: unknown): { errorCode: string; detail: string } | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  const errorCode = Reflect.get(body, "error_code");
  const detail = Reflect.get(body, "detail");
  if (typeof errorCode !== "string" || typeof detail !== "string" || detail.length === 0) {
    return null;
  }
  return { errorCode, detail };
}
