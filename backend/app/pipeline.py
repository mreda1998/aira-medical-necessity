import logging
import time
from typing import Optional

from pydantic import BaseModel

from .llm import LLM
from .models import Status, Order, EvalResult
from .pdf_extract import extract_text
from .compiler import compile_cached
from .router import extract_order, select_branch
from .extractor import extract_facts
from .verifier import leaves_to_verify, verify_facts
from .evaluator import evaluate
from .trace import Tracer

log = logging.getLogger("aira.pipeline")


class BranchResult(BaseModel):
    branch_id: str
    procedure_label: str
    verdict: Status
    tree: EvalResult
    gap_flags: dict[str, str] = {}


class RunResult(BaseModel):
    guideline_id: str
    title: str
    order: Order
    route_flag: str | None = None
    evaluated_branches: list[BranchResult]
    # Populated only when a Tracer is passed (debug mode): the ordered
    # intermediate JSON artifacts from every pipeline step.
    debug: Optional[list] = None


def run(
    guideline_bytes: bytes,
    chart_bytes: bytes,
    primary: LLM,
    verifier: LLM,
    tracer: Optional[Tracer] = None,
) -> RunResult:
    started = time.perf_counter()

    tree = compile_cached(guideline_bytes, primary)
    log.info(
        "guideline compiled: id=%s title=%r branches=%d",
        tree.guideline_id,
        tree.title,
        len(tree.branches),
    )
    if tracer:
        tracer.add("guideline_tree", tree.model_dump(mode="json"))

    chart_text = extract_text(chart_bytes)
    log.info("chart extracted: %d chars", len(chart_text))
    if tracer:
        tracer.add("chart_text", {"chars": len(chart_text), "preview": chart_text[:3000]})

    order = extract_order(chart_text, primary)
    log.info("order extracted: %s", order.model_dump())
    if tracer:
        tracer.add("order", order.model_dump(mode="json"))

    branches, route_flag = select_branch(order, tree)
    log.info(
        "routed to %d branch(es)%s",
        len(branches),
        f" (flag={route_flag})" if route_flag else "",
    )

    results: list[BranchResult] = []
    for branch in branches:
        facts = extract_facts(chart_text, branch.root, primary)
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
            facts, gap_flags = verify_facts(chart_text, branch.root, facts, to_verify, verifier)
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
                    "eval_tree": eval_tree.model_dump(mode="json"),
                },
            )

        results.append(
            BranchResult(
                branch_id=branch.branch_id,
                procedure_label=branch.procedure_label,
                verdict=eval_tree.status,
                tree=eval_tree,
                gap_flags=gap_flags,
            )
        )

    log.info("run complete in %.2fs", time.perf_counter() - started)
    return RunResult(
        guideline_id=tree.guideline_id,
        title=tree.title,
        order=order,
        route_flag=route_flag,
        evaluated_branches=results,
        debug=tracer.as_list() if tracer else None,
    )
