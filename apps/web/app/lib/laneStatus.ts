/**
 * One derivation of the four lane answers, shared by every surface that states them.
 *
 * The summary and the evidence workspace used to answer the same four questions
 * from separate logic, and could disagree on screen: the workspace treated a
 * missing overlay image as an absence of copy evidence, so a verified match
 * rendered as "no verified same-work copy was found" directly beneath a summary
 * reporting that match. Rendering concerns must never decide what the evidence
 * says, so nothing here may read `visualization`.
 */

export type LaneKey = "copy" | "origin" | "profile" | "rights";

/**
 * `hit` and `review` both mean evidence was found; they differ in whether the
 * evidence cleared the verification bar or only the review bar. `advisory`
 * carries context that must not be read as a finding. `unchecked` means the
 * lane could not run, which is never the same as a clean result.
 */
export type LaneState = "hit" | "review" | "advisory" | "clear" | "unchecked";

export type LaneStatus = {
  key: LaneKey;
  question: string;
  /** Short form, for dense lane cards. */
  headline: string;
  /** Fuller sentence, for the post-scan summary. */
  answer: string;
  note: string;
  state: LaneState;
};

export type LaneStatuses = Record<LaneKey, LaneStatus>;

type Record_ = Record<string, unknown>;

function asRecord(value: unknown): Record_ | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record_) : null;
}

