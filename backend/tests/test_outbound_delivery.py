from types import SimpleNamespace

import pytest

from app.channels.outbound import ChannelMessageDeliveryService, OutboundAuditStore, OutboundProviderError
from app.core.canonical import AccessContext, ChannelType, PermissionLevel, SourceType


def principal():
    return SimpleNamespace(
        user_id="user-1",
        organization_id="org-1",
        access_context=AccessContext(
            user_id="user-1",
            organization_id="org-1",
            role_id="role-1",
            user_permission=PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY],
        ),
    )


def evidence(sufficient=True):
    citation = SimpleNamespace(
        item_id="item-1",
        source=SourceType.SLACK,
        source_uri="slack://workspace/channel/event",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        relevance_score=0.9,
    )
    receipt = SimpleNamespace(receipt_id="receipt-1")
    return SimpleNamespace(sufficient_evidence=sufficient, citations=[citation] if sufficient else [], receipt=receipt)


def test_insufficient_evidence_never_sends(monkeypatch):
    service = ChannelMessageDeliveryService(OutboundAuditStore())
    monkeypatch.setattr("app.channels.outbound.app_graph", SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence(False)}))
    adapter = SimpleNamespace(send=lambda *args: pytest.fail("provider must not be called"))
    service.adapters[ChannelType.SLACK] = adapter

    result = service.send_message(principal(), ChannelType.SLACK, "C1", "private question")

    assert result["status"] == "insufficient_evidence"


def test_binding_and_acl_are_resolved_before_provider(monkeypatch):
    service = ChannelMessageDeliveryService(OutboundAuditStore())
    monkeypatch.setattr("app.channels.outbound.app_graph", SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence()}))
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: (_ for _ in ()).throw(PermissionError("not bound")))
    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=lambda *args: pytest.fail("provider must not be called"))

    with pytest.raises(PermissionError):
        service.send_message(principal(), ChannelType.SLACK, "C1", "question")


def test_duplicate_idempotency_does_not_send_twice(monkeypatch):
    service = ChannelMessageDeliveryService(OutboundAuditStore())
    monkeypatch.setattr("app.channels.outbound.app_graph", SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence(), "final_answer": "grounded answer"}))
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"channel_id": "C1", "team_id": "T1"})
    calls = []
    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=lambda *args: calls.append(args) or "ts-1")

    first = service.send_message(principal(), ChannelType.SLACK, "C1", "question", "same-key")
    second = service.send_message(principal(), ChannelType.SLACK, "C1", "question", "same-key")

    assert first["status"] == "sent"
    assert second["status"] == "duplicate"
    assert len(calls) == 1


def test_provider_failure_is_recorded_and_not_retried_as_duplicate(monkeypatch):
    store = OutboundAuditStore()
    service = ChannelMessageDeliveryService(store)
    monkeypatch.setattr("app.channels.outbound.app_graph", SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence(), "final_answer": "answer"}))
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"chat_id": "-1"})
    service.adapters[ChannelType.TELEGRAM] = SimpleNamespace(send=lambda *args: (_ for _ in ()).throw(OutboundProviderError("denied")))

    with pytest.raises(OutboundProviderError):
        service.send_message(principal(), ChannelType.TELEGRAM, "-1", "question", "failed-key")

    assert store._rows["failed-key"]["delivery_status"] == "failed"


def test_public_destination_acl_rejects_internal_evidence(monkeypatch):
    from app.channels.policy import channel_policy_store
    channel_policy_store.register_policy(
        organization_id="org-1",
        channel_type=ChannelType.SLACK,
        channel_id="C_PUB",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY,
        guild_id="T1",
    )
    service = ChannelMessageDeliveryService(OutboundAuditStore())
    internal_citation = SimpleNamespace(
        item_id="item-internal",
        source=SourceType.SLACK,
        source_uri="slack://T1/C_PUB/p1",
        permission=PermissionLevel.INTERNAL_CORE,
        relevance_score=0.95,
    )
    receipt = SimpleNamespace(receipt_id="rcpt-int")
    evidence_pack = SimpleNamespace(
        sufficient_evidence=True,
        citations=[internal_citation],
        receipt=receipt,
    )
    monkeypatch.setattr(
        "app.channels.outbound.app_graph",
        SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence_pack, "final_answer": "confidential answer"})
    )
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"channel_id": "C_PUB", "team_id": "T1"})
    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=lambda *args: pytest.fail("provider must NEVER be called"))

    with pytest.raises(PermissionError) as exc_info:
        service.send_message(principal(), ChannelType.SLACK, "C_PUB", "confidential question")
    assert "PUBLIC_COMMUNITY but evidence contains 'INTERNAL_CORE'" in str(exc_info.value)


