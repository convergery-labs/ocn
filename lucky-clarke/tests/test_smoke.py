"""Smoke tests: health, Agent Card, JSON-RPC."""
import pytest


async def test_health(client):
    """GET /health returns 200 ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_agent_card(client):
    """GET /.well-known/agent.json returns valid Agent Card."""
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "lucky-clarke"
    assert card["capabilities"]["tasks"] is True


async def test_jsonrpc_tasks_send(client, mocker):
    """POST / with tasks/send returns submitted task."""
    mocker.patch(
        "routes.a2a.run_digest_async",
        return_value=None,
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tasks/send",
        "params": {},
    }
    resp = await client.post("/", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["status"]["state"] == "submitted"
    assert "id" in body["result"]


async def test_jsonrpc_unknown_method(client):
    """POST / with unknown method returns -32601."""
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "unknown/method",
        "params": {},
    }
    resp = await client.post("/", json=payload)
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32601


async def test_webhook_news_retrieval(client):
    """POST /webhook/news-retrieval returns acknowledged."""
    resp = await client.post(
        "/webhook/news-retrieval",
        json={"run_id": 1, "status": "completed"},
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True


async def test_webhook_signal_detection(client):
    """POST /webhook/signal-detection returns acknowledged."""
    resp = await client.post(
        "/webhook/signal-detection",
        json={"job_id": 42, "status": "completed"},
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True
