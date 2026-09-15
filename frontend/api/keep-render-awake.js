export default async function handler(req, res) {
  // Strict fail-closed security: CRON_SECRET is required at runtime
  const cronSecret = process.env.CRON_SECRET;
  if (!cronSecret || cronSecret.trim().length === 0) {
    return res.status(500).json({
      error: 'Server Misconfiguration',
      message: 'CRON_SECRET environment variable is required and must be configured on Vercel.'
    });
  }

  const authHeader = req.headers['authorization'];
  const querySecret = req.query?.secret;
  const isAuthorized =
    authHeader === `Bearer ${cronSecret}` ||
    querySecret === cronSecret;

  if (!isAuthorized) {
    return res.status(401).json({
      error: 'Unauthorized',
      message: 'Invalid or missing CRON_SECRET.'
    });
  }

  const renderUrl = process.env.RENDER_SERVICE_URL || 'https://thread-agent.onrender.com';
  const healthEndpoint = `${renderUrl.replace(/\/+$/, '')}/health`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20000);

    const startTime = Date.now();
    const response = await fetch(healthEndpoint, {
      method: 'GET',
      headers: {
        'User-Agent': 'Thread-Agent-Vercel-Cron/1.0',
        'Accept': 'application/json'
      },
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    const latencyMs = Date.now() - startTime;
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    return res.status(200).json({
      status: 'ok',
      target: healthEndpoint,
      render_status: response.status,
      render_ok: response.ok,
      latency_ms: latencyMs,
      response_data: data,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    return res.status(502).json({
      status: 'error',
      target: healthEndpoint,
      error: error.message || 'Failed to ping Render service',
      timestamp: new Date().toISOString()
    });
  }
}
