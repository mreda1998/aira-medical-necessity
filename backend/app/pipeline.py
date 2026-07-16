from pydantic import BaseModel

from .llm import LLM
from .models import Status, Order, EvalResult
from .pdf_extract import extract_text
from .compiler import compile_cached
from .router import extract_order, select_branch
from .extractor import extract_facts
from .verifier import leaves_to_verify, verify_facts
from .evaluator import evaluate


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


def run(guideline_bytes: bytes, chart_bytes: bytes, primary: LLM, verifier: LLM) -> RunResult:
    tree = compile_cached(guideline_bytes, primary)
    chart_text = extract_text(chart_bytes)
    order = extract_order(chart_text, primary)
    branches, route_flag = select_branch(order, tree)

    results: list[BranchResult] = []
    for branch in branches:
        facts = extract_facts(chart_text, branch.root, primary)
        to_verify = leaves_to_verify(branch.root, facts)
        gap_flags: dict[str, str] = {}
        if to_verify:
            facts, gap_flags = verify_facts(chart_text, branch.root, facts, to_verify, verifier)
        eval_tree = evaluate(branch.root, facts)
        results.append(BranchResult(
            branch_id=branch.branch_id, procedure_label=branch.procedure_label,
            verdict=eval_tree.status, tree=eval_tree, gap_flags=gap_flags,
        ))

    return RunResult(guideline_id=tree.guideline_id, title=tree.title, order=order,
                     route_flag=route_flag, evaluated_branches=results)
