import logging
import re
import time
from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel, Field

from .llm import LLM
from .models import Status, Order, EvalResult
from .pdf_extract import DocumentQualityError, ExtractedDocument, extract_document
from .compiler import compile_cached
from .router import extract_order, select_branch
from .extractor import extract_facts
from .verifier import leaves_to_verify, verify_facts
from .evaluator import evaluate, decisive_findings
from .trace import Tracer

log = logging.getLogger("aira.pipeline")


class BranchResult(BaseModel):
    branch_id: str
    procedure_label: str
    verdict: Status
    tree: EvalResult
    decisive_findings: list[EvalResult]
    gap_flags: dict[str, str] = Field(default_factory=dict)


class DocumentSummary(BaseModel):
    filename: str | None = None
    page_count: int
    byte_size: int
    text_page_count: int
    text_coverage: float
    scanned_likely: bool
    warnings: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    guideline_id: str
    title: str
    order: Order
    guideline_document: DocumentSummary
    chart_document: DocumentSummary
    route_flag: str | None = None
    evaluated_branches: list[BranchResult]
    # Populated only when a Tracer is passed (debug mode): the ordered
    # intermediate JSON artifacts from every pipeline step.
    debug: Optional[list] = None


class ProgressUpdate(BaseModel):
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    elapsed_seconds: float


ProgressCallback = Callable[[ProgressUpdate], None]


def _document_summary(
    document: ExtractedDocument,
    data: bytes,
    filename: str | None,
    label: str,
) -> DocumentSummary:
    character_counts = [len(re.sub(r"\s+", "", page.text)) for page in document.pages]
    total_characters = sum(character_counts)
    if not document.pages:
        raise DocumentQualityError(f"{label} has no pages")
    if total_characters < 20:
        raise DocumentQualityError(
            f"{label} has no usable text layer; upload a text-readable PDF"
        )

    text_pages = sum(count >= 20 for count in character_counts)
    coverage = text_pages / len(document.pages)
    scanned_likely = coverage < 0.5
    warnings: list[str] = []
    if coverage < 1:
        warnings.append(
            f"{label}: {len(document.pages) - text_pages} of {len(document.pages)} pages "
            "have little or no extractable text."
        )
    if scanned_likely:
        warnings.append(
            f"{label}: this PDF appears image-heavy; some evidence may require OCR or vision."
        )
    if len(document.pages) >= 75:
        warnings.append(
            f"{label}: long document ({len(document.pages)} pages); processing may be slower."
        )

    return DocumentSummary(
        filename=filename,
        page_count=len(document.pages),
        byte_size=len(data),
        text_page_count=text_pages,
        text_coverage=round(coverage, 3),
        scanned_likely=scanned_likely,
        warnings=warnings,
    )


