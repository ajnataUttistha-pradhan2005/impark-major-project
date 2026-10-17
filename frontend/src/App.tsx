'use client';

import { AlertCircle, Archive, ArrowRight, KeyRound, Leaf, RefreshCw, WifiOff, X } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, setApiToken } from './api';
import { Clarification } from './components/Clarification';
import { Conversation } from './components/Conversation';
import { Discovery, type DiscoveryMode } from './components/Discovery';
import { EvidencePanel } from './components/Evidence';
import { MobileMenuButton, Sidebar } from './components/Sidebar';
import { loadAllSessions } from './sessionPages.mjs';
import type { Candidate, Capabilities, ChatState, Event, Evidence, Message, Run, Session } from './types';

const DEFAULT_NOTICE = 'Each chat focuses on one plant. Start a new exploration to discuss another plant.';
const terminal = new Set(['complete', 'failed', 'cancelled', 'interrupted']);

function friendlyError(error: unknown): string {
  const item = error as { code?: string; message?: string; status?: number };
  switch (item?.code) {
    case 'UNAUTHORIZED': return 'The demo API needs an access key. Add one in Connection settings.';
    case 'FORBIDDEN': return 'This API is not enabled for the current environment.';
    case 'BACKEND_UNAVAILABLE': case 'UNAVAILABLE': return 'The backend is unavailable. Your input is still here; try again when it reconnects.';
    case 'PLANT_SCOPE_LOCKED': return 'This chat is locked to one plant. Start a new exploration for another plant.';
    case 'ARCHIVED': return 'Restore this archived chat before sending another question.';
    case 'BUSY': return 'The research service is busy. Please retry shortly.';
    case 'IDEMPOTENCY_CONFLICT': return 'This request was already used for different input. Refresh the chat before trying again.';
    case 'INVALID_IMAGE': return 'The image is invalid or its format does not match the file type. Choose another PNG, JPEG or WebP image.';
    case 'IMAGE_TOO_LARGE': return 'The image exceeds the upload size limit. Choose a smaller one.';
    case 'INVALID_CURSOR': return 'The response stream changed. Reconnect to rebuild the answer.';
    case 'CONFLICT': return 'This chat has another active or interrupted operation. Refresh it before continuing.';
    case 'NOT_FOUND': return 'That exploration is no longer available.';
    case 'VALIDATION_ERROR': return 'Please check your input and try again.';
    default: return item?.message && item.status && item.status < 500 ? item.message : 'Something went wrong. Your input is still available; try again.';
  }
}

function progressLabel(event: Event): string | null {
  if (event.type === 'run_started') return 'Reviewing your request…';
  if (event.type === 'response_started') return 'Preparing a sourced answer…';
  if (event.type !== 'progress') return null;
  const stage = event.payload.stage;
  if (stage === 'agent_invocation_started') return 'Checking the available plant information…';
  if (stage === 'response_context_built') return 'Preparing a sourced answer…';
  if (stage === 'clarification_requested') return 'Preparing a clarification…';
  return 'Reviewing the available evidence…';
}

async function allMessages(sessionId: string): Promise<Message[]> {
  const items: Message[] = [];
  let offset: number | null = 0;
  while (offset !== null && items.length < 1000) {
    const page = await api.messages(sessionId, offset);
    items.push(...page.items);
    offset = page.next_offset;
  }
  return items;
}

type RetryAction = { kind: 'turn' | 'clarification'; sessionId: string; body: Record<string, string>; requestId: string };

