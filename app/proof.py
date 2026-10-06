"""Pick one proof point whose tags match the company and whose tech they do not already run."""

from __future__ import annotations

from app.config_loader import proof_library


def select_proof(tags: list[str], avoid: list[str] | None = None, library: list[dict] | None = None) -> dict:
    library = library or proof_library()
    if not library:
        raise RuntimeError("Proof-point library is empty.")
    avoid_set = {item.lower() for item in (avoid or [])}
    tag_set = {item.lower() for item in tags}
    ranked = []
    for proof in library:
        pitch = {item.lower() for item in proof.get("pitch") or []}
        blocked = bool(pitch & avoid_set)
        overlap = len(tag_set & {item.lower() for item in proof.get("tags") or []})
        ranked.append((blocked, -overlap, int(proof.get("order") or 99), proof))
    ranked.sort(key=lambda item: item[:3])
    chosen = dict(ranked[0][3])
    chosen["blocked_by_existing_tech"] = ranked[0][0]
    return chosen


def proof_by_id(proof_id: str, library: list[dict] | None = None) -> dict | None:
    for proof in library or proof_library():
        if proof.get("id") == proof_id:
            return proof
    return None
