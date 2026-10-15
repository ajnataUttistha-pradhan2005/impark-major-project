import test from "node:test";
import assert from "node:assert/strict";
import { ChatApi, ApiError, parseEvents } from "./client.mjs";

function bytes(text) {
  const data = new TextEncoder().encode(text);
  return new ReadableStream({ start(c) { for (const b of data) c.enqueue(Uint8Array.of(b)); c.close(); } });
}

test("SSE handles every byte boundary including Unicode and CRLF", async () => {
  const stream = bytes(': heartbeat\r\n\r\nid: 1\r\ndata: {"text":"तुलसी"}\r\n\r\ndata: {\n' +
                       'data: "ok":true}\n\n');
  assert.deepEqual(await Array.fromAsync(parseEvents(stream)), [{ text: "तुलसी" }, { ok: true }]);
});

test("partial frames require reconnection instead of silently dropping data", async () => {
  await assert.rejects(async () => Array.fromAsync(parseEvents(bytes('data: {"a":1}\n'))));
});

test("request forwards bearer and a caller-owned idempotency key", async () => {
  const api = new ChatApi("http://test/", { token: "test-token", fetcher: async (url, init) => {
    assert.equal(url, "http://test/api/v1/conversations/session/turns");
    assert.equal(init.headers.Authorization, "Bearer test-token");
    assert.equal(JSON.parse(init.body).request_id, "stable-id");
    return Response.json({ operation_id: "stable-id" });
  } });
  assert.deepEqual(await api.send("session", { text: "neem" }, "stable-id"), { operation_id: "stable-id" });
});

test("safe API errors preserve code and correlation", async () => {
  const api = new ChatApi("http://test", { fetcher: async () => Response.json({
    code: "CONFLICT", message: "Busy", correlation_id: "correlation",
  }, { status: 409 }) });
  await assert.rejects(api.create(), e => e instanceof ApiError && e.code === "CONFLICT" &&
    e.correlationId === "correlation");
});

test("event iterator deduplicates replay and rejects sequence gaps", async () => {
  const event = (sequence) => `data: ${JSON.stringify({ version: 1, operation_id: "op", sequence, type: "progress" })}\n\n`;
  const api = new ChatApi("http://test", { fetcher: async () => new Response(bytes(event(1) + event(2))) });
  assert.equal((await Array.fromAsync(api.events("op", { after: 1 }))).length, 1);
  const broken = new ChatApi("http://test", { fetcher: async () => new Response(bytes(event(3))) });
  await assert.rejects(async () => Array.fromAsync(broken.events("op")), /Event gap/);
});
