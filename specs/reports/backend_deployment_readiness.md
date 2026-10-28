# Backend deployment readiness — 2026-10-29

## Verified locally

- V2 identity, BYOK, traces, security isolation, gateway regression, deployment
  smoke, and session/frontend security selection: **92 passed, 39 skipped**.
  Skips are opt-in database/live checks; they are not verified passes.
- Frontend production build passed with the existing large-bundle warning.
- Candidate deployment sources were scanned against configured secret values;
  no configured secrets were found. Environment files are not deployment sources.
- Render configuration now declares `THREAD_MASTER_ENCRYPTION_KEY`, retains the
  separate Discord worker (`THREAD_START_GATEWAY_BOT=false`), and permits the
  README's documented frontend origin `https://thread-agent-xi.vercel.app`.
- A global `GEMINI_API_KEY` is not required by this V2 BYOK deployment blueprint.

## Not yet deployed

Implementation changes remain in the local working tree. No deployment commit
has been pushed or activated as part of this check. The installed Render CLI is
not authenticated; no Render API key, deploy hook or service ID is configured.
Requests to the frontend rewrite target `https://thread-agent.onrender.com`
timed out, so neither hosted health nor V2 version was established.

The operator must confirm the existing Render service or provide a different
deployment target, and authenticate with `render login` or perform the dashboard
deployment. Do not change Telegram merely because local checks passed.

## Backend settings

For the repository-root configuration in `render.yaml`:

```text
Build: pip install --upgrade pip && pip install -r backend/requirements.txt
Start: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
Python: 3.11.9
THREAD_START_GATEWAY_BOT=false
THREAD_DEMO_AUTH_ENABLED=false
THREAD_ALLOW_GUEST_MODE=false
```

Configure the same database and encryption master key used by the working local
backend and Discord worker. Configure backend `THREAD_JWT_SECRET`, GitHub webhook
secret, Slack token/signing secret, and Telegram token/webhook secret. Supabase
HTTP credentials may also be copied if that access path is used. A separate
`THREAD_SERVICE_DB_URL` is needed only when service metadata uses a separate DB.
Keep secret values out of commits, command arguments and public deployment logs.

## Cutover gate

1. Publish the intended source revision and deploy it to the confirmed service.
2. Verify `/health`, V2 routes in `/openapi.json`, and unauthenticated rejection
   from `/api/v2/auth/me`. Verify the hosted environment has the correct secrets.
3. Validate an authorized browser session through the frontend's API proxy.
4. Only then register Telegram at `https://<verified-backend>/api/webhooks/telegram`
   with its existing webhook secret. Retain pending updates and verify the result
   with `getWebhookInfo`.
5. The user will change Slack's Request URL to
   `https://<verified-backend>/api/webhooks/slack` and complete URL verification.
6. Repeat a real platform message-to-cited-answer check. The hosted Discord
   gateway continues independently against the shared database.

Telegram remains on the working ngrok endpoint until this gate is met.
