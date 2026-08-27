"""Tests for the chat engine (deterministic fallback)."""
from app import chat

ALLOWED = {"text", "kpi", "chart", "table", "map", "note"}

QUESTIONS = [
    "demand last 30 days",
    "where is the highest shortage risk this week",
    "show pending redistribution recommendations",
    "live weather at campus-01",
    "show India food context",
    "how accurate is the model",
    "show Bengaluru map",
    "show me the latest 50 data records",
    "what is the surplus situation over 90 days",
]


def test_ask_returns_contract():
    for q in QUESTIONS:
        r = chat.ask(q)
        assert isinstance(r.get("text"), str) and r["text"], q
        assert isinstance(r.get("blocks"), list), q
        for b in r["blocks"]:
            assert b.get("type") in ALLOWED, b
        assert r.get("engine"), q


def test_weather_question_emits_weather_chart():
    r = chat.ask("what is the live weather at campus-02")
    types = {b["type"] for b in r["blocks"]}
    assert "chart" in types  # weather charts rendered even if offline (error noted)


def test_unknown_question_falls_back_gracefully():
    r = chat.ask("tell me a joke about biryani")
    assert r["text"] and r["engine"] == "fallback"
