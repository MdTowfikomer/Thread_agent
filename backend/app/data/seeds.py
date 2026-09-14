from datetime import datetime, timezone, timedelta
from typing import List, Tuple
from app.core.canonical import (
    SourceRecord,
    MemoryChunk,
    IngestionReceipt,
    SourceType,
    PermissionLevel
)
from app.memory.adapters import get_source_adapter

def get_seed_data(organization_id: str = "gdg_mcet") -> Tuple[List[SourceRecord], List[MemoryChunk], List[IngestionReceipt]]:
    now = datetime.now(timezone.utc)
    
    raw_items = [
        # Item 1: Discord Announcement (Public Community)
        {
            "source_type": SourceType.DISCORD,
            "source_uri": "https://discord.com/channels/gdg-mcet/announcements/101",
            "author": "Arjun Sharma",
            "author_role": "Lead Organizer",
            "timestamp": now - timedelta(days=2),
            "title": "DevFest 2026 Date & College Auditorium Approval",
            "content": "Official Update: Principal and Dean have formally approved the Main Mechanical Auditorium for DevFest MCET 2026 on October 24th! Capacity is 450 seats. Audio-visual setup is scheduled for check on Oct 23rd evening. Keynote speaker confirmation is in progress.",
            "permission": PermissionLevel.PUBLIC_COMMUNITY,
            "tags": ["devfest", "venue", "announcement", "auditorium", "dates"],
            "entities": {"event": "DevFest 2026", "date": "2026-10-24", "capacity": 450, "location": "Main Auditorium"},
            "metadata": {"channel": "announcements", "message_id": "disc_101"}
        },
        # Item 2: GitHub Repository (Public Community)
        {
            "source_type": SourceType.GITHUB,
            "source_uri": "https://github.com/gdg-mcet/genai-starter-kit",
            "author": "Priya Ramesh",
            "author_role": "Tech Lead",
            "timestamp": now - timedelta(days=1),
            "title": "GenAI Hands-On Codelab Repository & Prerequisites",
            "content": "For the upcoming Saturday Hands-on GenAI Workshop: Students must have Python 3.10+ installed and a Google Cloud account ready. We will be building Gemini agents and RAG pipelines using LangGraph. Clone the starter repository: github.com/gdg-mcet/genai-starter-kit. The repo contains pre-configured notebooks and sample datasets.",
            "permission": PermissionLevel.PUBLIC_COMMUNITY,
            "tags": ["genai", "workshop", "github", "prerequisites", "python", "gemini"],
            "entities": {"repo": "https://github.com/gdg-mcet/genai-starter-kit", "topic": "GenAI Workshop", "requirements": "Python 3.10+, Google Cloud"},
            "metadata": {"repo_name": "genai-starter-kit", "default_branch": "main"}
        },
        # Item 3: Google Drive Spreadsheet (Confidential Internal Core)
        {
            "source_type": SourceType.GDRIVE,
            "source_uri": "https://docs.google.com/spreadsheets/d/gdg-mcet-budget-2026",
            "author": "Karthik Verma",
            "author_role": "Sponsorship & Finance Lead",
            "timestamp": now - timedelta(days=3),
            "title": "DevFest & Workshop Internal Budget Allocation 2026",
            "content": "CONFIDENTIAL CORE TEAM: Total sanctioned budget for DevFest and Fall workshops is ₹55,000. Allocation: ₹22,000 for attendee t-shirts and holographic sticker packs (Vendor: PrintWear Co, quote accepted), ₹18,000 for speaker travel honorarium and lunch catering, ₹10,000 reserved for emergency Wi-Fi hotspot dongles, ₹5,000 buffer. Current cash in hand from sponsor ZetaTech is ₹30,000.",
            "permission": PermissionLevel.INTERNAL_CORE,
            "tags": ["budget", "finance", "sponsorship", "swag", "vendor", "confidential", "cost"],
            "entities": {"total_budget": 55000, "swag_vendor": "PrintWear Co", "sponsor": "ZetaTech", "cash_in_hand": 30000},
            "metadata": {"sheet_name": "Summary_2026", "file_type": "spreadsheet"}
        },
        # Item 4: Notion Rolodex (Confidential Internal Core)
        {
            "source_type": SourceType.NOTION,
            "source_uri": "https://notion.so/gdg-mcet/speaker-database-v2",
            "author": "Arjun Sharma",
            "author_role": "Lead Organizer",
            "timestamp": now - timedelta(days=5),
            "title": "Speaker Directory & Handover Relationship Log",
            "content": "Speaker Rolodex: 1) Dr. S. Raman (Google Developer Expert - Cloud), contact: s.raman@gde.dev, prefers morning keynotes, needs HDMI adapter. 2) Ananya Basu (Staff AI Engineer, Bengaluru), contact: ananya.b@techcorp.io, agreed for GenAI panel. 3) Rahul K. (Open Source Maintainer), contact: rahul@foss.in, requested student project showcase slot.",
            "permission": PermissionLevel.INTERNAL_CORE,
            "tags": ["speakers", "gde", "handover", "contacts", "organizer"],
            "entities": {"speakers": ["Dr. S. Raman", "Ananya Basu", "Rahul K."]},
            "metadata": {"database_id": "notion_spk_002"}
        },
        # Item 5: Discord Announcement (Public Community)
        {
            "source_type": SourceType.DISCORD,
            "source_uri": "https://discord.com/channels/gdg-mcet/general/502",
            "author": "Sneha Nair",
            "author_role": "Community & PR Lead",
            "timestamp": now - timedelta(hours=6),
            "title": "Workshop RSVP Link & Certificate Eligibility Criteria",
            "content": "Hey community! RSVP link for the GenAI Workshop is live at: gdg.community.dev/events/mcet-genai-2026. Important: Digital participation certificates will only be issued to registered attendees who submit the hands-on project link before 5 PM on workshop day. Limited to 150 participants!",
            "permission": PermissionLevel.PUBLIC_COMMUNITY,
            "tags": ["rsvp", "certificates", "community", "registration", "rules"],
            "entities": {"rsvp_link": "gdg.community.dev/events/mcet-genai-2026", "seat_limit": 150},
            "metadata": {"channel": "general", "message_id": "disc_502"}
        }
    ]

    records: List[SourceRecord] = []
    chunks: List[MemoryChunk] = []
    receipts: List[IngestionReceipt] = []

    for raw in raw_items:
        adapter = get_source_adapter(raw["source_type"])
        record, item_chunks, receipt = adapter.ingest(raw, organization_id=organization_id)
        records.append(record)
        chunks.extend(item_chunks)
        receipts.append(receipt)

    return records, chunks, receipts
