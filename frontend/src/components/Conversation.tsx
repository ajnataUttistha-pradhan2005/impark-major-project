import { Archive, ArrowUp, BookOpen, Check, Copy, ImagePlus, Leaf, PauseCircle, RotateCcw, Square, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Capabilities, Message, Run, Session } from '../types';
import { Clarification } from './Clarification';
import { Upload } from './Upload';

type Props = {
  session: Session;
  messages: Message[];
  run: Run | null;
  draftResponse: string;
  progress: string;
  text: string;
  file: File | null;
  uploadStatus: string;
  uploadError: string | null;
  capabilities: Capabilities | null;
  busy: boolean;
  showConfirmation: boolean;
  onDismissConfirmation: () => void;
  onText: (text: string) => void;
  onFile: (file: File | null) => void;
  onUploadError: (value: string | null) => void;
  onSend: () => void;
  onCancel: () => void;
  onResume: () => void;
  onReconnect: () => void;
  onNew: () => void;
  onRestore: () => void;
  onSources: (operationId: string, citationIds: string[], focusIndex?: number) => void;
  onClarify: (text: string, selectedId?: string) => void;
};

const topics = [
  { label: 'Overview', question: 'Give me an overview of this plant.' },
  { label: 'Plant parts', question: 'Which plant parts are documented?' },
  { label: 'Phytochemicals', question: 'Which phytochemicals are reported?' },
  { label: 'Traditional uses', question: 'What traditional uses are recorded, and what is the evidence class?' },
  { label: 'Scientific evidence', question: 'What scientific evidence is available for this plant?' },
];

function responseFor(message: Message) {
  const result = message.data?.result as { response?: { citation_ids?: string[] } } | undefined;
  return result?.response?.citation_ids || [];
}

type MarkdownNode = { type: string; value?: string; url?: string; children?: MarkdownNode[] };

function citationLinks() {
  return (tree: MarkdownNode) => {
    function visit(node: MarkdownNode) {
      if (!node.children || node.type === 'link' || node.type === 'linkReference') return;
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text' || !child.value) { visit(child); return [child]; }
        const pieces = child.value.split(/(\[\d+\])/g);
        return pieces.filter(Boolean).map(piece => {
          const match = /^\[(\d+)\]$/.exec(piece);
          return match ? { type: 'link', url: `#citation-${match[1]}`, children: [{ type: 'text', value: piece }] } : { type: 'text', value: piece };
        });
      });
    }
    visit(tree);
  };
}

function Answer({ text, citationCount = 0, onCitation }: { text: string; citationCount?: number; onCitation?: (index: number) => void }) {
  return <div className="answer-markdown"><ReactMarkdown remarkPlugins={[remarkGfm, citationLinks]} components={{
    a: ({ href, children }) => {
      const citation = /^#citation-(\d+)$/.exec(href || '');
      if (citation) {
        const index = Number(citation[1]);
        return index >= 1 && index <= citationCount && onCitation
          ? <button className="citation-link" type="button" aria-label={`Open source ${index}`} onClick={() => onCitation(index)}>{children}</button>
          : <span>{children}</span>;
      }
      return href && /^https?:\/\//i.test(href) ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
    },
    table: ({ children }) => <div className="table-scroll"><table>{children}</table></div>,
  }}>{text}</ReactMarkdown></div>;
}

