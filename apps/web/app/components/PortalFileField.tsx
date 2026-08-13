"use client";

import { ChangeEvent, useState } from "react";

type PortalFileFieldProps = {
  name: string;
  accept?: string;
  required?: boolean;
  label: string;
  hint?: string;
};

export default function PortalFileField({
  name,
  accept = "image/*",
  required,
  label,
  hint = "PNG, JPG, or WEBP",
}: PortalFileFieldProps) {
  const [fileName, setFileName] = useState<string | null>(null);

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0]?.name ?? null;
    setFileName(next);
  }

  return (
    <label className="portalField portalFileField">
      <span className="portalFieldLabel">{label}</span>
      <span className={`portalFileShell${fileName ? " hasFile" : ""}`}>
        <input
          required={required}
          type="file"
          name={name}
          accept={accept}
          onChange={onChange}
        />
        <span className="portalFileCopy" aria-hidden="true">
          <strong>{fileName ?? "Drop an image or browse"}</strong>
          <small>{fileName ? "Click to replace" : hint}</small>
        </span>
      </span>
    </label>
  );
}
