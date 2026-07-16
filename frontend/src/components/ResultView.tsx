import { ShieldCheck } from "lucide-react";
import type { RunResult, BranchResult } from "../api";
import { STATUS, leavesOf } from "../lib/status";
import { CriterionRow } from "./CriterionRow";

function titleCase(s?: string | null) {
  if (!s) return "";
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

function ProcedurePill({ order }: { order: RunResult["order"] }) {
  const label = titleCase(order.modality) || "Procedure";
  return (
    <span className="inline-flex items-center gap-2 rounded-pill border border-line bg-white px-3.5 py-1.5 text-[13px] font-medium text-ink">
      {label}
      {order.cpt && <span className="text-ink-faint">· CPT {order.cpt}</span>}
    </span>
  );
}

function VerdictBanner({ branch }: { branch: BranchResult }) {
  const style = STATUS[branch.verdict];
  const leaves = leavesOf(branch.tree);
  const met = leaves.filter((l) => l.status === "MET").length;
  const insufficient = leaves.filter((l) => l.status === "INSUFFICIENT_EVIDENCE").length;
  const notMet = leaves.filter((l) => l.status === "NOT_MET").length;

  const detail =
    branch.verdict === "MET"
      ? `All ${leaves.length} criteria satisfied`
      : branch.verdict === "NOT_MET"
        ? `${notMet} criteri${notMet === 1 ? "on" : "a"} not met`
        : `${insufficient} item${insufficient === 1 ? "" : "s"} to resolve · ${met} of ${leaves.length} met`;

  return (
    <div
      className={`flex items-center gap-3 rounded-2xl border ${style.bannerBorder} ${style.bannerBg} px-4 py-3.5`}
    >
      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${style.dot}`} />
      <div>
        <p className={`text-[15px] font-semibold ${style.fg}`}>{style.verdictLabel}</p>
        <p className="text-[13px] text-ink-soft">{detail}</p>
      </div>
    </div>
  );
}

function BranchCard({ branch }: { branch: BranchResult }) {
  const leaves = leavesOf(branch.tree);
  return (
    <section className="animate-rise rounded-card border border-line bg-white p-6 shadow-[0_1px_2px_rgba(12,15,17,0.04),0_12px_32px_-16px_rgba(12,15,17,0.12)] sm:p-7">
      <p className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-faint">
        {branch.procedure_label}
      </p>

      <div className="mt-4">
        <VerdictBanner branch={branch} />
      </div>

      {Object.keys(branch.gap_flags).length > 0 && (
        <div className="mt-4 rounded-xl border border-warn/25 bg-warn-tint px-4 py-3">
          <p className="text-[13px] font-semibold text-warn">
            Second-model review flagged these fields
          </p>
          <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[13px] text-ink-soft">
            {Object.entries(branch.gap_flags).map(([field, flag]) => (
              <li key={field}>
                {field} <span className="text-ink-faint">({flag.split("_").join(" ")})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <ul className="mt-2 divide-y divide-line">
        {leaves.map((leaf) => (
          <CriterionRow
            key={leaf.node_id}
            node={leaf}
            flag={leaf.field ? branch.gap_flags[leaf.field] : undefined}
          />
        ))}
      </ul>
    </section>
  );
}

export function ResultView({ result, onReset }: { result: RunResult; onReset: () => void }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-5 pb-20 pt-10">
      <div className="mb-5 flex items-center justify-between">
        <p className="text-[13px] font-semibold uppercase tracking-[0.18em] text-ink-faint">
          Medical Necessity
        </p>
        <ProcedurePill order={result.order} />
      </div>

      {/* Policy / guideline source card */}
      <div className="mb-6 rounded-2xl border border-mint/30 bg-mint-tint px-5 py-4">
        <div className="flex items-center gap-2 text-[12.5px] font-semibold uppercase tracking-[0.12em] text-mint-deep">
          <ShieldCheck size={15} />
          Payer guideline
        </div>
        <p className="mt-1.5 text-[15px] font-semibold text-ink">{result.title}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="rounded-pill border border-mint/30 bg-white/70 px-2.5 py-0.5 text-[12px] font-medium text-mint-deep">
            Policy {result.guideline_id}
          </span>
          {result.route_flag && (
            <span className="rounded-pill border border-warn/30 bg-warn-tint px-2.5 py-0.5 text-[12px] font-medium text-warn">
              {result.route_flag.split("_").join(" ")} — showing all branches
            </span>
          )}
        </div>
      </div>

      <div className="space-y-6">
        {result.evaluated_branches.map((b) => (
          <BranchCard key={b.branch_id} branch={b} />
        ))}
      </div>

      <div className="mt-8 flex justify-center">
        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 rounded-pill border border-line bg-white px-5 py-2.5 text-[14px] font-medium text-ink transition hover:bg-canvas"
        >
          Check another chart
        </button>
      </div>
    </div>
  );
}
