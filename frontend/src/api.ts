export type Status = "MET" | "NOT_MET" | "INSUFFICIENT_EVIDENCE";
export type EvidenceState =
  | "DOCUMENTED"
  | "EXPLICITLY_ABSENT"
  | "NOT_DOCUMENTED"
  | "CONFLICTING";

export interface SourceSpan {
  text: string;
  page?: number;
  printed_page?: string;
  section?: string;
  match_method?: "exact" | "fuzzy" | "page_verified" | "model_reported" | "unverified";
  match_confidence?: number;
}

export interface EvalNode {
  node_id: string; kind: string; status: Status; human_readable?: string;
  field?: string;
  evidence?: { value?: unknown; found: boolean; state?: EvidenceState; source_span?: SourceSpan };
  guideline_span?: SourceSpan; flags: string[]; children: EvalNode[];
}
export interface BranchResult {
  branch_id: string; procedure_label: string; verdict: Status;
  tree: EvalNode; decisive_findings: EvalNode[]; gap_flags: Record<string, string>;
}
export interface RunResult {
  guideline_id: string; title: string;
  order: { modality?: string; vein?: string; laterality?: string; cpt?: string; patient_age?: number };
  guideline_document: DocumentSummary;
  chart_document: DocumentSummary;
  route_flag?: string | null; evaluated_branches: BranchResult[];
  /** ordered per-step intermediate artifacts; present only in debug mode */
  debug?: { step: string; data: unknown }[] | null;
}

export interface DocumentSummary {
  filename?: string;
  page_count: number;
  byte_size: number;
  text_page_count: number;
  text_coverage: number;
  scanned_likely: boolean;
  warnings: string[];
}

export interface EvaluationProgress {
  stage: string;
  message: string;
  current?: number;
  total?: number;
  elapsed_seconds: number;
}

type StreamEvent =
  | { type: "progress"; progress: EvaluationProgress }
  | { type: "result"; result: RunResult }
  | { type: "error"; status: number; detail: string };

export async function evaluate(
  guideline: File,
  chart: File,
  onProgress?: (progress: EvaluationProgress) => void,
): Promise<RunResult> {
  const fd = new FormData();
  fd.append("guideline", guideline);
  fd.append("chart", chart);
  const resp = await fetch("/api/evaluate/stream", { method: "POST", body: fd });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).detail ?? ""; } catch { /* non-JSON body */ }
    throw new Error(`evaluate failed (${resp.status})${detail ? `: ${detail}` : ""}`);
  }
  if (!resp.body) throw new Error("evaluate failed: the server returned no response stream");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: RunResult | null = null;

  function consume(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line) as StreamEvent;
    if (event.type === "progress") onProgress?.(event.progress);
    if (event.type === "result") result = event.result;
    if (event.type === "error") {
      throw new Error(`evaluate failed (${event.status}): ${event.detail}`);
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(consume);
    if (done) break;
  }
  consume(buffer);
  if (!result) throw new Error("evaluate failed: the response ended before a result was returned");
  return result;
}
