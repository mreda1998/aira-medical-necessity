import { useState } from "react";
import { evaluate, type RunResult } from "./api";
import { UploadPanel } from "./components/UploadPanel";
import { ResultView } from "./components/ResultView";

function Header() {
  return (
    <header className="border-b border-line bg-white/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-3xl items-center gap-2.5 px-5">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ink">
          <span className="h-2.5 w-2.5 rounded-full bg-mint" />
        </span>
        <span className="text-[15px] font-semibold tracking-tight text-ink">Aira</span>
        <span className="text-[15px] text-ink-faint">Medical Necessity</span>
      </div>
    </header>
  );
}

export function App() {
  const [guideline, setGuideline] = useState<File | null>(null);
  const [chart, setChart] = useState<File | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!guideline || !chart) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await evaluate(guideline, chart));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setResult(null);
    setError(null);
    setGuideline(null);
    setChart(null);
  }

  return (
    <div className="min-h-full">
      <Header />
      {result ? (
        <ResultView result={result} onReset={reset} />
      ) : (
        <UploadPanel
          guideline={guideline}
          chart={chart}
          loading={loading}
          error={error}
          onGuideline={setGuideline}
          onChart={setChart}
          onSubmit={submit}
        />
      )}
    </div>
  );
}