function asArray(value: unknown): Record_[] {
  return Array.isArray(value) ? (value.filter((item) => asRecord(item)) as Record_[]) : [];
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function upper(value: unknown, fallback: string): string {
  return (str(value) ?? fallback).toUpperCase();
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Prefer a human title; fall back to a short identifier rather than a raw one. */
function workLabel(match: Record_ | null): string {
  if (!match) return "a stored work";
  const title = str(match.title);
  if (title) return title;
  const workId = str(match.work_id);
  return workId ? `work ${workId.replace(/^wrk_/, "").slice(0, 8)}` : "a stored work";
}

function claimantSuffix(match: Record_ | null): string {
  const claimant = match ? str(match.claimant) : null;
  return claimant ? ` — ${claimant}` : "";
}

function copyLane(packet: Record_ | null, scan: Record_): LaneStatus {
  const question = "Does this reuse a work in the catalog?";
  const scope = asRecord(packet?.scope);
  const decision = asRecord(packet?.decision);
  const joint = asRecord(decision?.joint_risk);
  const top = asArray(packet?.matches)[0] ?? null;
  const fusion = asRecord(top?.fusion);
  const coverage = upper(scope?.coverage_status, "UNKNOWN");
  // MatchStatus is a closed enum on the API side: MATCH_FOUND, INCONCLUSIVE,
  // NO_MATCH_IN_CHECKED_SOURCES, SCOPE_INCOMPLETE, ERROR. Compare against those
  // exact values only — a near-miss such as "NO_MATCH" is never emitted, so it
  // would read as a match on every scan.
  const matchStatus = upper(scan.match_status ?? decision?.match_status, "");
  const label = workLabel(top);
  const attributed = `${label}${claimantSuffix(top)}`;

  if (coverage === "EMPTY_SCOPE") {
    return {
      key: "copy",
      question,
      headline: "No eligible reference in this catalog",
      answer: "This catalog holds no eligible reference to compare against",
      note: "Register protected works in this catalog to activate visual matching.",
      state: "unchecked",
    };
  }

  if (matchStatus === "SCOPE_INCOMPLETE") {
    return {
      key: "copy",
      question,
      headline: "Stored-work scope is incomplete",
      answer: "The catalog was not searched in full, so a clean result cannot be claimed",
      note: "Open the source record to inspect which references were omitted.",
      state: "unchecked",
    };
  }

  if (matchStatus === "ERROR") {
    return {
      key: "copy",
      question,
      headline: "Stored-work matching did not complete",
      answer: "The comparison failed, so this lane has no result",
      note: "Re-run the scan once the failure in the source record is resolved.",
      state: "unchecked",
    };
  }

  if (top?.exact_sha256 === true) {
    return {
      key: "copy",
      question,
      headline: `Exact reuse of ${label}`,
      answer: `Yes — this is a byte-identical copy of ${attributed}`,
      note: "The candidate and the stored file share an identical content hash.",
      state: "hit",
    };
  }

  if (fusion?.match_supported === true || fusion?.verified === true) {
    return {
      key: "copy",
      question,
      headline: `Verified reuse of ${label}`,
      answer: `Yes — verified visual reuse of ${attributed}`,
      note: "Matched-region geometry corroborates reuse of a stored work.",
      state: "hit",
    };
  }

  if (joint?.copy_supported === true || matchStatus === "MATCH_FOUND") {
    return {
      key: "copy",
      question,
      headline: `A stored work matched: ${label}`,
      answer: `Yes — the strongest match is ${attributed}`,
      note: "Verified visual reuse signal in the selected catalog.",
      state: "hit",
    };
  }

  if (fusion?.review_supported === true || matchStatus === "INCONCLUSIVE") {
    return {
      key: "copy",
      question,
      headline: `Possible reuse of ${label}`,
      answer: `Possibly — reuse of ${attributed} reached the review threshold`,
      note: "Visual evidence supports review but did not clear the verification bar.",
      state: "review",
    };
  }

  if (coverage !== "COMPLETE" && coverage !== "UNKNOWN") {
    return {
      key: "copy",
      question,
      headline: "Stored-work scope is incomplete",
      answer: "The catalog was not searched in full, so a clean result cannot be claimed",
      note: "Open the source record to inspect which references were omitted.",
      state: "unchecked",
    };
  }

  return {
    key: "copy",
    question,
    headline: "No verified same-work copy was found",
    answer: "No stored work matched above threshold",
    note: "No visual reuse signal reached the configured review threshold.",
    state: "clear",
  };
}

function originLane(packet: Record_ | null): LaneStatus {
  const question = "Was AI likely involved?";
  const synthetic = asRecord(packet?.synthetic_origin);
  const joint = asRecord(asRecord(packet?.decision)?.joint_risk);
  const classification = upper(synthetic?.classification, "");
  const note = "AI intelligence combines the active origin-analysis signals for this image.";
  const presentation = asRecord(synthetic?.presentation);
  const engineHeadline = str(presentation?.headline);
  const withEngineHeadline = (status: LaneStatus): LaneStatus =>
    engineHeadline ? { ...status, headline: engineHeadline } : status;

  // The engine already grades this lane, so read its verdict rather than
  // re-deriving one. `review_recommended` alone cannot be trusted for wording:
  // it is also set when every check was inconclusive, and phrasing that as
  // signals reaching a threshold would claim evidence the scan never had.
  const engineState = upper(presentation?.state, "");

  if (engineState === "ORIGIN_UNKNOWN") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "This scan cannot determine the image’s origin",
      answer: "Undetermined — the available checks could not establish an origin",
      note,
      state: "unchecked",
    });
  }

  if (engineState === "CHECK_UNAVAILABLE") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "AI-origin checks are not active",
      answer: "AI-origin analysis did not run for this scan",
      note,
      state: "unchecked",
    });
  }

  if (engineState === "AI_CONFIRMED") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "Signed provenance identifies AI use",
      answer: "Yes — trusted Content Credentials assert AI generation",
      note,
      state: "hit",
    });
  }

  if (engineState === "AI_INDICATORS_FOUND") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "AI indicators were corroborated",
      answer: "Yes — more than one check agreed on AI-generation indicators",
      note,
      state: "hit",
    });
  }

  // A single indicator — most often a visible label, which can be genuine,
  // copied or forged. The engine grades this tier "review", so it must not be
  // shown as a finding no matter which classification produced it.
  if (engineState === "AI_INDICATORS_NEED_REVIEW") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "AI-generation indicators need review",
      answer: "Possibly — an AI-generation indicator was found but not corroborated",
      note,
      state: "review",
    });
  }

  if (engineState === "NO_STRONG_AI_SIGNAL") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "No high-confidence AI-origin signal",
      answer: "No high-confidence AI signal detected",
      note,
      state: "clear",
    });
  }

  if (!synthetic) {
    return {
      key: "origin",
      question,
      headline: "AI-origin analysis needs activation",
      answer: "This scan did not receive an origin-analysis result",
      note,
      state: "unchecked",
    };
  }

  if (classification === "AI_ORIGIN_CHECK_DISABLED" || upper(synthetic.policy_mode, "") === "DISABLED") {
    return {
      key: "origin",
      question,
      headline: "AI-origin analysis is policy-controlled",
      answer: "AI-origin analysis is switched off by policy for this scan",
      note,
      state: "unchecked",
    };
  }

  if (classification === "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE") {
    return {
      key: "origin",
      question,
      headline: "AI-origin analysis needs activation",
      answer: "The origin-analysis route did not return a result",
      note,
      state: "unchecked",
    };
  }

  if (classification === "AI_ORIGIN_MARKER_FOUND") {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "A visible AI label was found",
      answer: "Yes — the image carries a visible AI-generation label",
      note,
      state: "hit",
    });
  }

  if (
    classification === "AI_ORIGIN_REVIEW_CANDIDATE" ||
    synthetic.review_recommended === true ||
    joint?.ai_origin_supported === true ||
    joint?.ai_origin_review === true
  ) {
    return withEngineHeadline({
      key: "origin",
      question,
      headline: "AI-generation indicators found",
      answer: "Possibly — AI-generation signals reached the review threshold",
      note,
      state: "review",
    });
  }

  return withEngineHeadline({
    key: "origin",
    question,
    headline: "No high-confidence AI-origin signal",
    answer: "No high-confidence AI signal detected",
    note,
    state: "clear",
  });
}

