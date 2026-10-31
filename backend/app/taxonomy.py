"""Contract taxonomy validation without promoting noisy outcome labels to ground truth."""
import json
from pathlib import Path

from .schemas import Category

MANDATORY_HUMAN = {"report.account", "report.payment", "complaint.admin"}


def load_taxonomy(path: str | None) -> dict:
    if not path:
        return {"version": "brief-contract-baseline", "source": "built_in_contract_codes",
                "mandatory_human": MANDATORY_HUMAN, "draft": True, "rule_categories": {}}
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("Taxonomy file exceeds 2 MB")
    data = json.loads(raw)
    categories = {c["code"] for c in data["categories"]}
    priorities = {p["code"] for p in data["priorities"]}
    if categories != {c.value for c in Category} or priorities != {"p0", "p1", "p2", "p3"}:
        raise ValueError("Taxonomy codes do not match the supported HTTP contract; update schema explicitly")
    configured = set(data.get("needs_human_always", []))
    if not configured.issubset(categories):
        raise ValueError("Unknown category in needs_human_always")
    # Rule refs the taxonomy ties to each category: a hint for "2.1 ОП"-only complaints.
    rule_categories: dict[str, set[str]] = {}
    for category in data["categories"]:
        for ref in category.get("rules", []):
            rule_categories.setdefault(str(ref).strip(), set()).add(category["code"])
    return {"version": str(data.get("version", "unspecified")), "source": "private_taxonomy_file",
            "mandatory_human": MANDATORY_HUMAN | configured,
            "draft": "draft" in str(data.get("version", "")).lower(), "rule_categories": rule_categories}
