import { ImagePlus, RefreshCw, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

type Props = { file: File | null; status: string; maxBytes: number; error: string | null; disabled?: boolean; onFile: (file: File | null) => void; onError: (error: string | null) => void };

export function Upload({ file, status, maxBytes, error, disabled, onFile, onError }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function accept(candidate?: File) {
    if (!candidate) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(candidate.type)) { onError('Choose a PNG, JPEG or WebP image.'); return; }
    if (candidate.size > maxBytes) { onError(`Choose an image smaller than ${(maxBytes / 1048576).toFixed(1)} MiB.`); return; }
    onError(null); onFile(candidate);
  }

  return <div className="upload-wrap">
    {file ? <div className="file-preview">
      {preview && <img src={preview} alt="Selected plant specimen preview, not yet identified" />}
      <div className="file-details"><strong title={file.name}>{file.name}</strong><small>{(file.size / 1048576).toFixed(2)} MiB · {status || 'Ready to upload'}</small></div>
      <button type="button" className="icon-button" disabled={disabled} aria-label="Replace image" title="Replace image" onClick={() => input.current?.click()}><RefreshCw size={18} /></button>
      <button type="button" className="icon-button" disabled={disabled} aria-label="Remove image" title="Remove image" onClick={() => onFile(null)}><X size={18} /></button>
    </div> : <div className={`drop-zone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); accept(e.dataTransfer.files[0]); }}>
      <ImagePlus size={24} strokeWidth={1.5} />
      <p><button type="button" className="text-button" disabled={disabled} onClick={() => input.current?.click()}>Choose a photo</button> or drop it here</p>
      <small>PNG, JPEG or WebP · up to {(maxBytes / 1048576).toFixed(1)} MiB</small>
    </div>}
    <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Select a plant image" onChange={e => { accept(e.target.files?.[0]); e.target.value = ''; }} />
    {error && <p className="field-error" role="alert">{error}</p>}
  </div>;
}
