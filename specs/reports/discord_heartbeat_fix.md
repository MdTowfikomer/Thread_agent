# Discord gateway heartbeat fix — 2026-10-29

## Observed failure

Hosted logs showed a first mention executing the inbound service's cold import on
Discord's asyncio event loop. Identity initialization performed synchronous
PostgreSQL operations while registering hardcoded GDG MCET bootstrap accounts.
Heartbeats were blocked for 10–30 seconds, followed by a reconnect and resume.
The heartbeat diagnostic also encountered a secondary logging format error when
its captured stack included SQL percent placeholders.

The same deployment, configured for direct PostgreSQL, repeatedly attempted to
initialize the optional Supabase HTTP client without a URL.

## Changes

- Mention processing offloads cold imports, identity resolution, access-context
  derivation, inference and outbound delivery to a worker thread.
- Gateway queue admission offloads binding and channel-policy lookups, while
  asyncio queue operations and task creation remain on the event loop.
- Production/configured identity services never auto-register demo identities.
  Fixture registration is restricted to explicitly enabled offline mode.
- Direct PostgreSQL configuration does not instantiate an unconfigured HTTP
  client; the existing direct database path remains available.
- Empty-mention greeting refers to the current workspace generically.
- Existing source ACL and account-verification rules are retained. Display-name
  similarity does not grant workspace membership or private-source access.

## Verification

Four regression checks initially failed: synchronous work on the mention/event
loop, queue lookup on the loop, production bootstrap writes, and unnecessary REST
initialization. After the changes, the selected gateway, worker, deployment smoke,
identity and regression suites passed: **45 tests**. No real platform messages
were sent by these checks.

The source archive was rebuilt, Python modules compiled, archive integrity checked,
and packaged bytes scanned against configured secrets. Environment files are not
included. Host-side heartbeat behavior still requires checking after uploading
the new archive; local tests do not prove successful remote deployment.

The separate database-error redaction fix is included in this archive. The
database password exposed in earlier user-supplied logs must still be rotated by
the operator and updated in every deployment using that connection.
