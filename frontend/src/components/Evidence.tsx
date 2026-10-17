import { ExternalLink, FileText, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { Evidence as EvidenceType } from '../types';

const visibleFields = new Set([
  'plant_name', 'common_names', 'plant_part', 'phytochemical_name', 'classyfire_class',
  'therapeutic_use', 'reported_use', 'mesh_category_name', 'standard_type',
  'standard_value', 'standard_units', 'standard_relation', 'target_name',
  'target_organism', 'document_journal', 'document_year', 'global_status',
  'regional_status', 'source',
]);

function claimFields(claim: string): [string, string][] | null {
  try {
    const parsed: unknown = JSON.parse(claim);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return Object.entries(parsed)
      .filter(([key, value]) => visibleFields.has(key) && (typeof value === 'string' || typeof value === 'number'))
      .map(([key, value]): [string, string] => [key, String(value).trim()])
      .filter(([, value]) => value.length > 0 && !['na', 'n/a', 'none', 'null'].includes(value.toLowerCase()));
  } catch { return null; }
}

function labelFor(field: string): string { return field.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase()); }
function evidenceLabel(item: EvidenceType): string {
  if (item.evidence_type === 'unknown') {
    return item.provenance.source_type === 'mesh' ? 'Reference definition' : 'Recorded source';
  }
  return `${item.evidence_type.replace('-', ' ')} evidence`;
}

function sourceTitle(item: EvidenceType): string {
  if (item.provenance.source_type === 'mesh') return 'Medical Subject Headings definition';
  const fields = Object.fromEntries(claimFields(item.claim) ?? []);
  if (item.graph_path?.includes('REPORTED_IN')) {
    const document = item.graph_nodes?.find(node => typeof node.document_chembl_id === 'string');
    const journal = fields.document_journal || (typeof document?.document_journal === 'string' ? document.document_journal : '');
    const year = fields.document_year || (typeof document?.document_year === 'string' ? document.document_year : '');
    if (journal) return `Linked document: ${journal}${year ? ` (${year})` : ''}`;
    return 'Linked research document';
  }
  return item.provenance.source_type === 'neo4j'
    ? 'Medicinal plant knowledge graph record'
    : item.provenance.reference || 'Research record';
}

function directLinkLabel(item: EvidenceType, url: string): string {
  if (item.provenance.source_type === 'mesh') return 'View this MeSH definition';
  if (url.includes('ebi.ac.uk/chembl/id_lookup/')) return 'View this ChEMBL document record';
  return 'View the linked document';
}

function Claim({ value }: { value: string }) {
  const fields = claimFields(value);
  return fields ? <dl className="evidence-fields">{fields.length ? fields.map(([field, text]) => <div key={field}><dt>{labelFor(field)}</dt><dd>{text}</dd></div>) : <div><dt>Record</dt><dd>Additional source details are available.</dd></div>}</dl> : <p>Additional source details are available.</p>;
}

export function EvidencePanel({ items, citationIds, focusIndex, missingCount, loading, error, onClose }: { items: EvidenceType[]; citationIds: string[]; focusIndex?: number; missingCount: number; loading: boolean; error: string | null; onClose: () => void }) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (loading || !focusIndex) return;
    const target = list.current?.querySelector(`[data-citation="${focusIndex}"]`);
    target?.scrollIntoView({ block: 'start' });
  }, [loading, focusIndex]);
  return <div className="evidence-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="evidence-panel" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
      <header><div><span className="kicker">RESEARCH RECORDS</span><h2 id="evidence-title">Sources & evidence</h2></div><button className="icon-button" autoFocus aria-label="Close sources" onClick={onClose}><X size={20} /></button></header>
      {loading && <p className="panel-state">Loading evidence…</p>}
      {error && <p className="panel-state error" role="alert">{error}</p>}
      {!loading && !error && missingCount > 0 && <p className="panel-state error" role="alert">{missingCount} cited {missingCount === 1 ? 'record is' : 'records are'} currently unavailable. The available records are shown below.</p>}
      {!loading && !error && items.length === 0 && <p className="panel-state">Source details are unavailable for this response.</p>}
      <div className="evidence-list" ref={list}>{items.map(item => <article className="evidence-record" data-citation={citationIds.indexOf(item.evidence_id) + 1} key={item.evidence_id}>
        <div className="evidence-record-head"><span className="source-index">[{citationIds.indexOf(item.evidence_id) + 1}]</span><span className="evidence-class">{evidenceLabel(item)}</span></div>
        <Claim value={item.claim} />
        <div className="source-detail"><FileText size={15} /><span>{sourceTitle(item)}</span></div>
        {item.source_urls?.filter(url => /^https?:\/\//i.test(url) && (item.provenance.source_type !== 'neo4j' || item.graph_path?.includes('REPORTED_IN'))).map(url => <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="source-link">{directLinkLabel(item, url)} <ExternalLink size={14} /></a>)}
        {(!item.source_urls?.length || (item.provenance.source_type === 'neo4j' && !item.graph_path?.includes('REPORTED_IN'))) && <p className="source-detail">No direct document link is recorded for this citation.</p>}
      </article>)}</div>
      <footer>Only links recorded for the cited source or its linked document are shown.</footer>
    </section>
  </div>;
}