function profileLane(packet: Record_ | null): LaneStatus {
  const question = "Does it resemble a creator profile in this catalog?";
  const style = asRecord(packet?.style_analysis);
  const decision = asRecord(style?.decision);
  const joint = asRecord(asRecord(packet?.decision)?.joint_risk);
  const topProfile = asArray(style?.top_profiles)[0] ?? null;
  const creator = topProfile ? str(topProfile.creator) : null;
  const tier = upper(decision?.evidence_tier, "");
  const classification = upper(decision?.classification, "");
  const reasons = stringList(decision?.reason_codes).map((reason) => reason.toUpperCase());
  const exactStoredWork = asArray(packet?.matches).some((match) => match.exact_sha256 === true);
  const exemplarReviewOnly =
    upper(decision?.evidence_basis, "") === "STRONGEST_EXEMPLAR_CROSS_CONTENT" ||
    reasons.includes("SELECTED_EXEMPLAR_REVIEW_ONLY");
  const sampleCount =
    topProfile && typeof topProfile.sample_count === "number" && Number.isFinite(topProfile.sample_count)
      ? Math.max(0, Math.round(topProfile.sample_count))
      : null;
  const singleton = Boolean(
    !exemplarReviewOnly &&
      (sampleCount === 1 ||
        upper(topProfile?.profile_strength, "").includes("SINGLE") ||
        upper(decision?.profile_reliability, "").includes("SINGLE")),
  );
  const enrollmentUnconfirmed = Boolean(
    topProfile?.profile_authorized === false ||
      decision?.policy_escalation_authorized === false ||
      tier === "ADVISORY_ONLY" ||
      classification === "PROFILE_ENROLLMENT_NOT_CONSENT_BACKED" ||
      reasons.includes("PROFILE_CONSENT_NOT_CONFIRMED") ||
      reasons.includes("STYLE_POLICY_ESCALATION_SUPPRESSED"),
  );

  const profileSubject = enrollmentUnconfirmed
    ? creator
      ? `${creator}'s unconfirmed profile grouping`
      : "an unconfirmed profile grouping"
    : singleton
      ? creator
        ? `${creator}'s single registered exemplar`
        : "a single registered exemplar"
      : creator
        ? `the registered profile of ${creator}`
        : "a registered creator profile";

  const qualificationNote = exemplarReviewOnly
    ? enrollmentUnconfirmed
      ? `A strong cross-content resemblance to one exemplar in this ${sampleCount ?? "multi"}-work unconfirmed grouping was found. This selected-exemplar signal is review-only and cannot affect policy.`
      : `A strong cross-content resemblance to one exemplar in this ${sampleCount ?? "multi"}-work profile was found. Selected-exemplar evidence is review-only.`
    : enrollmentUnconfirmed
      ? singleton
        ? "Enrollment or consent is not confirmed, and only one exemplar represents this creator. This visual comparison cannot affect policy."
        : "Enrollment or consent is not confirmed, so this visual comparison cannot affect policy."
    : singleton
      ? "Only one exemplar represents this creator, so this is a limited pairwise comparison rather than a multi-work profile."
      : "Creator intelligence compares the candidate against the registered multi-work profile.";

  if (!style || !decision) {
    return {
      key: "profile",
      question,
      headline: "Creator-profile analysis did not run",
      answer: "No creator-profile result was returned for this scan",
      note: "Register an eligible exemplar or retry the scan if the catalog already contains one.",
      state: "unchecked",
    };
  }

  if (tier === "UNAVAILABLE" || classification.includes("UNAVAILABLE") || style.error_code) {
    return {
      key: "profile",
      question,
      headline: "Creator-profile analysis was unavailable",
      answer: "No creator-profile conclusion was produced",
      note: "The comparison provider did not complete, so this is not a clean result.",
      state: "unchecked",
    };
  }

  if (!topProfile || classification === "NO_STYLE_REFERENCE_CORPUS") {
    return {
      key: "profile",
      question,
      headline: "No creator profile to compare against",
      answer: "No eligible creator profile was available for this scan",
      note: "One eligible exemplar enables a limited comparison; three representative works create a stronger multi-work profile.",
      state: "unchecked",
    };
  }

  if (
    tier === "DIAGNOSTIC" ||
    classification.includes("DIAGNOSTIC") ||
    style.learned_provider_active === false
  ) {
    return {
      key: "profile",
      question,
      headline: "Learned creator-profile analysis was unavailable",
      answer: creator
        ? `No creator-profile conclusion — only low-level visual diagnostics against ${creator}`
        : "No creator-profile conclusion — only low-level visual diagnostics were produced",
      note: "Palette, tone, edge, and texture diagnostics cannot identify or attribute a creator.",
      state: "unchecked",
    };
  }

  if (exactStoredWork) {
    return {
      key: "profile",
      question,
      headline: "This is the registered work itself",
      answer: "Creator-style resemblance is not interpreted separately for byte-identical content",
      note: "Use the Work Match result: the candidate and stored reference have the same SHA-256 hash.",
      state: "unchecked",
    };
  }

  // Creator-profile resemblance is always advisory. New packets keep the
  // measured evidence tier separate from policy eligibility; older packets
  // rewrote the same review-worthy reading to ADVISORY_ONLY when enrollment or
  // consent was not confirmed. Both shapes must preserve the visual evidence on
  // screen while leaving policy escalation suppressed.
  const resemblanceObserved = Boolean(
    tier === "VERY_HIGH" ||
      tier === "HIGH" ||
      tier === "REVIEW" ||
      tier === "ADVISORY_ONLY" ||
      decision.evidence_review_recommended === true ||
      decision.review_recommended === true ||
      decision.supported === true ||
      joint?.style_supported === true ||
      classification === "PROFILE_ENROLLMENT_NOT_CONSENT_BACKED" ||
      reasons.includes("STYLE_RESEMBLANCE_REVIEW_RECOMMENDED"),
  );

  if (resemblanceObserved) {
    const strong = tier === "VERY_HIGH" || tier === "HIGH";
    return {
      key: "profile",
      question,
      headline: strong
        ? creator
          ? `Strong visual resemblance to ${creator}`
          : "Strong creator-profile resemblance"
        : creator
          ? `Visual resemblance to ${creator} needs context`
          : "Creator-profile resemblance needs context",
      answer: strong
        ? `Strong visual resemblance was found against ${profileSubject}`
        : `Visual resemblance was found against ${profileSubject}`,
      note: qualificationNote,
      state: "advisory",
    };
  }

  if (tier === "LOW") {
    return {
      key: "profile",
      question,
      headline: creator ? `No strong resemblance to ${creator}` : "No strong creator-profile signal",
      answer: `No resemblance to ${profileSubject} reached the review threshold`,
      note: qualificationNote,
      state: "clear",
    };
  }

  return {
    key: "profile",
    question,
    headline: "Creator-profile result needs interpretation",
    answer: "The creator-profile lane returned an unrecognized evidence state",
    note: "Open the advanced measurements or retry with a compatible analysis provider.",
    state: "unchecked",
  };
}

