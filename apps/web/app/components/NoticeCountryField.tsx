"use client";

import { NOTICE_COUNTRIES as countries } from "../lib/noticeCountries";

export default function NoticeCountryField({ value, onChange, disabled = false }: {
  value?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
}) {
  return <label className="portalField">
    <span className="portalFieldLabel">Notice country <small>(optional)</small></span>
    <select aria-label="Your country" name="country_code" disabled={disabled}
      {...(value === undefined ? { defaultValue: "" } : { value })}
      onChange={onChange ? (event) => onChange(event.target.value) : undefined}>
      <option value="">Unknown / let Admin confirm</option>
      {countries.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
    </select>
    <small className="portalFieldHint">Your declaration helps prepare a draft. Admin confirms the jurisdiction; this does not locate the uploader or seller.</small>
  </label>;
}
