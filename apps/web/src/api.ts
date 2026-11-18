import type { Answer, Claim, Commitment, Doc, GraphData, Passage, Run, VerificationRun } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, credentials: "same-origin" });
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (body as { error?: { code: string; message: string } }).error;
    throw new ApiError(err?.code ?? "error", err?.message ?? `Request failed (${res.status})`);
  }
  return body as T;
}

const json = (data: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data) });

export const api = {
  health: () => req<{ config: Record<string, unknown> }>("/health"),
  documents: () => req<Doc[]>("/documents"),
  document: (id: string) => req<{ document: Doc; passages: Passage[]; amended_by: string[];
    parties: { name: string; alias: string | null }[]; definitions: { term: string; definition_text: string }[] }>(
    `/documents/${id}`),
  upload: (form: FormData) => req<Doc>("/documents", { method: "POST", body: form }),
  patch: (id: string, data: Partial<Doc>) => req<Doc>(`/documents/${id}`, { ...json(data), method: "PATCH" }),
  remove: (id: string) => req<{ deleted: string }>(`/documents/${id}`, { method: "DELETE" }),
  analyze: (id: string) => req<{ run: Run; poll: string }>(`/documents/${id}/analyze`, { method: "POST" }),
  run: (poll: string) => req<Run>(poll),
  commitments: (id: string) => req<Commitment[]>(`/documents/${id}/commitments`),
  claims: (id: string) => req<Claim[]>(`/documents/${id}/claims`),
  graph: (id: string) => req<GraphData>(`/documents/${id}/graph`),
  ask: (question: string, document_ids?: string[]) => req<Answer>("/ask", json({ question, document_ids })),
  verify: (base: string, other: string) =>
    req<VerificationRun>("/verify", json({ base_document_id: base, other_document_id: other })),
  verifications: (id: string) => req<VerificationRun[]>(`/documents/${id}/verifications`),
  review: (kind: "answers" | "findings" | "commitments", id: string,
    body: { decision: string; reviewer: string; note?: string; lifecycle?: string }) =>
    req(`/${kind}/${id}/review`, json(body)),
  samples: () => req<{ loaded: string[] }>("/samples", { method: "POST" }),
};
