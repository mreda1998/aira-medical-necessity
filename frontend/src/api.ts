export type Status = "MET" | "NOT_MET" | "INSUFFICIENT_EVIDENCE";

export interface EvalNode {
  node_id: string; kind: string; status: Status; human_readable?: string;
  field?: string; evidence?: { value?: unknown; found: boolean; source_span?: { text: string } };
  guideline_span?: { text: string }; flags: string[]; children: EvalNode[];
}
export interface BranchResult {
  branch_id: string; procedure_label: string; verdict: Status;
  tree: EvalNode; decisive_findings: EvalNode[]; gap_flags: Record<string, string>;
}
export interface RunResult {
  guideline_id: string; title: string;
  order: { modality?: string; vein?: string; laterality?: string; cpt?: string; patient_age?: number };
  route_flag?: string | null; evaluated_branches: BranchResult[];
  /** ordered per-step intermediate artifacts; present only in debug mode */
  debug?: { step: string; data: unknown }[] | null;
}

export async function evaluate(guideline: File, chart: File): Promise<RunResult> {
  const fd = new FormData();
  fd.append("guideline", guideline);
  fd.append("chart", chart);
  const resp = await fetch("/api/evaluate", { method: "POST", body: fd });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).detail ?? ""; } catch { /* non-JSON body */ }
    throw new Error(`evaluate failed (${resp.status})${detail ? `: ${detail}` : ""}`);
  }
  return resp.json();
}
