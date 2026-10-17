"""Continuous accounting-integrity monitor (Phase 5).

Runs the read-only reconciliation each cycle. On a MATERIAL discrepancy it
sets an integrity lock that blocks NEW entries (the governors consult it)
while leaving open-position monitoring and protective exits fully
operational, writes an ACCOUNTING_INTEGRITY_FAILURE audit event, and
preserves all records. Clearing the lock requires an explicit reviewed note.
An accounting error must never increase available trading capital, so the
lock fails safe toward blocking entries.
"""
from __future__ import annotations

DEFAULT_MATERIAL_USD = 0.01


def check_integrity(store, cfg, reconcile_fn, now_ms: int,
                    material_threshold_usd: float = DEFAULT_MATERIAL_USD) -> dict:
    """Reconcile; if any discrepancy's $ impact is material (or impact is
    unknown, e.g. a duplicate settlement), engage the integrity lock. Returns
    the reconciliation result plus a 'locked' flag. Mutates only the lock kv
    and the audit log — never financial records."""
    report = reconcile_fn(store, cfg)
    material = []
    for d in report["discrepancies"]:
        impact = d.get("impact_usd")
        # unknown impact (duplicate settlement, invalid position) is treated as
        # material — we must not assume it is harmless
        if impact is None or impact >= material_threshold_usd:
            material.append(d)
    if material and not store.get("integrity_locked"):
        kinds = ", ".join(sorted({d["kind"] for d in material}))
        total = sum(d["impact_usd"] for d in material if d.get("impact_usd") is not None)
        reason = (f"ACCOUNTING_INTEGRITY_FAILURE: {len(material)} material "
                  f"discrepancy(ies) [{kinds}], known impact ${total:.4f}. "
                  "New entries blocked; exits and monitoring continue; manual "
                  "review + clear required.")
        store.set("integrity_locked", True)
        store.set("integrity_reason", reason)
        store.set("integrity_locked_at_ms", now_ms)
        store.audit("error", "integrity", reason, ts_ms=now_ms)
    return {"ok": not material, "locked": bool(store.get("integrity_locked")),
            "material": material, "report": report}


def clear_integrity_lock(store, note: str) -> None:
    if not note or not note.strip():
        raise ValueError("A review note is required to clear the integrity lock")
    store.set("integrity_locked", False)
    store.set("integrity_reason", None)
    store.audit("warning", "integrity",
                f"integrity lock cleared after review: '{note}'")
