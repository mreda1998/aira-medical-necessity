import type { EvalNode, Status } from "../api";

const COLOR: Record<Status, string> = {
  MET: "#137333", NOT_MET: "#b3261e", INSUFFICIENT_EVIDENCE: "#a56300",
};
const LABEL: Record<Status, string> = {
  MET: "Met", NOT_MET: "Not met", INSUFFICIENT_EVIDENCE: "Missing evidence",
};

function leaves(node: EvalNode): EvalNode[] {
  if (node.kind === "leaf" || node.kind === "unmappable") return [node];
  return node.children.flatMap(leaves);
}

export function GapList({ tree }: { tree: EvalNode }) {
  return (
    <ul style={{ listStyle: "none", padding: 0 }}>
      {leaves(tree).map((n) => (
        <li key={n.node_id} style={{ borderLeft: `4px solid ${COLOR[n.status]}`,
             padding: "8px 12px", margin: "8px 0", background: "#fafafa" }}>
          <strong style={{ color: COLOR[n.status] }}>{LABEL[n.status]}</strong> — {n.human_readable}
          {n.guideline_span && <div style={{ fontSize: 12, color: "#555" }}>
            Guideline: “{n.guideline_span.text}”</div>}
          <div style={{ fontSize: 12, color: "#555" }}>
            {n.evidence?.found
              ? <>Chart: “{n.evidence.source_span?.text}”</>
              : <em>NOT FOUND IN CHART</em>}
          </div>
          {n.flags.length > 0 && <div style={{ fontSize: 12, color: "#a56300" }}>
            ⚑ {n.flags.join(", ")}</div>}
        </li>
      ))}
    </ul>
  );
}
