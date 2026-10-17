import { Archive, Leaf, Menu, Moon, MoreHorizontal, Plus, RotateCcw, Sun, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import type { Session } from '../types';
import { Brand } from './Icons';

type Props = {
  sessions: Session[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  archivedView: boolean;
  drawerOpen: boolean;
  theme: 'dark' | 'light';
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onMore: () => void;
  onView: (archived: boolean) => void;
  onRetry: () => void;
  onUpdate: (id: string, patch: { title?: string; archived?: boolean }) => void;
  onDelete: (id: string) => void;
  onTheme: () => void;
};

export function Sidebar(props: Props) {
  const [menuId, setMenuId] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [rename, setRename] = useState('');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  return <>
    {props.drawerOpen && <button className="drawer-scrim" aria-label="Close navigation" onClick={props.onClose} />}
    <aside className={`sidebar ${props.drawerOpen ? 'sidebar-open' : ''}`} aria-label="Explorations">
      <div className="sidebar-top">
        <Brand />
        <button className="icon-button mobile-only" aria-label="Close navigation" onClick={props.onClose}><X size={20} /></button>
      </div>
      <button className="new-button" onClick={() => { props.onNew(); props.onClose(); }}><Plus size={18} /> New exploration</button>
      <div className="sidebar-section-title sidebar-section-switch"><span>{props.archivedView ? 'ARCHIVED EXPLORATIONS' : 'RECENT EXPLORATIONS'}</span><button onClick={() => props.onView(!props.archivedView)}>{props.archivedView ? 'Recent' : 'Archived'}</button></div>
      <nav className="session-nav" aria-label={props.archivedView ? 'Archived chats' : 'Recent chats'}>
        {props.loading && <p className="sidebar-note">Loading explorations…</p>}
        {props.error && <div className="sidebar-note" role="alert">{props.error}<button className="text-button" onClick={props.onRetry}>Try again</button></div>}
        {!props.loading && !props.error && props.sessions.length === 0 && <div className="sidebar-empty"><Leaf size={20} /><p>{props.archivedView ? 'No archived explorations.' : 'Your explorations will appear here.'}</p></div>}
        {props.sessions.map(session => <div className={`session-row ${props.selectedId === session.session_id ? 'selected' : ''}`} key={session.session_id}>
          {renameId === session.session_id ? <form className="rename-form" onSubmit={e => { e.preventDefault(); if (rename.trim()) props.onUpdate(session.session_id, { title: rename.trim() }); setRenameId(null); }}>
            <input aria-label="Exploration title" maxLength={120} autoFocus value={rename} onChange={e => setRename(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') setRenameId(null); }} />
            <button type="submit" className="text-button">Save</button>
          </form> : <>
            <button className="session-link" aria-current={props.selectedId === session.session_id ? 'page' : undefined} title={session.title} onClick={() => { props.onSelect(session.session_id); props.onClose(); }}>
              <span className="session-title">{session.title}</span>
              <span className="session-subtitle">{session.state.active_plant?.label || (session.state.status === 'WAITING_USER' ? 'Needs confirmation' : 'Plant discovery')}</span>
            </button>
            <button className="session-more icon-button" aria-label={`Options for ${session.title}`} aria-expanded={menuId === session.session_id} onClick={() => { setMenuId(menuId === session.session_id ? null : session.session_id); setConfirmDelete(null); }}><MoreHorizontal size={17} /></button>
          </>}
          {menuId === session.session_id && <div className="session-menu">
            <button onClick={() => { setRenameId(session.session_id); setRename(session.title); setMenuId(null); }}>Rename</button>
            <button onClick={() => { props.onUpdate(session.session_id, { archived: !props.archivedView }); setMenuId(null); }}>{props.archivedView ? <RotateCcw size={15} /> : <Archive size={15} />}{props.archivedView ? 'Restore' : 'Archive'}</button>
            {confirmDelete === session.session_id ? <button className="danger" onClick={() => { props.onDelete(session.session_id); setMenuId(null); setConfirmDelete(null); }}>Confirm delete</button> : <button className="danger" onClick={() => setConfirmDelete(session.session_id)}><Trash2 size={15} /> Delete</button>}
          </div>}
        </div>)}
        {props.hasMore && <button className="load-more" onClick={props.onMore}>Load more</button>}
      </nav>
      <div className="sidebar-footer">
        <span>Academic research demo</span>
        <button className="icon-button" title={`Switch to ${props.theme === 'dark' ? 'light' : 'dark'} theme`} aria-label={`Switch to ${props.theme === 'dark' ? 'light' : 'dark'} theme`} onClick={props.onTheme}>{props.theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button>
      </div>
    </aside>
  </>;
}

export function MobileMenuButton({ onClick }: { onClick: () => void }) {
  return <button className="icon-button mobile-only" aria-label="Open navigation" onClick={onClick}><Menu size={21} /></button>;
}
