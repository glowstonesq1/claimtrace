// Plain-language labels (design-review D18). API enums stay precise; people see these words.
type Tone = "ok" | "bad" | "warn" | "info" | "muted";
export const VERDICT: Record<string, { label: string; tone: Tone; icon: string }> = {
  consistent: { label: "Matches", tone: "ok", icon: "check" },
  contradicted: { label: "Conflicts", tone: "bad", icon: "cross" },
  partially_supported: { label: "Partly supported", tone: "warn", icon: "half" },
  not_addressed: { label: "Not mentioned", tone: "muted", icon: "dash" },
  ambiguous: { label: "Unclear — please read", tone: "warn", icon: "question" },
  needs_human_review: { label: "Needs your review", tone: "warn", icon: "eye" },
};
export const ANSWER: Record<string, { label: string; tone: Tone; icon: string }> = {
  stated: { label: "Stated in the document", tone: "ok", icon: "check" },
  implied: { label: "Implied, not stated", tone: "warn", icon: "half" },
  contradicted: { label: "Documents disagree", tone: "bad", icon: "cross" },
  not_addressed: { label: "Not found", tone: "muted", icon: "dash" },
  ambiguous: { label: "Unclear — please read", tone: "warn", icon: "question" },
  needs_human_review: { label: "Needs your review", tone: "warn", icon: "eye" },
};
export const CONFIDENCE: Record<string, string> = {
  high: "Found in the text; check the quote",
  medium: "Found, with conditions or caveats; read carefully",
  low: "Unsure; please read the source",
  unknown: "No supporting text",
};
export const TYPE: Record<string, string> = {
  obligation: "Must do", entitlement: "May do", prohibition: "Must not do", condition: "Condition",
  deadline: "Deadline", consequence: "If not done", service_level: "Service level",
};
export const EFFECT: Record<string, string> = { in_force: "Current", replaced: "Replaced by amendment",
  deleted: "Deleted by amendment" };
export const REVIEW: Record<string, string> = { unreviewed: "Not reviewed", accepted: "Looks right",
  rejected: "Wrong", needs_evidence: "Evidence requested", resolved: "Handled" };
export const DOC_TYPES = ["contract", "amendment", "sow", "proposal", "policy", "audit_report", "evidence", "report", "other"];
export const DOC_TYPE_LABEL: Record<string, string> = { contract: "Contract", amendment: "Amendment", sow: "Statement of work",
  proposal: "Proposal", policy: "Policy", audit_report: "Audit report", evidence: "Evidence / record", report: "Report",
  other: "Other" };
export function where(s: { document_title: string | null; document_version: string | null; section: string | null;
  page: number | null }): string {
  return [s.document_title && `${s.document_title} (${s.document_version})`, s.section && `§${s.section}`,
    s.page && `page ${s.page}`].filter(Boolean).join(", ");
}