function rightsLane(packet: Record_ | null, scan: Record_): LaneStatus {
  const question = "What do the recorded rights say?";
  const decision = asRecord(packet?.decision);
  const path = upper(scan.rights_path ?? decision?.rights_path, "NO_LICENSE_INFO");
  const use = str(scan.intended_use) ?? "an unspecified use";
  const note = "The rights path is incorporated directly into the CreatorProof decision flow.";

  if (path === "EXISTING_LICENSE") {
    return {
      key: "rights",
      question,
      headline: "A recorded licence covers this use",
      answer: `A recorded licence covers ${use}`,
      note,
      state: "clear",
    };
  }

  if (path === "NO_LICENSE_INFO") {
    return {
      key: "rights",
      question,
      headline: "No licence is on record",
      answer: `No licence is on record for ${use}`,
      note,
      state: "advisory",
    };
  }

  return {
    key: "rights",
    question,
    headline: path.replace(/_/g, " ").toLowerCase(),
    answer: `${path.replace(/_/g, " ").toLowerCase()} for ${use}`,
    note,
    state: "advisory",
  };
}

/** Derive every lane answer from one evidence packet. */
export function laneStatuses(scan: Record_): LaneStatuses {
  const packet = asRecord(scan.evidence_packet);
  return {
    copy: copyLane(packet, scan),
    origin: originLane(packet),
    profile: profileLane(packet),
    rights: rightsLane(packet, scan),
  };
}

