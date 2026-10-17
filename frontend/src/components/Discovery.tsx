import { ArrowRight, Camera, Check, ChevronDown, Search, X } from 'lucide-react';
import { useState } from 'react';
import type { Candidate, Capabilities } from '../types';
import { Upload } from './Upload';

export type DiscoveryMode = 'name' | 'describe' | 'photo' | 'combined';

type Props = {
  mode: DiscoveryMode;
  text: string;
  file: File | null;
  selected: Candidate | null;
  suggestions: Candidate[];
  searchState: 'idle' | 'loading' | 'ready' | 'error' | 'unavailable';
  capabilities: Capabilities | null;
  uploadStatus: string;
  uploadError: string | null;
  busy: boolean;
  notice: string;
  onMode: (mode: DiscoveryMode) => void;
  onText: (value: string) => void;
  onSelect: (candidate: Candidate | null) => void;
  onFile: (file: File | null) => void;
  onUploadError: (error: string | null) => void;
  onSubmit: () => void;
};

const modes: { id: DiscoveryMode; label: string }[] = [
  { id: 'name', label: 'Plant name' }, { id: 'describe', label: 'Describe' },
  { id: 'photo', label: 'Photo' }, { id: 'combined', label: 'Text + photo' },
];

export function Discovery(props: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const usesPhoto = props.mode === 'photo' || props.mode === 'combined';
  const usesText = props.mode !== 'photo';
  const canSubmit = !props.busy && ((usesText && props.text.trim().length > 0) || (props.mode !== 'photo' && props.selected) || (usesPhoto && props.file));
  const searchVisible = props.mode === 'name' && open && props.text.trim().length > 0 && !props.selected;

  function choose(candidate: Candidate) { props.onSelect(candidate); setOpen(false); setActive(-1); }

  return <main className="discovery-view" id="main-content">
    <div className="discovery-inner">
      <div className="eyebrow"><span className="eyebrow-line" /> PLANT DISCOVERY</div>
      <h1>What plant would you<br className="desktop-break" /> like to explore<span className="accent-mark">?</span></h1>
      <p className="discovery-lead">Search by name, describe what you know, or identify a plant from a photo.</p>

      <section className="discovery-workspace" aria-label="Plant discovery">
        <div className="mode-tabs" role="tablist" aria-label="Discovery method" onKeyDown={event => {
          const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
          const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
          if (index < 0) return;
          const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
          if (next < 0) return;
          event.preventDefault(); tabs[next].focus(); props.onMode(modes[next].id); setOpen(false);
        }}>
          {modes.map(mode => <button key={mode.id} id={`discovery-tab-${mode.id}`} type="button" role="tab" aria-controls="discovery-panel" aria-selected={props.mode === mode.id} tabIndex={props.mode === mode.id ? 0 : -1} className={props.mode === mode.id ? 'active' : ''} onClick={() => { props.onMode(mode.id); setOpen(false); }}>{mode.label}</button>)}
        </div>
        <div className="discovery-form" id="discovery-panel" role="tabpanel" aria-labelledby={`discovery-tab-${props.mode}`}>
          {usesText && <div className="field-block">
            <label htmlFor="discovery-input">{props.mode === 'name' ? 'Search for a plant' : 'Describe the plant or what you know about it'}</label>
            <div className="input-wrap">
              {props.mode === 'name' && <Search className="input-icon" size={20} aria-hidden="true" />}
              {props.mode === 'name' ? <input id="discovery-input" type="search" autoComplete="off" role="combobox" aria-autocomplete="list" aria-expanded={searchVisible} aria-controls="plant-suggestions" aria-activedescendant={active >= 0 ? `suggestion-${active}` : undefined} placeholder="Search common or scientific name…" value={props.text} onChange={e => { props.onText(e.target.value); setOpen(true); setActive(-1); }} onFocus={() => setOpen(true)} onKeyDown={e => {
                if (e.key === 'ArrowDown' && props.suggestions.length) { e.preventDefault(); setOpen(true); setActive(i => (i + 1) % props.suggestions.length); }
                else if (e.key === 'ArrowUp' && props.suggestions.length) { e.preventDefault(); setOpen(true); setActive(i => i <= 0 ? props.suggestions.length - 1 : i - 1); }
                else if (e.key === 'Enter' && open && active >= 0) { e.preventDefault(); choose(props.suggestions[active]); }
                else if (e.key === 'Enter' && canSubmit) { e.preventDefault(); props.onSubmit(); }
                else if (e.key === 'Escape') { setOpen(false); setActive(-1); }
              }} /> : <textarea id="discovery-input" rows={4} maxLength={8000} placeholder="I’m looking for a medicinal plant with…" value={props.text} onChange={e => props.onText(e.target.value)} />}
              {props.mode === 'name' && props.text && <button type="button" className="input-clear" aria-label="Clear search" onClick={() => { props.onText(''); props.onSelect(null); setOpen(false); }}><X size={17} /></button>}
              {searchVisible && <div className="suggestions" id="plant-suggestions" role="listbox" aria-label="Plant suggestions">
                {props.searchState === 'loading' && <div className="suggestion-state">Searching plant names…</div>}
                {props.searchState === 'error' && <div className="suggestion-state">Search is unavailable. You can still submit the name.</div>}
                {props.searchState === 'unavailable' && <div className="suggestion-state">Suggestions are unavailable. You can still submit the name.</div>}
                {props.searchState === 'ready' && props.suggestions.length === 0 && <div className="suggestion-state">No clear matches. Try another name or describe the plant.</div>}
                {props.searchState === 'ready' && props.suggestions.map((item, index) => <button type="button" role="option" aria-selected={active === index} id={`suggestion-${index}`} className={`suggestion ${active === index ? 'highlighted' : ''}`} key={item.plant_id} onMouseDown={e => e.preventDefault()} onClick={() => choose(item)}>
                  <span className="suggestion-leaf">✳</span><span className="suggestion-copy"><strong>{item.label}</strong>{item.matched_name && item.matched_name !== item.label && <small>Matched: {item.matched_name}{item.language ? ` · ${item.language}` : ''}</small>}</span><ArrowRight size={16} />
                </button>)}
              </div>}
            </div>
            {props.selected && <div className="selected-candidate"><Check size={15} /> Candidate input: <strong>{props.selected.label}</strong><button type="button" aria-label="Clear selected candidate" onClick={() => props.onSelect(null)}><X size={14} /></button></div>}
          </div>}
          {usesPhoto && <div className="field-block"><label>Plant photo</label><Upload file={props.file} status={props.uploadStatus} maxBytes={props.capabilities?.max_image_bytes || 5_242_880} error={props.uploadError} disabled={props.busy} onFile={props.onFile} onError={props.onUploadError} />{props.capabilities && !props.capabilities.image_classifier && <p className="field-note">Image classification is currently unavailable. Add a name or description for discovery.</p>}{props.capabilities?.image_classifier && <p className="field-note">Leaf image suggestions require confirmation. Other plant parts may not be recognized.</p>}</div>}
          <div className="discovery-actions"><span className="subtle-hint">Identity may need your confirmation.</span><button className="primary-button" type="button" onClick={props.onSubmit} disabled={!canSubmit}>{props.busy ? 'Working…' : 'Find plant'} <ArrowRight size={17} /></button></div>
        </div>
      </section>
      <div className="discovery-examples"><span>Try a name</span>{['Ashwagandha', 'Tulsi', 'Neem'].map(name => <button key={name} type="button" onClick={() => { props.onMode('name'); props.onText(name); props.onSelect(null); }}>{name} <ArrowRight size={13} /></button>)}</div>
      <p className="discovery-notice">{props.notice}</p>
      <div className="discovery-art" aria-hidden="true"><Camera size={18} /><span>01 / DISCOVER</span><ChevronDown size={16} /></div>
    </div>
  </main>;
}
