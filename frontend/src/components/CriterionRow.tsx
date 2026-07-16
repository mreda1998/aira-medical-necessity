import { FileText, AlertTriangle, ExternalLink } from "lucide-react";
import type { EvalNode, EvidenceState, SourceSpan } from "../api";
import { STATUS } from "../lib/status";

function CitationLink({
  label,
  span,
  fileUrl,
}: {
  label: string;
  span?: SourceSpan;
  fileUrl?: string;
}) {
  if (!span?.text) return null;
  const verified =
    span.page !== undefined &&
    span.match_method !== "unverified" &&
    span.match_method !== "model_reported";
  const page = span.page ? `PDF p. ${span.page}` : "location unverified";
  const printed =
    span.printed_page && span.printed_page !== String(span.page)
      ? ` · document p. ${span.printed_page}`
      : "";
  const text = `${label} · ${page}${printed}${span.section ? ` · ${span.section}` : ""}`;

  if (!verified || !fileUrl) {
    return <span className="text-[12px] font-medium text-ink-faint">{text}</span>;
  }
  return (
    <a
      href={`${fileUrl}#page=${span.page}`}
      target="_blank"
      rel="noreferrer"
      className="inline-flex max-w-full items-center gap-1.5 rounded-pill border border-line bg-canvas px-2.5 py-1 text-[12px] font-medium text-ink-soft transition hover:border-mint/60 hover:text-mint-deep"
      title={`Open ${label.toLowerCase()} at PDF page ${span.page}`}
    >
      <span className="truncate">{text}</span>
      <ExternalLink size={11} className="shrink-0" />
    </a>
  );
}

function evidenceState(node: EvalNode): EvidenceState {
  if (node.evidence?.state) return node.evidence.state;
  return node.evidence?.found ? "DOCUMENTED" : "NOT_DOCUMENTED";
}

function evidenceText(node: EvalNode): { label: string; quote: string | null } {
  const evidence = node.evidence;
  const quote = evidence?.source_span?.text?.trim() || null;
  switch (evidenceState(node)) {
    case "CONFLICTING":
      return { label: "Conflicting chart evidence", quote };
    case "NOT_DOCUMENTED":
      return { label: "Not documented in chart", quote };
    case "EXPLICITLY_ABSENT":
      return { label: "Explicitly absent", quote };
    case "DOCUMENTED": {
      if (quote) return { label: "Documented", quote };
      const value = evidence?.value;
      return {
        label: "Documented",
        quote: value !== undefined && value !== null && value !== "" ? String(value) : null,
      };
    }
  }
}

export function CriterionRow({
  node,
  flag,
  guidelineUrl,
  chartUrl,
}: {
  node: EvalNode;
  flag?: string;
  guidelineUrl?: string;
  chartUrl?: string;
}) {
  const style = STATUS[node.status];
  const Icon = style.icon;
  const evidence = evidenceText(node);
  const state = evidenceState(node);
  const unresolved = state === "NOT_DOCUMENTED" || state === "CONFLICTING";
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
          <div className="mt-1.5">
            <p className="text-[13.5px] leading-relaxed text-ink-soft">
              {node.guideline_span.text.trim()}
            </p>
            <div className="mt-2">
              <CitationLink label="Guideline" span={node.guideline_span} fileUrl={guidelineUrl} />
            </div>
          </div>
        )}

        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px]">
          {unmappable ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-warn">
              <AlertTriangle size={13} />
              Rule could not be mapped — needs manual review
            </span>
          ) : (
            <span
              className={`inline-flex items-start gap-1.5 font-medium ${
                unresolved ? "text-warn" : style.fg
              }`}
            >
              {unresolved ? <AlertTriangle size={13} className="mt-0.5" /> : <FileText size={13} className="mt-0.5" />}
              <span>
                {evidence.label}
                {evidence.quote ? ` — “${evidence.quote}”` : ""}
              </span>
            </span>
          )}

          {!unmappable && node.evidence?.source_span && (
            <CitationLink label="Chart" span={node.evidence.source_span} fileUrl={chartUrl} />
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