export function Conversation(props: Props) {
  const bottom = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [attachOpen, setAttachOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [props.messages.length, props.draftResponse, props.progress]);
  useEffect(() => { if (textarea.current) { textarea.current.style.height = 'auto'; textarea.current.style.height = `${Math.min(textarea.current.scrollHeight, 160)}px`; } }, [props.text]);
  async function copy(value: string, id: string) { await navigator.clipboard.writeText(value); setCopied(id); window.setTimeout(() => setCopied(null), 1800); }
  const activeId = props.run?.operation_id;
  const hasPendingRow = props.messages.some(message => message.role === 'assistant' && message.operation_id === activeId);
  const waiting = props.session.state.status === 'WAITING_USER' && props.session.state.clarification;
  const repeatedIdentityPrompt = Boolean(
    waiting && props.session.state.active_plant
    && /select a candidate|scientific\/common name|which plant do you mean/i.test(waiting.question)
  );
  const lastQuestion = [...props.messages].reverse().find(message =>
    message.role === 'user' && message.content !== '[image/selection]'
  )?.content;
  const activeRun = props.run && ['accepted', 'running'].includes(props.run.status);
  const interrupted = props.run?.status === 'interrupted';

  return <div className="conversation-view" id="main-content">
    <div className="transcript-scroll"><div className="transcript">
      {props.session.archived && <div className="archive-banner"><Archive size={19} /><div><strong>This exploration is archived.</strong><p>Restore it to ask another question in the same plant chat.</p></div><button className="secondary-button" onClick={props.onRestore}>Restore chat</button></div>}
      {props.showConfirmation && <div className="confirmation-banner"><div className="confirmation-icon"><Leaf size={24} /></div><div><span className="kicker">PLANT IDENTIFIED</span><h2>{props.session.state.active_plant?.label}</h2><p>This chat now focuses on one plant. Explore its documented details and evidence.</p><div className="topic-list">{topics.map(topic => <button key={topic.label} type="button" onClick={() => { props.onText(topic.question); props.onDismissConfirmation(); textarea.current?.focus(); }}>{topic.label}</button>)}</div><button className="confirmation-continue" type="button" onClick={() => { props.onDismissConfirmation(); textarea.current?.focus(); }}>Continue to chat</button></div><button className="icon-button" aria-label="Dismiss plant confirmation" onClick={props.onDismissConfirmation}><X size={18} /></button></div>}
      {!props.messages.length && <div className="conversation-empty"><Leaf size={30} strokeWidth={1.4} /><h2>Explore {props.session.state.active_plant?.label}</h2><p>Ask about documented plant parts, compounds, reported uses or the evidence behind them.</p><div className="topic-list">{topics.map(topic => <button key={topic.label} onClick={() => { props.onText(topic.question); textarea.current?.focus(); }}>{topic.label}</button>)}</div></div>}
      {props.messages.map(message => {
        const provisional = message.role === 'assistant' && message.operation_id === activeId && activeRun;
        const text = provisional ? props.draftResponse : message.content;
        if (message.role === 'assistant' && !text && !provisional && message.status === 'pending') return null;
        return <article className={`message message-${message.role}`} key={message.message_id}>
          {message.role === 'assistant' && <div className="message-avatar"><Leaf size={17} /></div>}
          <div className="message-body">
            {message.role === 'user' ? <div className="user-content">{message.content === '[image/selection]' ? 'Plant submitted for identification' : message.content}</div> : <>
              {text ? <Answer text={text} citationCount={responseFor(message).length} onCitation={index => props.onSources(message.operation_id, responseFor(message), index)} /> : <p className="waiting-copy">{props.progress || 'Working on your request…'}</p>}
              {provisional && <span className="stream-cursor" aria-hidden="true" />}
              {!provisional && message.status !== 'complete' && <div className="message-status">{message.status === 'interrupted' ? 'Response interrupted' : message.status === 'cancelled' ? 'Cancelled' : message.status === 'failed' ? 'Response unavailable' : message.status}</div>}
              {message.status === 'complete' && text && <div className="message-tools">
                {responseFor(message).length > 0 && <button onClick={() => props.onSources(message.operation_id, responseFor(message))}><BookOpen size={15} /> Sources · {responseFor(message).length}</button>}
                <button aria-label="Copy answer" title="Copy answer" onClick={() => copy(text, message.message_id)}>{copied === message.message_id ? <Check size={15} /> : <Copy size={15} />} {copied === message.message_id ? 'Copied' : 'Copy'}</button>
              </div>}
            </>}
          </div>
        </article>;
      })}
      {activeRun && !hasPendingRow && <div className="pending-response"><span className="subtle-spinner" />{props.progress || 'Working on your request…'}</div>}
      {interrupted && <div className="run-recovery"><PauseCircle size={19} /><div><strong>This response was interrupted.</strong><p>Continue the same run or cancel it before asking another question.</p></div><button className="secondary-button" onClick={props.onResume}><RotateCcw size={16} /> Resume</button><button className="text-button" onClick={props.onCancel}>Cancel</button></div>}
      {props.run && activeRun && <div className="run-controls"><span className="subtle-spinner" />{props.progress || 'Reviewing the available evidence…'}<button onClick={props.onCancel}><Square size={13} /> Stop</button><button onClick={props.onReconnect} title="Reconnect to response stream"><RotateCcw size={14} /> Reconnect</button></div>}
      {waiting && repeatedIdentityPrompt && lastQuestion ? <section className="clarification-panel" aria-labelledby="active-plant-recovery-heading">
        <div className="clarification-top"><span className="clarification-symbol"><Leaf size={20} /></span><span className="kicker">CONTINUE THIS CHAT</span></div>
        <h2 id="active-plant-recovery-heading">Use {props.session.state.active_plant?.label} for this question?</h2>
        <p>This chat already has an active plant. Continue your question about it without choosing another candidate.</p>
        <button className="primary-button" type="button" disabled={props.busy} onClick={() => props.onClarify(lastQuestion)}>Continue with {props.session.state.active_plant?.label}</button>
      </section> : waiting && <Clarification key={waiting.clarification_id} clarification={repeatedIdentityPrompt ? { ...waiting, candidates: [], question: `Rephrase your question about ${props.session.state.active_plant?.label}.` } : waiting} identity={false} busy={props.busy} onChoose={candidate => props.onClarify(`Confirmed ${candidate.label}`, candidate.plant_id)} onReply={text => props.onClarify(text)} />}
      {props.session.state.status === 'SCOPE_REJECTED' && <div className="scope-note"><p>This chat is focused on {props.session.state.active_plant?.label}. To explore another plant, start a new chat.</p><button className="secondary-button" onClick={props.onNew}>New exploration <ArrowUp size={15} /></button></div>}
      <div ref={bottom} />
    </div></div>
    <div className="conversation-compose-wrap"><div className="conversation-compose">
      {!waiting && <>
        {attachOpen && <div className="composer-upload"><Upload file={props.file} status={props.uploadStatus} maxBytes={props.capabilities?.max_image_bytes || 5_242_880} error={props.uploadError} disabled={props.busy} onFile={props.onFile} onError={props.onUploadError} /></div>}
        <div className="composer-box"><textarea ref={textarea} rows={1} maxLength={8000} aria-label={`Ask about ${props.session.state.active_plant?.label || 'this plant'}`} placeholder={`Ask about ${props.session.state.active_plant?.label || 'this plant'}…`} value={props.text} disabled={props.busy} onChange={e => props.onText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (props.text.trim() || props.file) props.onSend(); } }} /><div className="composer-actions"><button className={`icon-button ${attachOpen ? 'active' : ''}`} type="button" title="Attach plant photo" aria-label="Attach plant photo" aria-expanded={attachOpen} disabled={props.busy} onClick={() => setAttachOpen(!attachOpen)}><ImagePlus size={19} /></button><span>Enter to send · Shift+Enter for a new line</span><button className="send-button" type="button" aria-label="Send question" onClick={props.onSend} disabled={props.busy || (!props.text.trim() && !props.file)}><ArrowUp size={19} /></button></div></div>
      </>}
      <p className="composer-disclaimer">Educational use only · Responses reflect available records and their evidence class.</p>
    </div></div>
  </div>;
}
