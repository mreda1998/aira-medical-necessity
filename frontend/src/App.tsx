import { useState } from "react";
import { evaluate, type RunResult, type Status } from "./api";
import { GapList } from "./components/GapList";

const VERDICT_TEXT: Record<Status, string> = {
  MET: "MEETS medical necessity", NOT_MET: "DOES NOT MEET",
  INSUFFICIENT_EVIDENCE: "INCOMPLETE — items to resolve",
};

export function App() {
  const [guideline, setGuideline] = useState<File | null>(null);
  const [chart, setChart] = useState<File | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!guideline || !chart) return;
    setLoading(true); setError(null); setResult(null);
    try { setResult(await evaluate(guideline, chart)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ maxWidth: 780, margin: "40px auto", fontFamily: "system-ui" }}>
      <h1>Medical Necessity Checker</h1>
      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        <label>Guideline PDF <input type="file" accept="application/pdf"
          onChange={(e) => setGuideline(e.target.files?.[0] ?? null)} /></label>
        <label>Patient chart PDF <input type="file" accept="application/pdf"
          onChange={(e) => setChart(e.target.files?.[0] ?? null)} /></label>
        <button onClick={submit} disabled={!guideline || !chart || loading}>
          {loading ? "Evaluating…" : "Evaluate"}</button>
      </div>
      {error && <p style={{ color: "#b3261e" }}>{error}</p>}
      {result && (
        <div style={{ marginTop: 24 }}>
          <p><strong>Order:</strong> {result.order.modality} of {result.order.vein}
            {result.route_flag && <span style={{ color: "#a56300" }}> ⚑ {result.route_flag}</span>}</p>
          {result.evaluated_branches.map((b) => (
            <div key={b.branch_id} style={{ marginBottom: 24 }}>
              <h2 style={{ marginBottom: 4 }}>{b.procedure_label}</h2>
              <p style={{ fontWeight: 700 }}>{VERDICT_TEXT[b.verdict]}</p>
              {Object.keys(b.gap_flags).length > 0 && (
                <div style={{ background: "#fff7e6", border: "1px solid #a56300", borderRadius: 4,
                              padding: "8px 12px", margin: "8px 0", fontSize: 13 }}>
                  <strong style={{ color: "#a56300" }}>⚑ Verifier disagreement — review these fields:</strong>
                  <ul style={{ margin: "4px 0 0 18px" }}>
                    {Object.entries(b.gap_flags).map(([field, flag]) => (
                      <li key={field}>{field} ({flag.split("_").join(" ")})</li>
                    ))}
                  </ul>
                </div>
              )}
              <GapList tree={b.tree} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
