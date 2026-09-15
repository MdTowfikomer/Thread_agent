-- Migration 017: Purge fixture seed records and chunks from organizational memory

-- 1. Delete memory_chunks associated with fixture source records
DELETE FROM memory_chunks
WHERE source_record_id IN (
    SELECT id FROM source_records
    WHERE source_uri IN (
        'https://discord.com/channels/gdg-mcet/announcements/101',
        'https://github.com/gdg-mcet/genai-starter-kit',
        'https://docs.google.com/spreadsheets/d/gdg-mcet-budget-2026',
        'https://notion.so/gdg-mcet/speaker-database-v2',
        'https://discord.com/channels/gdg-mcet/general/502'
    )
) OR source_uri IN (
    'https://discord.com/channels/gdg-mcet/announcements/101',
    'https://github.com/gdg-mcet/genai-starter-kit',
    'https://docs.google.com/spreadsheets/d/gdg-mcet-budget-2026',
    'https://notion.so/gdg-mcet/speaker-database-v2',
    'https://discord.com/channels/gdg-mcet/general/502'
);

-- 2. Delete fixture source records
DELETE FROM source_records
WHERE source_uri IN (
    'https://discord.com/channels/gdg-mcet/announcements/101',
    'https://github.com/gdg-mcet/genai-starter-kit',
    'https://docs.google.com/spreadsheets/d/gdg-mcet-budget-2026',
    'https://notion.so/gdg-mcet/speaker-database-v2',
    'https://discord.com/channels/gdg-mcet/general/502'
);
