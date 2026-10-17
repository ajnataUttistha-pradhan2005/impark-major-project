/** Framework-independent client. Public schemas live in ../contracts/. */
export class ApiError extends Error {
  constructor(status, body) {
    super(body.message || `HTTP ${status}`);
    this.status = status;
    this.code = body.code || "HTTP_ERROR";
    this.correlationId = body.correlation_id;
  }
}

export class ChatApi {
  constructor(baseUrl, { token, fetcher = globalThis.fetch } = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    // Browser-native fetch can reject calls whose receiver is a ChatApi instance.
    this.fetcher = (...args) => fetcher.call(globalThis, ...args);
  }

  async request(path, { method = "GET", body, signal, headers = {} } = {}) {
    const response = await this.fetcher(this.baseUrl + path, {
      method, signal,
      headers: {
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      throw new ApiError(response.status, await response.json().catch(() => ({})));
    }
    return response.status === 204 ? undefined : response.json();
  }

  create(title = "New chat") {
    return this.request("/api/v1/conversations", { method: "POST", body: { title } });
  }

  send(sessionId, input, requestId = crypto.randomUUID()) {
    return this.request(`/api/v1/conversations/${encodeURIComponent(sessionId)}/turns`, {
      method: "POST", body: { ...input, request_id: requestId },
    });
  }

  cancel(operationId) {
    return this.request(`/api/v1/runs/${encodeURIComponent(operationId)}/cancel`, { method: "POST" });
  }

  async *events(operationId, { after = 0, signal } = {}) {
    const response = await this.fetcher(
      `${this.baseUrl}/api/v1/runs/${encodeURIComponent(operationId)}/events?after=${after}`, {
        signal,
        headers: {
          Accept: "text/event-stream",
          ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        },
      },
    );
    if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => ({})));
    if (!response.body) throw new Error("Missing event stream");
    let sequence = after;
    for await (const event of parseEvents(response.body)) {
      if (event.version !== 1 || event.operation_id !== operationId ||
          !Number.isSafeInteger(event.sequence) || typeof event.type !== "string") {
        throw new Error("Invalid event envelope");
      }
      if (event.sequence <= sequence) continue;
      if (event.sequence !== sequence + 1) throw new Error("Event gap; reload run history");
      sequence = event.sequence;
      yield event;
    }
  }
}

/** Handles UTF-8/line/frame splits, comments and multiline SSE data. */
export async function* parseEvents(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lines = [];
  let frameSize = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);
        frameSize += line.length;
        if (frameSize > 1_000_000) throw new Error("Event frame too large");
        if (line === "") {
          if (lines.length) yield JSON.parse(lines.join("\n"));
          lines = [];
          frameSize = 0;
        } else if (line.startsWith("data:")) {
          lines.push(line.slice(5).replace(/^ /, ""));
        }
      }
      if (buffer.length > 1_000_000) throw new Error("Event frame too large");
      if (done) {
        if (lines.length || buffer.trim()) throw new Error("Interrupted SSE frame; reconnect");
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
