import pytest

from src.agents.nodes.reasoning import evaluate_triage_severity


def test_triage_critical_fall():
    res = evaluate_triage_severity(
        incident_type="fall",
        ai_confidence=0.92,
        posture="lying",
        immobility_duration_ms=5000,
        location="Phòng khách",
    )
    assert res["threat_level"] == "CRITICAL"
    assert res["severity"] == "critical"
    assert res["verdict"] == "CONFIRMED_ALERT"
    assert "NGUY CẤP" in res["reasoning"]


def test_triage_high_fall():
    res = evaluate_triage_severity(
        incident_type="fall",
        ai_confidence=0.88,
        posture="lying",
        immobility_duration_ms=1000,
        location="Phòng ngủ",
    )
    assert res["threat_level"] == "HIGH"
    assert res["severity"] == "high"


def test_triage_stranger_frequent():
    res = evaluate_triage_severity(
        incident_type="unknown_person",
        occurrence_count=6,
        location="Sân trước",
    )
    assert res["threat_level"] == "HIGH"
    assert "liên tục" in res["reasoning"]


def test_triage_known_person_suppression():
    res = evaluate_triage_severity(
        incident_type="unknown_person",
        occurrence_count=2,
        location="Cổng",
        is_known_person=True,
    )
    assert res["threat_level"] == "LOW"
    assert res["verdict"] == "DUPLICATE"
    assert "người thân" in res["reasoning"]
