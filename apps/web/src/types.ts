export type Span = {
  document_id: string; passage_id: string; char_start: number; char_end: number; quote: string;
  page: number | null; section: string | null; document_title: string | null; document_version: string | null;
};
export type Deadline = { kind: string; raw: string | null; date: string | null; offset_days: number | null;
  business_days: boolean; anchor: string | null; ambiguous_format: boolean };
export type Doc = {
  id: string; title: string; version_label: string; doc_type: string; source: string; author: string | null;
  filename: string | null; uploaded_at: string; checksum_sha256: string; page_count: number | null; status: string;
  warnings: string[]; tags: string[]; amends_document_id: string | null; allow_external_llm: boolean;
};
export type Passage = { id: string; ordinal: number; page: number | null; section_number: string | null;
  section_title: string | null; char_start: number; char_end: number; text: string };
export type Commitment = {
  id: string; document_id: string; text: string; type: string; modality: string; obliging_party: string | null;
  performer_party: string | null; beneficiary_party: string | null; action: string; deadline: Deadline | null;
  conditions: string[]; exceptions: string[]; references: string[]; section_number: string | null;
  document_effect: string; lifecycle: string; amends_section: string | null; status: string; confidence: string;
  needs_review: boolean; review_reasons: string[]; caveats: string[];
  provenance: { span: Span; extraction_method: string; review_status: string; model: string | null };
};
export type Claim = { id: string; text: string; claim_type: string; section_number: string | null;
  provenance: { span: Span } };
export type Citation = { span: Span; role: string; verified: boolean; note: string | null };
export type Answer = {
  id: string; question: string; status: string; answer_text: string; confidence: string; citations: Citation[];
  graph_path: { node: string; edge: string | null }[]; caveats: string[]; follow_ups: string[];
  review_status: string; needs_review: boolean;
};
export type Finding = {
  id: string; verdict: string; subject_text: string; subject_span: Span | null; supporting: Span[];
  conflicting: Span[]; explanation: string; severity: string; recommended_action: string;
  sufficiency: string | null; review_status: string;
};
export type VerificationRun = { id: string; base_document_id: string; other_document_id: string; mode: string;
  findings: Finding[]; summary: Record<string, number> };
export type Run = { id: string; status: string; error: string | null; counts: Record<string, number> };
export type GraphData = { nodes: { id: string; type: string; label: string; text?: string }[];
  edges: { id: string; src_id: string; dst_id: string; type: string }[] };
