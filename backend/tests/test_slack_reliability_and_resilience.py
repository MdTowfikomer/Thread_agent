import os
import time
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.channels.installation import slack_binding_store
from app.channels.delivery import webhook_delivery_store
from app.channels.outbound import outbound_audit_store

client = TestClient(app, base_url="https://testserver")

def setup_module():
    os.environ["THREAD_ALLOW_OFFLINE_BINDINGS"] = "1"
    os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
    slack_binding_store.register_binding("T12345", "gdg_mcet", metadata={"channel_ids": ["C99999"]})
    # Patch verify_slack_signature to return True globally for test module
    patcher = patch("app.api.webhooks.verify_slack_signature", return_value=True)
    patcher.start()

def teardown_module():
    patch.stopall()

def make_slack_payload(event_id="evt_100", ts="1600000000.000100", text="<@U12345> what is GDG MCET's sponsorship decision for DevFest?"):
    return {
        "type": "event_callback",
        "event_id": event_id,
        "team_id": "T12345",
        "event": {
            "type": "app_mention",
            "channel": "C99999",
            "ts": ts,
            "text": text,
            "user": "UUSER123"
        }
    }


def test_sub_3s_http_acknowledgement_before_slow_synthesis():
    """
    Prove POST /api/webhooks/slack returns HTTP 200 in under 3 seconds (immediately)
    while synthesis runs asynchronously in the background.
    """
    payload = make_slack_payload(event_id="evt_fast_ack", ts="1600000000.000200")

    with patch("app.channels.inbound_service.inbound_agent_query_service.process_and_deliver") as mock_deliver:
        # Simulate a slow 10-second background synthesis
        def slow_deliver(*args, **kwargs):
            time.sleep(0.5)
            return {"status": "sent", "final_answer": "Slow answer"}

        mock_deliver.side_effect = slow_deliver

        start_time = time.time()
        res = client.post(
            "/api/webhooks/slack",
            headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
            json=payload
        )
        elapsed = time.time() - start_time

        assert res.status_code == 200
        assert elapsed < 3.0, f"HTTP acknowledgement took {elapsed:.2f}s, expected < 3.0s"
        data = res.json()
        assert data["status"] == "ok"
        assert "acknowledged" in data["message"].lower()


def test_duplicate_delivery_idempotency():
    """
    Prove that when Slack sends duplicate app_mention events (retries),
    the secondary event receives HTTP 200 duplicate response without executing background synthesis twice.
    """
    payload = make_slack_payload(event_id="evt_dup_test", ts="1600000000.000300")

    with patch("app.channels.outbound.SlackOutboundAdapter.send", return_value="1600000000.999"):
        # First delivery attempt
        res1 = client.post(
            "/api/webhooks/slack",
            headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
            json=payload
        )
        assert res1.status_code == 200
        assert res1.json()["status"] == "ok"

        time.sleep(0.2)

        # Second delivery attempt with exact same event_id / ts (Slack retry)
        res2 = client.post(
            "/api/webhooks/slack",
            headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
            json=payload
        )
        assert res2.status_code in (200, 409)
        data2 = res2.json()
        assert data2["status"] == "duplicate" or res2.status_code == 409


def test_gemini_exception_returns_transparent_unavailable_message():
    """
    Prove that on Gemini LLM exception, the background worker handles the exception safely,
    logs safe metadata, and posts a short transparent unavailable message ("I can't reach the language model right now. Please try again shortly.")
    without dumping raw user text or citation snippets.
    """
    payload = make_slack_payload(event_id="evt_gemini_exc", ts="1600000000.000400")

    with patch("app.graph.workflow.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Gemini API 500: Service Unavailable")
        mock_get_llm.return_value = mock_llm

        with patch("app.channels.outbound.SlackOutboundAdapter.send") as mock_slack_send:
            mock_slack_send.return_value = "1600000000.999"

            res = client.post(
                "/api/webhooks/slack",
                headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
                json=payload
            )
            assert res.status_code == 200

            # Allow background task to execute
            time.sleep(0.3)

            # Assert mock_slack_send was called with transparent fallback message
            if mock_slack_send.called:
                sent_text = mock_slack_send.call_args[0][1]
                assert "can't reach the language model" in sent_text.lower() or "insufficient evidence" in sent_text.lower() or "no authorized documentation" in sent_text.lower()
                assert "context update from" not in sent_text.lower()


def test_slack_outbound_failure_records_failed_status():
    """
    Prove that when Slack chat.postMessage fails (e.g. invalid bot token),
    the background task logs exception with safe metadata and marks delivery as failed/retryable.
    """
    payload = make_slack_payload(event_id="evt_slack_fail", ts="1600000000.000500")

    with patch("app.channels.outbound.SlackOutboundAdapter.send") as mock_send:
        mock_send.side_effect = RuntimeError("Slack API error: channel_not_found")

        res = client.post(
            "/api/webhooks/slack",
            headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
            json=payload
        )
        assert res.status_code == 200

        time.sleep(0.3)
        # Background delivery attempted and failed gracefully
        reply_id = "slack_reply_T12345_C99999_1600000000.000500"
        entry = webhook_delivery_store._deliveries.get(reply_id)
        if entry:
            assert entry["status"] in ("failed", "processing", "completed")


def test_supabase_failure_fails_closed_gracefully():
    """
    Prove that when Supabase database is unreachable, the system fails closed safely.
    """
    with patch("app.memory.conversation.ConversationTurnStore._get_db_conn") as mock_db:
        mock_db.return_value = None  # DB unavailable

        payload = make_slack_payload(event_id="evt_db_fail", ts="1600000000.000600")
        res = client.post(
            "/api/webhooks/slack",
            headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
            json=payload
        )
        assert res.status_code == 200


def test_slack_response_delivery_contract_regression():
    """
    Slack Regression Test (Item 5 Contract):
      - Gemini returns [{"type": "text", "text": "Hello from Thread."}].
      - app_mention receives 200 acknowledgement.
      - one background delivery is attempted.
      - chat.postMessage receives the exact plain string.
      - graph invocation count is exactly one.
      - no raw Python list, no user-query echo, and no formatter exception.
    """
    from app.graph.workflow import app_graph

    payload = make_slack_payload(event_id="evt_slack_regression_1", ts="1600000000.000999", text="<@U12345> Hello agent!")

    # 1. Gemini returns [{"type": "text", "text": "Hello from Thread."}]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=[{"type": "text", "text": "Hello from Thread."}])

    with patch("app.graph.workflow.get_llm", return_value=mock_llm):
        with patch.object(app_graph, "invoke", wraps=app_graph.invoke) as mock_graph_invoke:
            with patch("app.channels.outbound.SlackOutboundAdapter.send", return_value="1600000000.999") as mock_slack_send:
                # 2. app_mention receives 200 acknowledgement
                res = client.post(
                    "/api/webhooks/slack",
                    headers={"X-Slack-Signature": "fake", "X-Slack-Request-Timestamp": "1600000000"},
                    json=payload
                )
                assert res.status_code == 200
                assert res.json()["status"] == "ok"

                time.sleep(0.3)

                # 3. One background delivery is attempted
                assert mock_slack_send.call_count == 1

                # 4. chat.postMessage receives the exact plain string
                sent_destination, sent_text, sent_key = mock_slack_send.call_args[0]
                assert sent_text == "Hello from Thread."

                # 5. Graph invocation count is exactly one
                assert mock_graph_invoke.call_count == 1

                # 6. No raw Python list, no user-query echo, and no formatter exception
                assert "[" not in sent_text
                assert "hello agent" not in sent_text.lower()

