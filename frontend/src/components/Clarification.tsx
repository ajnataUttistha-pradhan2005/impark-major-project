import { ArrowRight, HelpCircle } from 'lucide-react';
import { useState } from 'react';
import type { Candidate, Clarification as ClarificationType } from '../types';

type Props = { clarification: ClarificationType; busy: boolean; identity?: boolean; onChoose: (candidate: Candidate) => void; onReply: (text: string) => void };

export function Clarification({ clarification, busy, identity = true, onChoose, onReply }: Props) {
  const [reply, setReply] = useState('');
  const candidates = identity ? clarification.candidates : [];
  return <section className="clarification-panel" aria-labelledby="clarification-heading">
    <div className="clarification-top"><span className="clarification-symbol"><HelpCircle size={20} /></span><span className="kicker">{identity ? candidates.length ? 'CHOOSE A PLANT' : 'IDENTIFY THE PLANT' : 'CLARIFY YOUR QUESTION'}</span></div>
    <h2 id="clarification-heading">{clarification.question}</h2>
    {candidates.length > 0 && <div className="candidate-list" aria-label="Possible plants">{candidates.map(candidate => <button className="candidate-row" key={candidate.plant_id} disabled={busy} onClick={() => onChoose(candidate)}>
      <span className="candidate-initial">{candidate.label.charAt(0).toUpperCase()}</span>
      <span className="candidate-info"><strong>{candidate.label}</strong>{candidate.matched_name && candidate.matched_name !== candidate.label && <small>Matched as {candidate.matched_name}{candidate.language ? ` · ${candidate.language}` : ''}</small>}</span>
      <span className="candidate-action">Select <ArrowRight size={15} /></span>
    </button>)}</div>}
    <div className="clarification-answer"><label htmlFor="clarification-text">{identity ? candidates.length ? 'Or clarify in your own words' : 'Tell us another name or a distinguishing detail' : 'What would you like to know about this plant?'}</label><div className="clarification-input"><input id="clarification-text" value={reply} disabled={busy} onChange={e => setReply(e.target.value)} maxLength={8000} placeholder={identity ? 'Add a name or detail…' : 'Ask about a part, compound, use, or source…'} onKeyDown={e => { if (e.key === 'Enter' && !busy && reply.trim()) onReply(reply.trim()); }} /><button type="button" className="icon-button" title="Submit clarification" aria-label="Submit clarification" disabled={!reply.trim() || busy} onClick={() => onReply(reply.trim())}><ArrowRight size={18} /></button></div></div>
    <p className="field-note">Your answer will continue in this chat.</p>
  </section>;
}
