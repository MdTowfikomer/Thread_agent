import pytest
from app.core.canonical import ChannelType, PermissionLevel, LinkVerificationType
from app.identity.service import CrossChannelIdentityService, MIN_VERIFIED_CONFIDENCE
from app.core.membership import membership_store

def test_immutable_account_id_resolution():
    service = CrossChannelIdentityService()
    
    # 1. Arjun's verified GitHub account (numeric ID 583231)
    res_github = service.resolve_identity(
        organization_id="gdg_mcet",
        channel_type=ChannelType.GITHUB,
        account_id="583231",
        username="arjun-dev"
    )
    assert res_github.person_id == "usr_arjun"
    assert res_github.is_verified is True
    assert res_github.permission_level == PermissionLevel.INTERNAL_CORE
    assert res_github.confidence == 1.0

    # 2. Arjun's verified Discord account
    res_discord = service.resolve_identity(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        account_id="discord_arjun_101",
        username="arjun_gdg"
    )
    assert res_discord.person_id == "usr_arjun"
    assert res_discord.is_verified is True
    assert res_discord.permission_level == PermissionLevel.INTERNAL_CORE

def test_strict_prohibition_of_name_based_automatic_merges():
    """
    CRITICAL SECURITY TEST:
    An external user joins GitHub with username 'arjun_gdg' or 'Arjun Sharma',
    but has an unknown account_id. The identity service MUST NEVER merge this
    external user into internal member 'usr_arjun'.
    """
    service = CrossChannelIdentityService()

    # Attacker or coincidence: external account ID is 9999999, but username matches Arjun Sharma
    unlinked_res = service.resolve_identity(
        organization_id="gdg_mcet",
        channel_type=ChannelType.GITHUB,
        account_id="9999999",
        username="arjun_gdg",
        display_name="Arjun Sharma",
        email="fake_arjun@gmail.com"
    )

    # 1. Must NOT resolve to usr_arjun
    assert unlinked_res.person_id != "usr_arjun", "MUST NOT merge unverified account based on matching name/username"
    assert unlinked_res.person_id == "ext_github_9999999"
    assert unlinked_res.is_synthetic_public is True

    # 2. Must NOT inherit core internal permissions
    assert unlinked_res.permission_level == PermissionLevel.PUBLIC_COMMUNITY
    assert unlinked_res.allowed_scopes == [PermissionLevel.PUBLIC_COMMUNITY]
    assert unlinked_res.is_verified is False
    assert unlinked_res.confidence == 0.0

    # 3. Evidence flags potential collision/spoofing
    assert unlinked_res.evidence.get("potential_name_collision") is True

def test_organization_boundaries_strictly_enforced():
    """
    Cross-organization account leakage must be strictly rejected.
    """
    service = CrossChannelIdentityService()

    # Querying Arjun's account under a different organization must NOT resolve to Arjun's gdg_mcet persona
    other_org_res = service.resolve_identity(
        organization_id="other_unrelated_org",
        channel_type=ChannelType.GITHUB,
        account_id="583231"
    )
    assert other_org_res.person_id != "usr_arjun"
    assert other_org_res.permission_level == PermissionLevel.PUBLIC_COMMUNITY

    # Attempting to link a user to an organization they do not belong to must raise ValueError
    with pytest.raises(ValueError) as exc_info:
        service.link_account(
            organization_id="other_unrelated_org",
            person_id="usr_arjun",  # Belongs to gdg_mcet
            channel_type=ChannelType.GITHUB,
            account_id="888888",
            link_type=LinkVerificationType.ORGANIZER_MANUAL
        )
    assert "Cross-organization linking rejected" in str(exc_info.value)

def test_verification_evidence_and_confidence_thresholds():
    """
    Unverified or low-confidence links must NOT inherit internal permissions.
    """
    service = CrossChannelIdentityService()

    # Link Rohan (community member) with an unverified self-claim (confidence 0.3)
    service.link_account(
        organization_id="gdg_mcet",
        person_id="usr_student_rohan",
        channel_type=ChannelType.SLACK,
        account_id="U_ROHAN_CLAIMED",
        link_type=LinkVerificationType.CLAIMED_UNVERIFIED,
        confidence=0.3,
        evidence={"claimed_in_chat": True}
    )

    res = service.resolve_identity(
        organization_id="gdg_mcet",
        channel_type=ChannelType.SLACK,
        account_id="U_ROHAN_CLAIMED"
    )
    assert res.person_id == "usr_student_rohan"
    assert res.is_verified is False
    assert res.confidence == 0.3
    assert res.permission_level == PermissionLevel.PUBLIC_COMMUNITY