def test_public_destination_acl_rejects_pending_review_evidence(monkeypatch):
    service = ChannelMessageDeliveryService(OutboundAuditStore())
    quarantine_citation = SimpleNamespace(
        item_id="item-quarantine",
        source=SourceType.SLACK,
        source_uri="slack://T1/C_PUB/p1",
        permission=PermissionLevel.PENDING_REVIEW,
        relevance_score=0.9,
    )
    receipt = SimpleNamespace(receipt_id="rcpt-quarantine")
    evidence_pack = SimpleNamespace(
        sufficient_evidence=True,
        citations=[quarantine_citation],
        receipt=receipt,
    )
    monkeypatch.setattr(
        "app.channels.outbound.app_graph",
        SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence_pack, "final_answer": "quarantined answer"})
    )
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"channel_id": "C_PUB", "team_id": "T1"})
    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=lambda *args: pytest.fail("provider must NEVER be called"))

    with pytest.raises(PermissionError) as exc_info:
        service.send_message(principal(), ChannelType.SLACK, "C_PUB", "quarantine question")
    assert "PENDING_REVIEW permission is never sendable" in str(exc_info.value)


def test_idempotency_keys_scoped_across_users_and_destinations(monkeypatch):
    service = ChannelMessageDeliveryService(OutboundAuditStore())
    monkeypatch.setattr(
        "app.channels.outbound.app_graph",
        SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence(), "final_answer": "grounded answer"})
    )
    monkeypatch.setattr(service, "_resolve_destination", lambda plat, dest, org: {"channel_id": dest, "team_id": "T1"})
    calls = []
    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=lambda dest, txt, key: calls.append((dest["channel_id"], key)) or f"ts-{len(calls)}")

    p1 = principal()
    p2 = SimpleNamespace(
        user_id="user-2",
        organization_id="org-1",
        access_context=AccessContext(
            user_id="user-2",
            organization_id="org-1",
            role_id="role-1",
            user_permission=PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY],
        ),
    )

    # User 1 to Channel 1 with "shared-key"
    r1 = service.send_message(p1, ChannelType.SLACK, "C1", "question", "shared-key")
    assert r1["status"] == "sent"

    # User 2 to Channel 1 with the same "shared-key" -> must NOT collide or be duplicate!
    r2 = service.send_message(p2, ChannelType.SLACK, "C1", "question", "shared-key")
    assert r2["status"] == "sent"

    # User 1 to Channel 2 with "shared-key" -> must NOT collide with Channel 1!
    r3 = service.send_message(p1, ChannelType.SLACK, "C2", "question", "shared-key")
    assert r3["status"] == "sent"

    # User 1 to Channel 1 with "shared-key" again -> DUPLICATE!
    r4 = service.send_message(p1, ChannelType.SLACK, "C1", "question", "shared-key")
    assert r4["status"] == "duplicate"
    assert len(calls) == 3


def test_ambiguous_provider_timeout_records_unknown_and_blocks_automatic_duplicate_posts(monkeypatch):
    from app.channels.outbound import OutboundTimeoutError
    store = OutboundAuditStore()
    service = ChannelMessageDeliveryService(store)
    monkeypatch.setattr(
        "app.channels.outbound.app_graph",
        SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence(), "final_answer": "timeout answer"})
    )
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"channel_id": "C1", "team_id": "T1"})

    send_calls = []

    def timeout_send(*args):
        send_calls.append(args)
        raise OutboundTimeoutError("Provider request timed out ambiguously")

    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=timeout_send)

    # First call times out
    with pytest.raises(OutboundTimeoutError):
        service.send_message(principal(), ChannelType.SLACK, "C1", "question", "timeout-key")

    assert len(send_calls) == 1
    assert store._rows["timeout-key"]["delivery_status"] == "unknown"

    # Re-post attempt with same idempotency key must NOT automatically re-call provider
    retry_result = service.send_message(principal(), ChannelType.SLACK, "C1", "question", "timeout-key")
    assert retry_result["status"] == "unknown"
    assert len(send_calls) == 1  # Provider was NOT called a second time!


def test_failed_sends_allow_controlled_retry(monkeypatch):
    store = OutboundAuditStore()
    service = ChannelMessageDeliveryService(store)
    monkeypatch.setattr(
        "app.channels.outbound.app_graph",
        SimpleNamespace(invoke=lambda state: {"evidence_pack": evidence(), "final_answer": "retry answer"})
    )
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"channel_id": "C1", "team_id": "T1"})

    calls = {"count": 0}

    def flaky_send(*args):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OutboundProviderError("transient upstream 500")
        return "ts-recovered"

    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=flaky_send)

    # Attempt 1 fails
    with pytest.raises(OutboundProviderError):
        service.send_message(principal(), ChannelType.SLACK, "C1", "question", "retry-key")

    assert store._rows["retry-key"]["delivery_status"] == "failed"

    # Controlled retry attempt succeeds
    recovered = service.send_message(principal(), ChannelType.SLACK, "C1", "question", "retry-key")
    assert recovered["status"] == "sent"
    assert recovered["provider_response_id"] == "ts-recovered"
    assert store._rows["retry-key"]["delivery_status"] == "sent"

