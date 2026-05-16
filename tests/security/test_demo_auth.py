from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_missing_demo_user_header_rejects_documents():
    response = TestClient(app).get("/api/documents")

    assert response.status_code == 403


def test_missing_demo_user_header_rejects_referral_analysis():
    response = TestClient(app).post("/api/referrals/analyze/missing-document")

    assert response.status_code == 403


def test_missing_demo_user_header_rejects_guideline_chat():
    response = TestClient(app).post("/api/guidelines/chat", json={"question": "Wie beantrage ich KIS?"})

    assert response.status_code == 403


def test_health_remains_public_without_demo_user_header():
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
