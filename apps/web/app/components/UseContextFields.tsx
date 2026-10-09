"use client";
import { PERMISSIONS } from "@/app/lib/phase1";

export default function UseContextFields({ disabled = false }: { disabled?: boolean }) {
  return <details className="cpDetails cpFull"><summary>More details about your intended use <small>(optional)</small></summary><div className="cpDetailBody"><p className="cpDescription">Add only what you know. These details help compare your intended use with license and artist restrictions. Publication country is separate from your notice-country declaration.</p><fieldset className="cpUseContextFields" disabled={disabled}><div className="cpFormGrid">
    <label className="portalField"><span className="portalFieldLabel">Publication country</span><input aria-label="Publication country" name="use_territory" maxLength={2} pattern="[A-Za-z]{2}" placeholder="BD, US, DE…" /><small className="portalFieldHint">Two-letter code for where this use takes place.</small></label>
    <label className="portalField"><span className="portalFieldLabel">Publication channel</span><input name="use_channel" maxLength={160} placeholder="web, social, print…" /></label>
    <label className="portalField"><span className="portalFieldLabel">Audience</span><input name="use_audience" maxLength={160} placeholder="public, internal…" /></label>
    <label className="portalField"><span className="portalFieldLabel">Transformation</span><input name="use_transformation" maxLength={160} placeholder="crop, resize, AI edit…" /></label>
    <label className="portalField"><span className="portalFieldLabel">Platform</span><input name="use_platform" maxLength={160} placeholder="Platform named in the policy" /></label>
    <label className="portalField"><span className="portalFieldLabel">AI model, if applicable</span><input name="use_model" maxLength={160} placeholder="Exact model identifier" /></label>
    <label className="portalField cpFull"><span className="portalFieldLabel">Artist permission to check</span><select aria-label="Artist permission to check" name="use_rights_permission" defaultValue=""><option value="">No specific AI permission requested</option>{PERMISSIONS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}</select></label>
  </div></fieldset></div></details>;
}
