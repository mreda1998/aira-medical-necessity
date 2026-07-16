import { useRef, useState } from "react";
import { FileText, UploadCloud, X, ArrowRight, Loader2 } from "lucide-react";

interface DropFieldProps {
  label: string;
  hint: string;
  file: File | null;
  onFile: (f: File | null) => void;
}

function DropField({ label, hint, file, onFile }: DropFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function pick(files: FileList | null) {
    const f = files?.[0];
    if (f && f.type === "application/pdf") onFile(f);
  }

  return (
    <div>
      <p className="mb-2 text-[13px] font-semibold text-ink">{label}</p>
      {file ? (
        <div className="flex items-center gap-3 rounded-2xl border border-mint/40 bg-mint-tint px-4 py-3.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-mint text-white">
            <FileText size={17} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[14px] font-medium text-ink">{file.name}</p>
            <p className="text-[12px] text-ink-soft">{(file.size / 1024).toFixed(0)} KB</p>
          </div>
          <button
            onClick={() => onFile(null)}
            aria-label={`Remove ${label}`}
            className="flex h-7 w-7 items-center justify-center rounded-full text-ink-faint transition hover:bg-white hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            pick(e.dataTransfer.files);
          }}
          className={`flex w-full flex-col items-center gap-2 rounded-2xl border border-dashed px-4 py-7 text-center transition ${
            over ? "border-mint bg-mint-tint" : "border-line bg-canvas hover:border-mint/50 hover:bg-mint-tint/40"
          }`}
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-mint-deep shadow-sm">
            <UploadCloud size={19} />
          </span>
          <span className="text-[13.5px] font-medium text-ink">Drop PDF or click to browse</span>
          <span className="text-[12px] text-ink-faint">{hint}</span>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => pick(e.target.files)}
          />
        </button>
      )}
    </div>
  );
}

interface UploadPanelProps {
  guideline: File | null;
  chart: File | null;
  loading: boolean;
  error: string | null;
  onGuideline: (f: File | null) => void;
  onChart: (f: File | null) => void;
  onSubmit: () => void;
}

export function UploadPanel(props: UploadPanelProps) {
  const { guideline, chart, loading, error } = props;
  const ready = !!guideline && !!chart && !loading;

  return (
    <div className="mx-auto w-full max-w-xl px-5 pt-16">
      <div className="mb-8 text-center">
        <h1 className="text-[26px] font-semibold tracking-tight text-ink">
          Check medical necessity in seconds
        </h1>
        <p className="mx-auto mt-2 max-w-md text-[15px] leading-relaxed text-ink-soft">
          Upload a payer guideline and a patient chart. Get a verdict with the exact evidence
          gaps — before you submit the prior authorization.
        </p>
      </div>

      <div className="animate-rise rounded-card border border-line bg-white p-6 shadow-[0_1px_2px_rgba(12,15,17,0.04),0_16px_40px_-20px_rgba(12,15,17,0.16)] sm:p-7">
        <div className="space-y-5">
          <DropField
            label="Payer guideline"
            hint="Medical necessity policy PDF"
            file={guideline}
            onFile={props.onGuideline}
          />
          <DropField
            label="Patient chart"
            hint="Clinical record PDF"
            file={chart}
            onFile={props.onChart}
          />
        </div>

        {error && (
          <p className="mt-5 rounded-xl border border-danger/25 bg-danger-tint px-4 py-2.5 text-[13px] text-danger">
            {error}
          </p>
        )}

        <button
          onClick={props.onSubmit}
          disabled={!ready}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-pill bg-ink px-5 py-3.5 text-[15px] font-semibold text-white transition enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35"
        >
          {loading ? (
            <>
              <Loader2 size={17} className="animate-spin" />
              Evaluating…
            </>
          ) : (
            <>
              Evaluate necessity
              <ArrowRight size={17} />
            </>
          )}
        </button>

        {loading && (
          <p className="mt-3 text-center text-[12.5px] text-ink-faint">
            Compiling the guideline and reading the chart — a new guideline can take ~20s.
          </p>
        )}
      </div>
    </div>
  );
}