def run(
    guideline_bytes: bytes,
    chart_bytes: bytes,
    primary: LLM,
    verifier: LLM,
    tracer: Optional[Tracer] = None,
    guideline_name: str | None = None,
    chart_name: str | None = None,
    progress: ProgressCallback | None = None,
) -> RunResult:
    started = time.perf_counter()

    def emit(
        stage: str,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        update = ProgressUpdate(
            stage=stage,
            message=message,
            current=current,
            total=total,
            elapsed_seconds=round(time.perf_counter() - started, 2),
        )
        log.info("progress: %s - %s", stage, message)
        if progress:
            progress(update)

    # Preflight both PDFs before the first provider call. This fails clearly on
    # image-only files instead of asking the LLM to reason over empty text.
    emit("document_preflight", "Reading and checking both PDFs")
    guideline_document = extract_document(guideline_bytes)
    chart_document = extract_document(chart_bytes)
    guideline_summary = _document_summary(
        guideline_document, guideline_bytes, guideline_name, "Guideline"
    )
    chart_summary = _document_summary(chart_document, chart_bytes, chart_name, "Patient chart")
    if tracer:
        tracer.add("document_preflight", {
            "guideline": guideline_summary.model_dump(mode="json"),
            "chart": chart_summary.model_dump(mode="json"),
        })

    emit("guideline_cache", "Checking the compiled-policy cache")
    tree = compile_cached(
        guideline_bytes,
        primary,
        guideline_document,
        on_cache=lambda hit: emit(
            "guideline_cache",
            "Using cached policy criteria" if hit else "New policy - compilation required",
        ),
        on_selection=lambda original, selected, strategy: emit(
            "guideline_selection",
            (
                f"Selected {selected} of {original} policy pages using {strategy.replace('_', ' ')}"
                if selected < original
                else f"Using all {original} policy pages"
            ),
        ),
        on_attempt=lambda current, total: emit(
            "guideline_compilation",
            f"Compiling policy criteria - attempt {current} of {total}",
            current,
            total,
        ),
    )
    log.info(
        "guideline compiled: id=%s title=%r branches=%d",
        tree.guideline_id,
        tree.title,
        len(tree.branches),
    )
    if tracer:
        tracer.add("guideline_tree", tree.model_dump(mode="json"))

    emit("chart_extraction", "Preparing page-aware chart text")
    chart_text = chart_document.marked_text
    log.info("chart extracted: %d chars", len(chart_text))
    if tracer:
        tracer.add("chart_text", {"chars": len(chart_text), "preview": chart_text[:3000]})

    emit("order_extraction", "Extracting the requested procedure")
    order = extract_order(chart_text, primary)
    log.info("order extracted: %s", order.model_dump())
    if tracer:
        tracer.add("order", order.model_dump(mode="json"))

    emit("routing", "Matching the requested procedure to policy branches")
    branches, route_flag = select_branch(order, tree)
    log.info(
        "routed to %d branch(es)%s",
        len(branches),
        f" (flag={route_flag})" if route_flag else "",
    )
    if tracer:
        tracer.add(
            "route",
            {
                "route_flag": route_flag,
                "branches": [branch.branch_id for branch in branches],
            },
        )
    if route_flag == "policy_not_applicable":
        emit("routing", "Requested procedure is not covered by this policy")

    results: list[BranchResult] = []
    for index, branch in enumerate(branches, start=1):
        emit(
            "branch_extraction",
            f"Extracting evidence for {branch.procedure_label}",
            index,
            len(branches),
        )
        facts = extract_facts(chart_text, branch.root, primary, chart_document)
        if tracer:
            tracer.add(
                f"facts:{branch.branch_id}",
                {k: v.model_dump(mode="json") for k, v in facts.items()},
            )

        to_verify = leaves_to_verify(branch.root, facts)
        log.info(
            "branch %s: %d fields extracted, %d pivotal field(s) to verify",
            branch.branch_id,
            len(facts),
            len(to_verify),
        )

        gap_flags: dict[str, str] = {}
        if to_verify:
            emit(
                "branch_verification",
                f"Verifying {len(to_verify)} pivotal evidence item(s)",
                index,
                len(branches),
            )
            facts, gap_flags = verify_facts(
                chart_text, branch.root, facts, to_verify, verifier, chart_document
            )
            if gap_flags:
                log.info("branch %s: verifier disagreed on %s", branch.branch_id, list(gap_flags))
            if tracer:
                tracer.add(
                    f"verified:{branch.branch_id}",
                    {
                        "gap_flags": gap_flags,
                        "facts": {k: v.model_dump(mode="json") for k, v in facts.items()},
                    },
                )

        eval_tree = evaluate(branch.root, facts)
        log.info("branch %s verdict: %s", branch.branch_id, eval_tree.status.value)
        if tracer:
            tracer.add(
                f"verdict:{branch.branch_id}",
                {
                    "verdict": eval_tree.status.value,
                    "gap_flags": gap_flags,
                    "decisive_findings": [
                        finding.model_dump(mode="json")
                        for finding in decisive_findings(branch.root, eval_tree)
                    ],
                    "eval_tree": eval_tree.model_dump(mode="json"),
                },
            )

        results.append(
            BranchResult(
                branch_id=branch.branch_id,
                procedure_label=branch.procedure_label,
                verdict=eval_tree.status,
                tree=eval_tree,
                decisive_findings=decisive_findings(branch.root, eval_tree),
                gap_flags=gap_flags,
            )
        )
        emit(
            "branch_complete",
            f"Completed {branch.procedure_label}: {eval_tree.status.value}",
            index,
            len(branches),
        )

    elapsed = time.perf_counter() - started
    log.info("run complete in %.2fs", elapsed)
    emit("complete", f"Evaluation complete in {elapsed:.1f} seconds")
    return RunResult(
        guideline_id=tree.guideline_id,
        title=tree.title,
        order=order,
        guideline_document=guideline_summary,
        chart_document=chart_summary,
        route_flag=route_flag,
        evaluated_branches=results,
        debug=tracer.as_list() if tracer else None,
    )
