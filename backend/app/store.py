import hashlib
import os
from pathlib import Path
from typing import Optional

from .models import CriteriaTree

CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/data/guidelines"))


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def tree_path(h: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{h}.json"


def save_tree(h: str, tree: CriteriaTree) -> None:
    tree_path(h).write_text(tree.model_dump_json(indent=2))


def load_tree(h: str) -> Optional[CriteriaTree]:
    p = tree_path(h)
    return CriteriaTree.model_validate_json(p.read_text()) if p.exists() else None