export function laneStatusList(scan: Record_): LaneStatus[] {
  const statuses = laneStatuses(scan);
  return [statuses.copy, statuses.origin, statuses.profile, statuses.rights];
}

/** The lane names in sentence case, for use inside a sentence. */
const LANE_NOUN: Record<LaneKey, string> = {
  copy: "stored-work copy",
  origin: "AI origin",
  profile: "creator profile",
  rights: "recorded rights",
};

/**
 * One line naming the lanes that returned something, or `null` when none did.
 *
 * This exists so the post-scan summary is derived from the same lane statuses
 * as the cards beneath it rather than from the engine's `joint_risk.headline`.
 * The two disagree on real runs: the joint headline reports "AI origin needs
 * review" whenever review was recommended, including when the lane's own
 * presentation state came back `ORIGIN_UNKNOWN` and the card therefore reads
 * "not run". A summary that contradicts the cards under it is worse than none.
 */
export function findingsLine(lanes: LaneStatus[]): string | null {
  const clauses = lanes
    .filter((lane) => lane.state === "hit" || lane.state === "review")
    .map((lane) =>
      lane.state === "hit"
        ? `${LANE_NOUN[lane.key]} found evidence`
        : `${LANE_NOUN[lane.key]} needs review`,
    );
  if (clauses.length === 0) return null;
  const line = clauses.join("; ");
  return line.charAt(0).toUpperCase() + line.slice(1);
}
