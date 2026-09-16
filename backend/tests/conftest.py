import pytest
from app.core.canonical import ChannelType, PermissionLevel
from app.channels.installation import guild_installation_store
from app.channels.policy import channel_policy_store

@pytest.fixture(autouse=True)
def setup_test_channels_and_policies():
    """
    Test fixture registering standard test guilds and channel policies.
    Guarantees isolation and ensures runtime code contains ZERO hardcoded defaults.
    """
    guild_installation_store.clear()
    channel_policy_store.clear()

    # Guilds for test suites
    guild_installation_store.register_installation(
        guild_id="1549162455874412667",
        organization_id="gdg_mcet",
        guild_name="GDG MCET Discord"
    )
    guild_installation_store.register_installation(
        guild_id="11223344",
        organization_id="gdg_mcet",
        guild_name="GDG MCET Discord Test"
    )

    # Test channel policies for guild 11223344
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="11223344",
        channel_id="99001122",
        channel_name="core-team",
        permission_scope=PermissionLevel.INTERNAL_CORE
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="11223344",
        channel_id="77889900",
        channel_name="organizers-budget",
        permission_scope=PermissionLevel.INTERNAL_CORE
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="11223344",
        channel_id="55667788",
        channel_name="general",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="11223344",
        channel_id="11112222",
        channel_name="general-help",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="11223344",
        channel_id="33445566",
        channel_name="announcements",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )

    # Test channel policies for guild 1549162455874412667
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="1549162455874412667",
        channel_id="1549434796772560967",
        channel_name="core-team",
        permission_scope=PermissionLevel.INTERNAL_CORE
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="1549162455874412667",
        channel_id="1549434872584474735",
        channel_name="organizers",
        permission_scope=PermissionLevel.INTERNAL_CORE
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="1549162455874412667",
        channel_id="1549162457359065110",
        channel_name="general",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="1549162455874412667",
        channel_id="1549434693735157820",
        channel_name="public_community",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )

    # Test channel policy for Slack
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.SLACK,
        guild_id="T0C21JVKS49",
        channel_id="C0C21QPFB6E",
        channel_name="general",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )

    yield

    guild_installation_store.clear()
    channel_policy_store.clear()
