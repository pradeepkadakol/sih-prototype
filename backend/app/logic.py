"""Small, deterministic rules used by the API and its verification UI."""

import hashlib
import hmac
import json
import math


ALGORITHM = "hmac-sha256-rejection-v1"


def candidate_weights(users: list[dict], risk: str, excluded: list[int]) -> list[dict]:
    return [
        {"id": user["id"], "weight": 4 if risk == "high" and user["qualified_high_risk"] else 1}
        for user in sorted(users, key=lambda item: item["id"])
        if user["active"] and user["available"] and user["id"] not in excluded
    ]


def selection_message(case_id: int, candidates: list[dict], event_number: int, counter: int) -> bytes:
    return json.dumps(
        {"case_id": case_id, "candidates": candidates, "event_number": event_number, "counter": counter},
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def select_inspector(seed: bytes, case_id: int, candidates: list[dict], event_number: int) -> int:
    total = sum(item["weight"] for item in candidates)
    if total <= 0 or any(item["weight"] <= 0 for item in candidates):
        raise ValueError("At least one positive candidate weight is required")
    limit = (1 << 256) - ((1 << 256) % total)
    counter = 0
    while True:
        number = int.from_bytes(hmac.new(seed, selection_message(case_id, candidates, event_number, counter), hashlib.sha256).digest(), "big")
        if number < limit:
            pick = number % total
            for item in candidates:
                if pick < item["weight"]:
                    return item["id"]
                pick -= item["weight"]
        counter += 1


def verify_commitment(seed_hex: str, commitment: str) -> bool:
    try:
        return hmac.compare_digest(hashlib.sha256(bytes.fromhex(seed_hex)).hexdigest(), commitment)
    except ValueError:
        return False


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius = 6371000
    a1, a2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = a2 - a1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(dlon / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def missing_required(template: list[dict], answers: dict[str, str]) -> list[str]:
    return [item["key"] for item in template if item.get("required") and answers.get(item["key"]) not in {"pass", "fail", "na"}]
