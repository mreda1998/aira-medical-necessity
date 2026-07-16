export type Status = "MET" | "NOT_MET" | "INSUFFICIENT_EVIDENCE";

export interface EvalNode {
  node_id: string; kind: string; status: Status; human_readable?: string;
  field?: string; evidence?: { value?: unknown; found: boolean; source_span?: { text: string } };
  guideline_span?: { text: string }; flags: string[]; children: EvalNode[];
}
export interface BranchResult {
  branch_id: string; procedure_label: string; verdict: Status;
  tree: EvalNode; gap_flags: Record<string, string>;
}
export interface RunResult {
  guideline_id: string; title: string;
  order: { modality?: string; vein?: string; laterality?: string; cpt?: string };
  route_flag?: string | null; evaluated_branches: BranchResult[];
}

export async function evaluate(guideline: File, chart: File): Promise<RunResult> {
  const fd = new FormData();
  fd.append("guideline", guideline);
  fd.append("chart", chart);
  const resp = await fetch("/api/evaluate", { method: "POST", body: fd });
  if (!resp.ok) throw new Error(`evaluate failed: ${resp.status}`);
  return resp.json();
}
