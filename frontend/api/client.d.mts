export class ApiError extends Error {
  status: number;
  code: string;
  correlationId?: string;
  constructor(status: number, body: { code?: string; message?: string; correlation_id?: string });
}

export class ChatApi {
  baseUrl: string;
  token?: string;
  constructor(baseUrl: string, options?: { token?: string; fetcher?: typeof fetch });
  request(path: string, options?: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    headers?: Record<string, string>;
  }): Promise<unknown>;
  create(title?: string): Promise<unknown>;
  send(sessionId: string, input: object, requestId?: string): Promise<unknown>;
  cancel(operationId: string): Promise<unknown>;
  events(operationId: string, options?: { after?: number; signal?: AbortSignal }): AsyncIterable<unknown>;
}

export function parseEvents(stream: ReadableStream<Uint8Array>): AsyncIterable<unknown>;
