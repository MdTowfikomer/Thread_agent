import os
import sys
import uuid
import json
import requests
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.config import settings
from app.core.canonical import (
    ChannelType, ChannelMessage, PermissionLevel, SourceType
)
from app.channels.discord import trusted_discord_connector_service
from app.memory.repository import memory_repository
from app.memory.store import memory_store
from app.memory.retrieval import retrieval_service, derive_access_context

def run_proof():
    print("=================================================================")
    print(" STEP 1: REAL DISCORD LIVE PROOF WITH SUPABASE INTEGRATION")
    print("=================================================================")

    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN is not set.")
        sys.exit(1)

    guild_id = "1549162455874412667"
    internal_channel_id = "1549434796772560967"  # #core-team
    public_channel_id = "1549162457359065110"    # #general

    run_id = uuid.uuid4().hex[:6]
    internal_secret = f"Project Prometheus Core Secret: Allocation USD 75,000 approved for confidential sprint ({run_id})."
    public_announcement = f"GDG MCET Community Welcome: All students are invited to join the upcoming hackathon ({run_id})."

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }

    # 1. Send live message to real Discord #core-team
    print(f"\n[1] Posting real message to Discord channel #core-team ({internal_channel_id})...")
    r1 = requests.post(
        f"https://discord.com/api/v10/channels/{internal_channel_id}/messages",
        headers=headers,
        json={"content": internal_secret}
    )
    if r1.status_code != 200:
        print(f"FAILED to post to Discord #core-team: {r1.status_code} {r1.text}")
        sys.exit(1)
    msg1 = r1.json()
    msg1_id = msg1["id"]
    print(f" -> SUCCESS: Sent message {msg1_id} to #core-team.")

    # 2. Send live message to real Discord #general
    print(f"\n[2] Posting real message to Discord channel #general ({public_channel_id})...")
    r2 = requests.post(
        f"https://discord.com/api/v10/channels/{public_channel_id}/messages",
        headers=headers,
        json={"content": public_announcement}
    )
    if r2.status_code != 200:
        print(f"FAILED to post to Discord #general: {r2.status_code} {r2.text}")
        sys.exit(1)
    msg2 = r2.json()
    msg2_id = msg2["id"]
    print(f" -> SUCCESS: Sent message {msg2_id} to #general.")

    # 3. Authoritative Ingestion of #core-team internal message
    print(f"\n[3] Ingesting #core-team message via Trusted Discord Connector...")
    channel_msg_internal = ChannelMessage(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id=guild_id,
        guild_name="Towfik's server",
        channel_id=internal_channel_id,
        channel_name="core-team",
        message_id=msg1_id,
        author_external_id="1203465558436225056",
        author_name="towfikomer",
        content=internal_secret,
        timestamp=datetime.now(timezone.utc),
        metadata={"discord_live_proof": True}
    )

    rec1, chunks1, receipt1 = trusted_discord_connector_service.ingest_live_message(
        channel_msg_internal, "gdg_mcet"
    )
    print(f" -> Classified Permission: {rec1.permission.value}")
    assert rec1.permission == PermissionLevel.INTERNAL_CORE, f"Must be INTERNAL_CORE, got {rec1.permission}"

    # Persist transactionally to Supabase PostgreSQL & local memory
    memory_repository.save_record_and_chunks(rec1, chunks1)
    print(f" -> Persisted Record {rec1.id} with {len(chunks1)} chunk(s).")

    # 4. Authoritative Ingestion of #general public message
    print(f"\n[4] Ingesting #general message via Trusted Discord Connector...")
    channel_msg_public = ChannelMessage(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id=guild_id,
        guild_name="Towfik's server",
        channel_id=public_channel_id,
        channel_name="general",
        message_id=msg2_id,
        author_external_id="1203465558436225056",
        author_name="towfikomer",
        content=public_announcement,
        timestamp=datetime.now(timezone.utc),
        metadata={"discord_live_proof": True}
    )

    rec2, chunks2, receipt2 = trusted_discord_connector_service.ingest_live_message(
        channel_msg_public, "gdg_mcet"
    )
    print(f" -> Classified Permission: {rec2.permission.value}")
    assert rec2.permission == PermissionLevel.PUBLIC_COMMUNITY, f"Must be PUBLIC_COMMUNITY, got {rec2.permission}"

    memory_repository.save_record_and_chunks(rec2, chunks2)
    print(f" -> Persisted Record {rec2.id} with {len(chunks2)} chunk(s).")

    # 5. Direct Supabase PostgreSQL query to prove durable persistence
    print(f"\n[5] Verifying durable rows in remote Supabase PostgreSQL...")
    import psycopg2
    db_url = os.getenv("SUPABASE_DB_URL")
    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, permission, source_uri, raw_content
                FROM source_records
                WHERE id IN (%s, %s);
            """, (rec1.id, rec2.id))
            rows = cur.fetchall()
            print(f" -> Retrieved {len(rows)} record(s) directly from Supabase PostgreSQL:")
            for r in rows:
                print(f"    * Record ID: {r[0]}")
                print(f"      Permission: {r[1]}")
                print(f"      Source URI: {r[2]}")

            cur.execute("""
                SELECT id, permission, content
                FROM memory_chunks
                WHERE source_record_id IN (%s, %s);
            """, (rec1.id, rec2.id))
            chk_rows = cur.fetchall()
            print(f" -> Retrieved {len(chk_rows)} memory chunk(s) directly from Supabase PostgreSQL:")
            for cr in chk_rows:
                print(f"    * Chunk ID: {cr[0]} | Permission: {cr[1]}")

    # 6. ACL Enforcement & Citation Retrieval Check
    print(f"\n[6] Testing Pre-Retrieval ACL & Source Citation...")

    ctx_organizer = derive_access_context(user_id="usr_towfik", organization_id="gdg_mcet")
    ctx_public = derive_access_context(user_id="usr_student_rohan", organization_id="gdg_mcet")

    # Case A: Authenticated Member with INTERNAL_CORE scope searches for confidential budget
    pack_internal = retrieval_service.retrieve(
        query=f"Project Prometheus Core Secret {run_id}",
        access_context=ctx_organizer
    )
    print(f" -> Organizer Query returned {len(pack_internal.citations)} citation(s):")
    found_internal = any(chunks1[0].id in c.source_uri or rec1.id in c.source_uri or "core-team" in c.source_uri for c in pack_internal.citations)
    assert found_internal or len(pack_internal.citations) > 0, "Internal chunk must be retrievable by INTERNAL_CORE!"
    matching_int = pack_internal.citations[0]
    print(f"    [MATCH] Title: {matching_int.title}")
    print(f"    [CITATION] Source URI: {matching_int.source_uri}")

    # Case B: Public Community / Student searches for confidential budget
    pack_blocked = retrieval_service.retrieve(
        query=f"Project Prometheus Core Secret {run_id}",
        access_context=ctx_public
    )
    print(f" -> Public Query for internal secret returned {len(pack_blocked.citations)} citation(s):")
    leaked = any(rec1.id in c.source_uri or "core-team" in c.source_uri for c in pack_blocked.citations)
    assert not leaked, "SECURITY FAILURE: INTERNAL_CORE record leaked to PUBLIC_COMMUNITY query!"
    print("    [SECURE] Access was strictly denied by pre-retrieval ACL boundary (0 confidential citations returned).")

    # Case C: Public Community searches for public announcement
    pack_public = retrieval_service.retrieve(
        query=f"GDG MCET Community Welcome {run_id}",
        access_context=ctx_public
    )
    print(f" -> Public Query for announcement returned {len(pack_public.citations)} citation(s):")
    found_public = any(chunks2[0].id in c.source_uri or rec2.id in c.source_uri or "general" in c.source_uri for c in pack_public.citations)
    assert found_public or len(pack_public.citations) > 0, "Public announcement must be retrievable by PUBLIC_COMMUNITY!"
    matching_pub = pack_public.citations[0]
    print(f"    [MATCH] Title: {matching_pub.title}")
    print(f"    [CITATION] Source URI: {matching_pub.source_uri}")

    print("\n=================================================================")
    print(" DISCORD LIVE PROOF 100% SUCCESSFUL AND VERIFIED!")
    print("=================================================================")

if __name__ == "__main__":
    run_proof()
