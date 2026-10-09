"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ImagePlus, Upload, X } from "lucide-react";

export default function ArtistArtworkUpload() {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);

  useEffect(() => {
    if (!file || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function removeFile() {
    if (input.current) input.current.value = "";
    setFile(null);
    setPreviewFailed(false);
  }

  return <div className="artistArtworkUpload">
    <div className="artistRegisterStep"><span aria-hidden="true">01</span><label htmlFor={inputId}>Reference image</label></div>
    <div className={`artistUploadCanvas${file ? " hasFile" : ""}`}>
      <input id={inputId} ref={input} type="file" name="file" required accept="image/png,image/jpeg,image/webp" aria-describedby={`${inputId}-hint`} onChange={event => {
        setFile(event.target.files?.[0] || null);
        setPreviewFailed(false);
      }} />
      {preview && !previewFailed
        ? <img src={preview} alt="Selected artwork preview" className="artistUploadPreview" onError={() => setPreviewFailed(true)} />
        : <div className="artistUploadEmpty" aria-hidden="true"><span className="artistUploadIcon"><ImagePlus size={29} strokeWidth={1.35} /></span><strong>{file ? "Preview unavailable" : "Give your artwork a home."}</strong><p>{file ? "You can replace this file before registering." : "Drop your original image here"}</p><span className="artistUploadBrowse"><Upload size={14} />{file ? "Choose another image" : "Browse files"}</span></div>}
      {preview && !previewFailed && <span className="artistUploadReplace" aria-hidden="true"><Upload size={14} />Click or drop to replace</span>}
      <span className="artistUploadCorners" aria-hidden="true" />
    </div>
    <div className="artistUploadMeta" aria-live="polite">
      {file ? <><span className="artistUploadFile"><Check size={15} /><span><strong>{file.name}</strong><small>{file.size < 1024 * 1024 ? `${Math.ceil(file.size / 1024)} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`} · Selected reference</small></span></span><button type="button" onClick={removeFile} className="artistRemoveFile" aria-label="Remove selected reference image"><X size={16} /></button></> : <span id={`${inputId}-hint`}>PNG, JPG or WEBP · Up to 4 MB / 6 MP</span>}
      {file && <span id={`${inputId}-hint`} className="artistUploadLimit">PNG, JPG or WEBP · Up to 4 MB / 6 MP</span>}
    </div>
  </div>;
}