export default function App() {
  const router = useRouter();
  const pathname = usePathname();
  const routeSession = pathname?.match(/^\/chat\/([0-9a-f-]{36})$/i)?.[1] || null;
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [archivedView, setArchivedView] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [sessionLoading, setSessionLoading] = useState(Boolean(routeSession));
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [draftResponse, setDraftResponse] = useState('');
  const [progress, setProgress] = useState('');
  const [mode, setMode] = useState<DiscoveryMode>('name');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [suggestions, setSuggestions] = useState<Candidate[]>([]);
  const [searchState, setSearchState] = useState<'idle' | 'loading' | 'ready' | 'error' | 'unavailable'>('idle');
  const [uploadStatus, setUploadStatus] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [evidence, setEvidence] = useState<{ items: Evidence[]; citationIds: string[]; focusIndex?: number; missingCount: number; loading: boolean; error: string | null } | null>(null);
  const evidenceRequest = useRef(0);
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyDraft, setKeyDraft] = useState('');
  const streamController = useRef<AbortController | null>(null);
  const activeOperation = useRef<string | null>(null);
  const currentSession = useRef<string | null>(null);
  const retryAction = useRef<RetryAction | null>(null);
  const lastAcceptedAction = useRef<RetryAction | null>(null);
  const searchController = useRef<AbortController | null>(null);
  const sessionsRequest = useRef(0);
  const chatRefreshVersion = useRef(0);
  const createdDuringSubmit = useRef<string | null>(null);

  useEffect(() => { const stored = window.localStorage.getItem('impark.theme'); if (stored === 'light') setTheme('light'); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; window.localStorage.setItem('impark.theme', theme); }, [theme]);

  const refreshSessions = useCallback(async (view = archivedView) => {
    const request = ++sessionsRequest.current;
    setSessionsLoading(true); setSessionsError(null);
    try {
      const all = await loadAllSessions(api.sessions, view, () => request === sessionsRequest.current);
      if (!all) return;
      setSessions(all);
      setNextOffset(null);
    }
    catch (cause) { if (request === sessionsRequest.current) setSessionsError(friendlyError(cause)); }
    finally { if (request === sessionsRequest.current) setSessionsLoading(false); }
  }, [archivedView]);

  useEffect(() => { void refreshSessions(); api.capabilities().then(setCapabilities).catch(() => {}); }, [refreshSessions]);

  const refreshChat = useCallback(async (sid: string) => {
    const version = ++chatRefreshVersion.current;
    const [latest, history] = await Promise.all([api.session(sid), allMessages(sid)]);
    if (currentSession.current !== sid || chatRefreshVersion.current !== version) return;
    setSession(latest); setMessages(history);
    return { latest, history };
  }, []);

  const finalize = useCallback(async (oid: string, sid: string) => {
    const latestRun = await api.run(oid);
    if (activeOperation.current !== oid || currentSession.current !== sid) return;
    setRun(latestRun);
    if (latestRun.status === 'interrupted') { setProgress('This run was interrupted.'); return; }
    if (latestRun.status === 'accepted' || latestRun.status === 'running') return;
    if (latestRun.result) {
      setSession(previous => previous?.session_id === sid
        ? { ...previous, state: latestRun.result! }
        : previous);
    }
    await refreshChat(sid);
    setRun(null); setDraftResponse(''); setProgress(''); activeOperation.current = null;
    window.sessionStorage.removeItem(`impark.operation.${sid}`);
    if (latestRun.status === 'failed') { retryAction.current = lastAcceptedAction.current ? { ...lastAcceptedAction.current, requestId: crypto.randomUUID() } : null; setError(`This run could not be completed${latestRun.error_code ? ` (${latestRun.error_code})` : ''}. You can retry your request.`); }
    lastAcceptedAction.current = null;
    if (latestRun.status === 'cancelled') setError('The run was cancelled.');
    void refreshSessions();
  }, [refreshChat, refreshSessions]);

  useEffect(() => {
    if (!session?.state.active_plant || session.archived || session.state.mode !== 'conversation' || session.state.clarification) return;
    const confirmationKey = `impark.confirmed.${session.session_id}`;
    if (messages.filter(message => message.role === 'user').length > 1) {
      window.sessionStorage.setItem(confirmationKey, '1');
      setShowConfirmation(false);
    } else if (!window.sessionStorage.getItem(confirmationKey)) {
      setShowConfirmation(true);
    }
  }, [session, messages]);

  useEffect(() => {
    if (session?.state.status !== 'WAITING_USER' || !session.state.clarification || run) return;
    window.requestAnimationFrame(() => document.querySelector('.discovery-clarification')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  }, [session?.state.status, session?.state.clarification, run]);

  const monitor = useCallback(async (initial: Run, sid: string) => {
    streamController.current?.abort();
    const controller = new AbortController();
    streamController.current = controller;
    activeOperation.current = initial.operation_id;
    setRun(initial); setDraftResponse(''); setProgress('Reviewing your request…');
    window.sessionStorage.setItem(`impark.operation.${sid}`, initial.operation_id);
    for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt++) {
      try {
        let draft = '';
        for await (const event of api.events(initial.operation_id, controller.signal)) {
          if (controller.signal.aborted || activeOperation.current !== initial.operation_id || currentSession.current !== sid) return;
          const label = progressLabel(event);
          if (label) setProgress(label);
          if (event.type === 'response_started' || event.type === 'response_reset') { draft = ''; setDraftResponse(''); }
          if (event.type === 'response_delta') { draft += String(event.payload.text || ''); setDraftResponse(draft); }
          if (event.type === 'response_completed') { draft = String(event.payload.text || draft); setDraftResponse(draft); }
          if (event.type === 'run_completed' || event.type === 'run_failed' || event.type === 'run_cancelled' || event.type === 'run_interrupted') { await finalize(initial.operation_id, sid); return; }
        }
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (attempt === 3) setError(`The live response disconnected. ${friendlyError(cause)} Reconnect to continue.`);
      }
      if (controller.signal.aborted) return;
      try {
        const latest = await api.run(initial.operation_id);
        if (terminal.has(latest.status)) { await finalize(initial.operation_id, sid); return; }
      } catch { /* Keep reconnect available; session may be temporarily offline. */ }
      await new Promise(resolve => window.setTimeout(resolve, Math.min(1000 * (attempt + 1), 3000)));
    }
  }, [finalize]);

  useEffect(() => {
    if (routeSession && createdDuringSubmit.current === routeSession) {
      createdDuringSubmit.current = null;
      currentSession.current = routeSession;
      setSessionLoading(false);
      return;
    }
    createdDuringSubmit.current = null;
    chatRefreshVersion.current++;
    const version = chatRefreshVersion.current;
    currentSession.current = routeSession;
    streamController.current?.abort();
    activeOperation.current = null;
    lastAcceptedAction.current = null;
    setSession(null); setMessages([]); setRun(null); setDraftResponse(''); setError(null); setShowConfirmation(false);
    setMode('name'); setText(''); setFile(null); setSelected(null); setUploadStatus(''); setUploadError(null);
    if (!routeSession) { setSessionLoading(false); return; }
    let cancelled = false;
    setSessionLoading(true);
    (async () => {
      try {
        const [latest, history] = await Promise.all([api.session(routeSession), allMessages(routeSession)]);
        if (cancelled || currentSession.current !== routeSession || chatRefreshVersion.current !== version) return;
        setSession(latest); setMessages(history);
        const persisted = window.sessionStorage.getItem(`impark.operation.${routeSession}`);
        const pending = [...history].reverse().find(item => item.role === 'assistant' && ['pending', 'streaming', 'interrupted'].includes(item.status));
        const oid = persisted || pending?.operation_id;
        if (oid) {
          const savedRun = await api.run(oid);
          if (cancelled) return;
          if (savedRun.status === 'accepted' || savedRun.status === 'running') void monitor(savedRun, routeSession);
          else if (savedRun.status === 'interrupted') { activeOperation.current = oid; setRun(savedRun); }
          else window.sessionStorage.removeItem(`impark.operation.${routeSession}`);
        }
      } catch (cause) { if (!cancelled) setError(friendlyError(cause)); }
      finally { if (!cancelled) setSessionLoading(false); }
    })();
    return () => { cancelled = true; streamController.current?.abort(); };
  // Route changes are the only trigger; run monitoring is deliberately not restarted by state updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeSession]);

  useEffect(() => {
    searchController.current?.abort();
    if (mode !== 'name' || selected || !text.trim()) { setSuggestions([]); setSearchState('idle'); return; }
    const controller = new AbortController(); searchController.current = controller;
    setSearchState('loading');
    const timer = window.setTimeout(async () => {
      try {
        const result = await api.autocomplete(text.trim(), controller.signal);
        if (controller.signal.aborted) return;
        setSuggestions(result.candidates); setSearchState(result.implemented ? 'ready' : 'unavailable');
      } catch { if (!controller.signal.aborted) setSearchState('error'); }
    }, 300);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [mode, text, selected]);

  async function startNew() {
    setError(null);
    try { const created = await api.create(); setArchivedView(false); setSessions(list => [created, ...list]); router.push(`/chat/${created.session_id}`); void refreshSessions(false); }
    catch (cause) { setError(friendlyError(cause)); }
  }

  async function loadMore() {
    if (nextOffset === null) return;
    try { const page = await api.sessions(archivedView, nextOffset); setSessions(list => [...list, ...page.items.filter(item => !list.some(old => old.session_id === item.session_id))]); setNextOffset(page.next_offset); }
    catch (cause) { setSessionsError(friendlyError(cause)); }
  }

  async function updateSession(id: string, patch: { title?: string; archived?: boolean }) {
    try { const changed = await api.update(id, patch); if (patch.archived !== undefined) { setSessions(list => list.filter(item => item.session_id !== id)); if (routeSession === id) { if (patch.archived) router.push('/'); else setSession(changed); } if (!patch.archived) setArchivedView(false); } else { setSessions(list => list.map(item => item.session_id === id ? changed : item)); if (routeSession === id) setSession(changed); } }
    catch (cause) { setError(friendlyError(cause)); }
  }

  async function deleteSession(id: string) {
    try { await api.delete(id); setSessions(list => list.filter(item => item.session_id !== id)); window.sessionStorage.removeItem(`impark.operation.${id}`); if (routeSession === id) router.push('/'); void refreshSessions(); }
    catch (cause) { setError(friendlyError(cause)); }
  }

  async function executeAction(action: RetryAction) {
    setBusy(true); setError(null);
    try {
      const started = action.kind === 'turn'
        ? await api.send(action.sessionId, action.body, action.requestId)
        : await api.clarify(action.sessionId, { ...action.body, request_id: action.requestId, clarification_id: action.body.clarification_id, text: action.body.text });
      retryAction.current = null;
      lastAcceptedAction.current = action;
      if (currentSession.current !== action.sessionId) router.push(`/chat/${action.sessionId}`);
      setText(''); setFile(null); setSelected(null); setUploadStatus('');
      setRun(started);
      void refreshChat(action.sessionId);
      void monitor(started, action.sessionId);
    } catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(false); }
  }

  async function ensureSession(): Promise<string> {
    if (session) return session.session_id;
    const created = await api.create();
    createdDuringSubmit.current = created.session_id;
    currentSession.current = created.session_id; setSession(created); setArchivedView(false); setSessions(list => [created, ...list]);
    router.push(`/chat/${created.session_id}`);
    return created.session_id;
  }

  async function submit() {
    if (busy || run) return;
    const currentText = text.trim();
    const usePhoto = session?.state.mode === 'conversation' || mode === 'photo' || mode === 'combined';
    const selectedCandidate = session?.state.mode === 'conversation' || mode === 'photo' ? null : selected;
    const textToSend = selectedCandidate && mode === 'name'
      ? ''
      : session?.state.mode === 'conversation' || mode !== 'photo' ? currentText : '';
    if (!textToSend && !selectedCandidate && !(usePhoto && file)) { setError('Enter a plant name or description, or choose a photo.'); return; }
    setBusy(true); setError(null);
    try {
      const sid = await ensureSession();
      let imageId: string | undefined;
      if (usePhoto && file) { setUploadStatus('Uploading…'); const image = await api.upload(sid, file); imageId = image.image_id; setUploadStatus('Uploaded'); }
      const body: Record<string, string> = {};
      if (textToSend) body.text = textToSend;
      if (selectedCandidate) body.selected_plant_id = selectedCandidate.plant_id;
      if (imageId) body.image_id = imageId;
      const action: RetryAction = { kind: 'turn', sessionId: sid, body, requestId: crypto.randomUUID() };
      retryAction.current = action;
      setBusy(false); await executeAction(action);
    } catch (cause) { setError(friendlyError(cause)); setUploadStatus('Upload failed'); setBusy(false); }
  }

  async function clarify(reply: string, selectedId?: string) {
    if (busy || run || !session?.state.clarification) return;
    const body: Record<string, string> = { clarification_id: session.state.clarification.clarification_id, text: reply };
    const action: RetryAction = { kind: 'clarification', sessionId: session.session_id, body: selectedId ? { ...body, selected_plant_id: selectedId } : body, requestId: crypto.randomUUID() };
    retryAction.current = action;
    await executeAction(action);
  }

  async function submitDiscovery() {
    if (session?.state.status === 'WAITING_USER' && session.state.clarification) {
      if (selected) {
        const offered = session.state.clarification.candidates.some(
          candidate => candidate.plant_id === selected.plant_id
        );
        if (offered) await clarify(`Confirmed ${selected.label}`, selected.plant_id);
        else await clarify(selected.label);
        return;
      }
      if (file && (mode === 'photo' || mode === 'combined')) {
        setBusy(true); setUploadStatus('Uploading…');
        try { const image = await api.upload(session.session_id, file); setUploadStatus('Uploaded'); const action: RetryAction = { kind: 'clarification', sessionId: session.session_id, body: { clarification_id: session.state.clarification.clarification_id, text: text.trim() || 'Updated image', image_id: image.image_id }, requestId: crypto.randomUUID() }; retryAction.current = action; setBusy(false); await executeAction(action); }
        catch (cause) { setBusy(false); setUploadStatus('Upload failed'); setError(friendlyError(cause)); }
        return;
      }
      if (text.trim()) { await clarify(text.trim()); return; }
    }
    await submit();
  }

  async function cancelRun() {
    if (!run) return;
    try { streamController.current?.abort(); await api.cancel(run.operation_id); await finalize(run.operation_id, run.session_id); }
    catch (cause) { setError(friendlyError(cause)); }
  }

  async function resumeRun() {
    if (!run) return;
    try { const resumed = await api.resume(run.operation_id); void monitor(resumed, resumed.session_id); }
    catch (cause) { setError(friendlyError(cause)); try { setRun(await api.run(run.operation_id)); } catch { /* Keep previous state. */ } }
  }

  async function showSources(operationId: string, ids: string[], focusIndex?: number) {
    const request = ++evidenceRequest.current;
    setEvidence({ items: [], citationIds: ids, focusIndex, missingCount: 0, loading: true, error: null });
    try {
      const page = await api.evidence(operationId);
      if (request !== evidenceRequest.current) return;
      const byId = new Map(page.items.map(item => [item.evidence_id, item]));
      const ordered = [...new Set(ids)].map(id => byId.get(id));
      setEvidence({ items: ordered.filter((item): item is Evidence => Boolean(item)), citationIds: ids, focusIndex, missingCount: ordered.filter(item => !item).length, loading: false, error: null });
    } catch (cause) {
      if (request === evidenceRequest.current) setEvidence({ items: [], citationIds: ids, focusIndex, missingCount: 0, loading: false, error: friendlyError(cause) });
    }
  }

  const isConversation = session?.state.mode === 'conversation' && Boolean(session.state.active_plant);
  const currentNotice = session?.state.session_notice || DEFAULT_NOTICE;
  const currentRunActive = run && ['accepted', 'running', 'interrupted'].includes(run.status);
  const dismissConfirmation = () => { if (session) window.sessionStorage.setItem(`impark.confirmed.${session.session_id}`, '1'); setShowConfirmation(false); };
  const statusState: ChatState | undefined = session?.state;

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <Sidebar sessions={sessions} selectedId={routeSession} loading={sessionsLoading} error={sessionsError} hasMore={nextOffset !== null} archivedView={archivedView} drawerOpen={drawerOpen} theme={theme} onClose={() => setDrawerOpen(false)} onSelect={id => router.push(`/chat/${id}`)} onNew={() => void startNew()} onMore={() => void loadMore()} onView={value => { setSessions([]); setNextOffset(null); setArchivedView(value); }} onRetry={() => void refreshSessions()} onUpdate={(id, patch) => void updateSession(id, patch)} onDelete={id => void deleteSession(id)} onTheme={() => setTheme(value => value === 'dark' ? 'light' : 'dark')} />
    <div className="workspace">
      <header className="topbar"><div className="topbar-left"><MobileMenuButton onClick={() => setDrawerOpen(true)} /><span className="topbar-divider mobile-only" /><span className="topbar-label">{isConversation ? 'EXPLORATION' : 'PLANT DISCOVERY'}</span>{isConversation && <span className="topbar-plant"><Leaf size={15} /> {session?.state.active_plant?.label}</span>}</div><div className="topbar-right"><button className="connection-button" onClick={() => setKeyOpen(true)} title="Connection settings"><KeyRound size={15} /><span>Connection</span></button><span className="topbar-edition">RESEARCH DEMO / 2026</span></div></header>
      {error && <div className="global-alert" role="alert"><AlertCircle size={18} /><span>{error}</span>{retryAction.current && <button onClick={() => void executeAction(retryAction.current!)}>Retry request</button>}{run && currentRunActive && <button onClick={() => void monitor(run, run.session_id)}>Reconnect</button>}<button className="icon-button" aria-label="Dismiss error" onClick={() => setError(null)}><X size={17} /></button></div>}
      {sessionLoading ? <main className="loading-view" id="main-content"><div className="subtle-spinner" /><p>Opening your exploration…</p></main> : isConversation && session ? <Conversation session={session} messages={messages} run={run} draftResponse={draftResponse} progress={progress} text={text} file={file} uploadStatus={uploadStatus} uploadError={uploadError} capabilities={capabilities} busy={busy || Boolean(currentRunActive) || session.archived} showConfirmation={showConfirmation} onDismissConfirmation={dismissConfirmation} onText={setText} onFile={setFile} onUploadError={setUploadError} onSend={() => void submit()} onCancel={() => void cancelRun()} onResume={() => void resumeRun()} onReconnect={() => run && void monitor(run, run.session_id)} onNew={() => void startNew()} onRestore={() => void updateSession(session.session_id, { archived: false })} onSources={(oid, ids, focusIndex) => void showSources(oid, ids, focusIndex)} onClarify={(reply, id) => void clarify(reply, id)} /> : <div className="discovery-container">
        <Discovery mode={mode} text={text} file={file} selected={selected} suggestions={suggestions} searchState={searchState} capabilities={capabilities} uploadStatus={uploadStatus} uploadError={uploadError} busy={busy || Boolean(currentRunActive) || Boolean(session?.archived)} notice={currentNotice} onMode={next => { setMode(next); if (next === 'photo') setSelected(null); }} onText={value => { setText(value); setSelected(null); }} onSelect={setSelected} onFile={setFile} onUploadError={setUploadError} onSubmit={() => void submitDiscovery()} />
        {session?.archived && <div className="archive-banner discovery-archive"><Archive size={19} /><div><strong>This exploration is archived.</strong><p>Restore it to continue discovery.</p></div><button className="secondary-button" onClick={() => void updateSession(session.session_id, { archived: false })}>Restore chat</button></div>}
        {currentRunActive && <div className="discovery-running" role="status"><span className="subtle-spinner" /><span>{progress || 'Reviewing your request…'}</span><button onClick={() => void cancelRun()}>Stop</button>{run?.status === 'interrupted' && <button onClick={() => void resumeRun()}>Resume</button>}</div>}
        {statusState?.clarification && !currentRunActive && <div className="discovery-clarification"><Clarification clarification={statusState.clarification} busy={busy || Boolean(session?.archived)} onChoose={candidate => void clarify(`Confirmed ${candidate.label}`, candidate.plant_id)} onReply={reply => void clarify(reply)} /><p className="field-note">You can also choose Photo above, upload a clearer image, and submit it as a clarification.</p></div>}
        {statusState && !statusState.clarification && statusState.status !== 'READY' && !currentRunActive && <div className="discovery-result"><span className="kicker">DISCOVERY RESULT</span>{statusState.response?.text ? <p>{statusState.response.text}</p> : <p>A reliable plant identity could not be established from this input. Try a clearer name, description or leaf photo.</p>}{statusState.understanding?.candidates?.length ? <div className="candidate-list">{statusState.understanding.candidates.map(candidate => <button className="candidate-row" key={candidate.plant_id} onClick={() => { setSelected(candidate); setText(candidate.label); }}><span className="candidate-initial">{candidate.label.charAt(0)}</span><strong>{candidate.label}</strong><ArrowRight size={16} /></button>)}</div> : null}</div>}
      </div>}
    </div>
    {evidence && <EvidencePanel items={evidence.items} citationIds={evidence.citationIds} focusIndex={evidence.focusIndex} missingCount={evidence.missingCount} loading={evidence.loading} error={evidence.error} onClose={() => { evidenceRequest.current++; setEvidence(null); }} />}
    {keyOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setKeyOpen(false); }}><section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-heading"><button className="icon-button settings-close" aria-label="Close connection settings" onClick={() => setKeyOpen(false)}><X size={20} /></button><KeyRound size={22} className="settings-icon" /><h2 id="settings-heading">Connection settings</h2><p>This frontend uses a same-origin Next.js proxy. If the backend requires a demo API key and the proxy is not configured with it, enter the key for this tab only. It is not saved or displayed again.</p><label htmlFor="api-key">Demo API key</label><input id="api-key" type="password" autoComplete="off" value={keyDraft} onChange={e => setKeyDraft(e.target.value)} placeholder="Optional for local development" /><button className="primary-button" onClick={() => { setApiToken(keyDraft); setKeyDraft(''); setKeyOpen(false); void refreshSessions(); api.capabilities().then(setCapabilities).catch(() => {}); if (routeSession) void refreshChat(routeSession); }}>Apply connection <ArrowRight size={17} /></button><p className="field-note"><WifiOff size={14} /> The backend must be running separately at the configured server URL.</p></section></div>}
  </div>;
}
