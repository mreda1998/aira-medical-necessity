from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel


class Status(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


class PredicateType(str, Enum):
    BOOLEAN = "boolean"
    NUMERIC_GTE = "numeric_gte"
    NUMERIC_LTE = "numeric_lte"
    ORDINAL_GTE = "ordinal_gte"
    DURATION_GTE = "duration_gte"
    EXISTENCE = "existence"


class SourceSpan(BaseModel):
    text: str
    page: Optional[int] = None


class LeafNode(BaseModel):
    kind: Literal["leaf"] = "leaf"
    id: str
    predicate: PredicateType
    field: str
    threshold: Optional[Union[float, str, bool]] = None
    unit: Optional[str] = None
    negated: bool = False
    human_readable: str
    source_span: Optional[SourceSpan] = None
    parse_confidence: float = 1.0


class UnmappableNode(BaseModel):
    kind: Literal["unmappable"] = "unmappable"
    id: str
    human_readable: str
    reason: str = ""
    source_span: Optional[SourceSpan] = None


class AllOf(BaseModel):
    kind: Literal["all_of"] = "all_of"
    id: str
    children: list["Node"]


class AnyOf(BaseModel):
    kind: Literal["any_of"] = "any_of"
    id: str
    children: list["Node"]


class NOf(BaseModel):
    kind: Literal["n_of"] = "n_of"
    id: str
    k: int
    children: list["Node"]


Node = Union[AllOf, AnyOf, NOf, LeafNode, UnmappableNode]


class CriteriaBranch(BaseModel):
    branch_id: str
    vein_types: list[str]
    procedure_label: str
    root: Node


class CriteriaTree(BaseModel):
    guideline_id: str
    title: str
    branches: list[CriteriaBranch]


class Fact(BaseModel):
    field: str
    value: Optional[Union[float, str, bool]] = None
    unit: Optional[str] = None
    found: bool = False
    source_span: Optional[SourceSpan] = None
    confidence: float = 1.0


class Order(BaseModel):
    modality: Optional[str] = None
    vein: Optional[str] = None
    laterality: Optional[str] = None
    cpt: Optional[str] = None
    raw: Optional[str] = None


class EvalResult(BaseModel):
    node_id: str
    kind: str
    status: Status
    human_readable: Optional[str] = None
    field: Optional[str] = None
    evidence: Optional[Fact] = None
    guideline_span: Optional[SourceSpan] = None
    flags: list[str] = []
    children: list["EvalResult"] = []


for _m in (AllOf, AnyOf, NOf, CriteriaBranch, EvalResult):
    _m.model_rebuild()
