from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class Status(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


class PredicateType(str, Enum):
    BOOLEAN = "boolean"
    NUMERIC_GT = "numeric_gt"
    NUMERIC_GTE = "numeric_gte"
    NUMERIC_LT = "numeric_lt"
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


Node = Annotated[
    Union[AllOf, AnyOf, NOf, LeafNode, UnmappableNode],
    Field(discriminator="kind"),
]


class CriteriaBranch(BaseModel):
    branch_id: str
    # Generic applicability metadata used by the deterministic router. The
    # legacy vein field remains for the original vascular policy.
    procedure_codes: list[str] = Field(default_factory=list)
    procedure_aliases: list[str] = Field(default_factory=list)
    min_age: Optional[float] = None
    max_age: Optional[float] = None
    vein_types: list[str] = Field(default_factory=list)
    procedure_label: str
    root: Node


class CriteriaTree(BaseModel):
    guideline_id: str
    title: str
    branches: list[CriteriaBranch]


class EvidenceState(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    EXPLICITLY_ABSENT = "EXPLICITLY_ABSENT"
    NOT_DOCUMENTED = "NOT_DOCUMENTED"
    CONFLICTING = "CONFLICTING"


class Fact(BaseModel):
    field: str
    value: Optional[Union[float, str, bool]] = None
    unit: Optional[str] = None
    state: EvidenceState = EvidenceState.NOT_DOCUMENTED
    # Backwards-compatible projection for the API and older cached/mock data.
    # New extraction output should set ``state`` and let this value be derived.
    found: bool = False
    source_span: Optional[SourceSpan] = None
    confidence: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def normalize_evidence_state(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        raw_state = values.get("state")
        if raw_state is None:
            if not values.get("found", False):
                raw_state = EvidenceState.NOT_DOCUMENTED.value
            else:
                value = values.get("value")
                denied = value is False or (
                    isinstance(value, str)
                    and value.strip().lower()
                    in {"false", "no", "absent", "denied", "none", "negative", "0"}
                )
                raw_state = (
                    EvidenceState.EXPLICITLY_ABSENT.value
                    if denied
                    else EvidenceState.DOCUMENTED.value
                )
        state_value = raw_state.value if isinstance(raw_state, EvidenceState) else str(raw_state)
        values["state"] = state_value
        values["found"] = state_value in {
            EvidenceState.DOCUMENTED.value,
            EvidenceState.EXPLICITLY_ABSENT.value,
        }
        if state_value == EvidenceState.EXPLICITLY_ABSENT.value and values.get("value") is None:
            values["value"] = False
        if state_value == EvidenceState.NOT_DOCUMENTED.value:
            values["value"] = None
        return values


class Order(BaseModel):
    modality: Optional[str] = None
    vein: Optional[str] = None
    laterality: Optional[str] = None
    cpt: Optional[str] = None
    raw: Optional[str] = None
    patient_age: Optional[float] = None


class EvalResult(BaseModel):
    node_id: str
    kind: str
    status: Status
    human_readable: Optional[str] = None
    field: Optional[str] = None
    evidence: Optional[Fact] = None
    guideline_span: Optional[SourceSpan] = None
    flags: list[str] = Field(default_factory=list)
    children: list["EvalResult"] = Field(default_factory=list)


for _m in (AllOf, AnyOf, NOf, CriteriaBranch, EvalResult):
    _m.model_rebuild()
