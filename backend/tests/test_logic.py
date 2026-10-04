import hashlib

from app.logic import candidate_weights, select_inspector, verify_commitment, distance_meters, missing_required


def test_eligibility_and_high_risk_weights():
    users = [
        {"id": 3, "active": True, "available": True, "qualified_high_risk": False},
        {"id": 2, "active": True, "available": True, "qualified_high_risk": True},
        {"id": 1, "active": False, "available": True, "qualified_high_risk": True},
        {"id": 4, "active": True, "available": False, "qualified_high_risk": True},
    ]
    assert candidate_weights(users, "high", [3]) == [{"id": 2, "weight": 4}]
    assert candidate_weights(users, "high", []) == [{"id": 2, "weight": 4}, {"id": 3, "weight": 1}]


def test_selection_is_deterministic_and_commitment_verifies():
    seed = bytes.fromhex("ab" * 32)
    candidates = [{"id": 2, "weight": 4}, {"id": 3, "weight": 1}]
    selected = select_inspector(seed, 17, candidates, 2)
    assert selected in (2, 3)
    assert select_inspector(seed, 17, candidates, 2) == selected
    assert verify_commitment(seed.hex(), hashlib.sha256(seed).hexdigest())
    assert not verify_commitment((b"x" * 32).hex(), hashlib.sha256(seed).hexdigest())


def test_geofence_distance_and_required_answers():
    assert distance_meters(12.0, 77.0, 12.0, 77.0) == 0
    assert 1000 < distance_meters(12.0, 77.0, 12.01, 77.0) < 1200
    template = [{"key": "safety", "required": True}, {"key": "notes", "required": False}]
    assert missing_required(template, {"safety": "pass"}) == []
    assert missing_required(template, {"notes": "pass"}) == ["safety"]
