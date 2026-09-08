from __future__ import annotations

from typing import Any

from .models import ConflictImpact, ConflictRecord, EnvelopeMode, GateResult, QueryEnvelope


def sufficiency_gate(
    envelopes: dict[str, QueryEnvelope],
    required: dict[str, list[str]],
    conflicts: list[ConflictRecord],
    enabled: bool = True,
) -> GateResult:
    if not enabled:
        return GateResult(
            gate="sufficiency",
            passed=True,
            enabled=False,
            reasons=["Gate desativado pela configuração experimental."],
        )

    missing: list[str] = []
    reasons: list[str] = []
    for key, fields in required.items():
        envelope = envelopes.get(key)
        if envelope is None:
            missing.append(f"source:{key}")
            continue
        if envelope.mode in {EnvelopeMode.INCONCLUSIVE, EnvelopeMode.UNAVAILABLE}:
            missing.append(f"usable:{key}")
            continue
        payload = envelope.data if isinstance(envelope.data, (dict, list)) else {}
        for field in fields:
            value = _read_path(payload, field)
            if value is None or value == "" or value == [] or value == {}:
                missing.append(f"field:{key}.{field}")
        if envelope.mode == EnvelopeMode.PARTIAL and not any(
            item.startswith(f"field:{key}.") for item in missing
        ):
            reasons.append(f"{key} é parcial, mas preserva os campos decisivos.")

    blocking = [
        conflict.topic
        for conflict in conflicts
        if not conflict.resolved and conflict.impact == "blocks_action"
    ]
    non_blocking = [
        conflict.topic
        for conflict in conflicts
        if not conflict.resolved and conflict.impact != "blocks_action"
    ]
    missing.extend(f"conflict:{topic}" for topic in blocking)
    if non_blocking:
        reasons.append(
            "Divergências não decisivas foram preservadas para exposição na resposta: "
            + ", ".join(non_blocking)
            + "."
        )
    if not missing:
        reasons.append("Todas as fontes e campos decisivos estão disponíveis.")
    return GateResult(
        gate="sufficiency", passed=not missing, reasons=reasons, missing=missing
    )


def resolve_conflict(
    topic: str,
    sources: list[str],
    *,
    same_instant: bool,
    dedicated_source: str | None,
    technical_support: str | None,
    impact: ConflictImpact = "blocks_action",
) -> ConflictRecord:
    if not same_instant:
        return ConflictRecord(
            topic=topic,
            sources=sources,
            resolved=True,
            resolution="As fontes descrevem instantes diferentes; a mais recente é aplicável.",
            rule="temporal_alignment",
            impact=impact,
        )
    if dedicated_source:
        return ConflictRecord(
            topic=topic,
            sources=sources,
            resolved=True,
            resolution=f"Fonte dedicada priorizada: {dedicated_source}.",
            rule="dedicated_endpoint",
            impact=impact,
        )
    if technical_support:
        return ConflictRecord(
            topic=topic,
            sources=sources,
            resolved=True,
            resolution=technical_support,
            rule="technical_evidence",
            impact=impact,
        )
    return ConflictRecord(
        topic=topic,
        sources=sources,
        resolved=False,
        resolution=None,
        rule="unresolved_real_divergence",
        impact=impact,
    )


def _read_path(value: Any, path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        else:
            return None
    return current
