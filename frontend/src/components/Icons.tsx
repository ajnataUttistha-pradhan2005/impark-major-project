import { Leaf } from 'lucide-react';

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="brand" aria-label="IMPARK">
    <span className="brand-mark"><Leaf size={19} strokeWidth={1.8} aria-hidden="true" /></span>
    {!compact && <span className="brand-text">impark<span className="brand-period">.</span><small>plant knowledge workspace</small></span>}
  </div>;
}
