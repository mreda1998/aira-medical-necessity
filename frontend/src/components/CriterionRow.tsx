import { FileText, AlertTriangle } from "lucide-react";
import type { EvalNode } from "../api";
import { STATUS } from "../lib/status";

function evidenceText(node: EvalNode): { quote: string | null; missing: boolean } {
  const ev = node.evidence;
  if (!ev || !ev.found) return { quote: null, missing: true };
  const quote = ev.source_span?.text?.trim();
  if (quote) return { quote, missing: false };
  // found but no span — fall back to the value
  const v = ev.value;
  if (v !== undefined && v !== null && v !== "")
    return { quote: `Documented: ${String(v)}`, missing: false };
  return { quote: "Documented", missing: false };
}

export function CriterionRow({ node, flag }: { node: EvalNode; flag?: string }) {
  const style = STATUS[node.status];
  const Icon = style.icon;
  const { quote, missing } = evidenceText(node);
  const unmappable = node.kind === "unmappable";

  return (
    <li className="flex gap-3.5 py-4">
      <span
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md ${style.chipBg} text-white`}
      >
        <Icon size={13} strokeWidth={3} />
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-semibold leading-snug text-ink">
          {node.human_readable ?? node.field ?? node.node_id}
        </p>

        {node.guideline_span?.text && (
          <p className="mt-1 text-[13.5px] leading-relaxed text-ink-soft">
            {node.guideline_span.text.trim()}
          </p>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
          {unmappable ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-warn">
              <AlertTriangle size={13} />
              Rule could not be mapped — needs manual review
            </span>
          ) : missing ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-ink-faint">
              <FileText size={13} />
              Not found in chart
            </span>
          ) : (
            <span className={`inline-flex items-center gap-1.5 font-medium ${style.fg}`}>
              <FileText size={13} />
              {quote}
            </span>
          )}

          {flag && (
            <span className="inline-flex items-center gap-1.5 rounded-pill bg-warn-tint px-2 py-0.5 text-[12px] font-medium text-warn">
              <AlertTriangle size={12} />
              {flag.split("_").join(" ")}
            </span>
          )}
        </div>
      </div>

      <span className={`mt-0.5 shrink-0 text-[12.5px] font-semibold ${style.fg}`}>
        {style.leafLabel}
      </span>
    </li>
  );
}
