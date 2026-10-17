import { ChatApi } from '../api/client.mjs';
import type { Capabilities, Candidate, Event, Evidence, ImageReference, Message, Page, Run, Session } from './types';

const baseUrl = '';
let token = '';
let client = new ChatApi(baseUrl);

export function setApiToken(value: string) {
  token = value.trim();
  client = new ChatApi(baseUrl, { token });
}

export const api = {
  capabilities: () => client.request('/api/v1/capabilities') as Promise<Capabilities>,
  sessions: (archived = false, offset = 0) => client.request(`/api/v1/conversations?archived=${archived}&limit=100&offset=${offset}`) as Promise<Page<Session>>,
  create: (title = 'New exploration') => client.create(title) as Promise<Session>,
  session: (id: string) => client.request(`/api/v1/conversations/${encodeURIComponent(id)}`) as Promise<Session>,
  update: (id: string, body: { title?: string; archived?: boolean }) => client.request(`/api/v1/conversations/${encodeURIComponent(id)}`, { method: 'PATCH', body }) as Promise<Session>,
  delete: (id: string) => client.request(`/api/v1/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }) as Promise<void>,
  messages: (id: string, offset = 0) => client.request(`/api/v1/conversations/${encodeURIComponent(id)}/messages?limit=100&offset=${offset}`) as Promise<Page<Message>>,
  send: (id: string, body: { text?: string; image_id?: string; selected_plant_id?: string }, requestId: string) => client.send(id, body, requestId) as Promise<Run>,
  clarify: (id: string, body: { request_id: string; clarification_id: string; text: string; selected_plant_id?: string; image_id?: string }) => client.request(`/api/v1/conversations/${encodeURIComponent(id)}/clarifications`, { method: 'POST', body }) as Promise<Run>,
  autocomplete: (q: string, signal?: AbortSignal) => client.request(`/api/v1/discovery/autocomplete?q=${encodeURIComponent(q)}`, { signal }) as Promise<{ implemented: boolean; detail: string; candidates: Candidate[] }>,
  run: (id: string) => client.request(`/api/v1/runs/${encodeURIComponent(id)}`) as Promise<Run>,
  cancel: (id: string) => client.cancel(id) as Promise<Run>,
  resume: (id: string) => client.request(`/api/v1/runs/${encodeURIComponent(id)}/resume`, { method: 'POST' }) as Promise<Run>,
  events: (id: string, signal: AbortSignal) => client.events(id, { after: 0, signal }) as AsyncIterable<Event>,
  evidence: (id: string) => client.request(`/api/v1/runs/${encodeURIComponent(id)}/evidence`) as Promise<{ items: Evidence[] }>,
  async upload(id: string, file: File): Promise<ImageReference> {
    const response = await fetch(`${baseUrl}/api/v1/conversations/${encodeURIComponent(id)}/images`, {
      method: 'POST',
      headers: { 'Content-Type': file.type, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: file,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const error = new Error(body.message || `Image upload failed (${response.status})`);
      Object.assign(error, { code: body.code, status: response.status });
      throw error;
    }
    return response.json();
  },
};
