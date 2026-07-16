import re
from typing import Optional

CEAP_ORDER = ["C0", "C1", "C2", "C2R", "C3", "C4A", "C4B", "C4C", "C5", "C6", "C6R"]


def _ceap_rank(v: str) -> int:
    key = v.strip().upper().rstrip("SA")  # drop trailing symptomatic/asymptomatic marker
    if key not in CEAP_ORDER:
        # tolerate C4 without subletter by mapping to C4A
        if key == "C4":
            key = "C4A"
        else:
            raise ValueError(f"unknown CEAP class: {v!r}")
    return CEAP_ORDER.index(key)


def compare_ordinal(a: str, b: str) -> int:
    ra, rb = _ceap_rank(a), _ceap_rank(b)
    return (ra > rb) - (ra < rb)


def parse_measurement(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", value)
    if not nums:
        return None
    return min(float(n) for n in nums)  # lower bound = conservative


_VEIN_SYNONYMS = {
    "great_saphenous": ["gsv", "great saphenous", "long saphenous", "large saphenous"],
    "small_saphenous": ["ssv", "small saphenous", "short saphenous", "lesser saphenous"],
    "accessory_saphenous": ["asv", "accessory saphenous", "anterior accessory saphenous"],
    "perforator": ["perforator", "perforating vein"],
    "tributary": ["tributary", "varicose tributary"],
}


def canonical_vein(name: str) -> Optional[str]:
    n = name.strip().lower().replace(" vein", "")
    for canon, syns in _VEIN_SYNONYMS.items():
        for s in syns:
            if s.replace(" vein", "") in n:
                return canon
    return None
