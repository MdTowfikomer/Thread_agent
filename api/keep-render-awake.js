export default async function handler(req, res) {
  // Enforce CRON_SECRET authorization for Vercel Cron
  const authHeader = req.headers['authorization'];
  const cronSecret = process.env.CRON_SECRET;

  if (cronSecret) {
    const isAuthorized =
      authHeader === `Bearer ${cronSecret}` ||
      req.query?.secret === cronSecret;

    if (!isAuthorized) {
      return res.status(401).json({
        error: 'Unauthorized',
        message: 'Invalid or missing CRON_SECRET.'
      });
    }
  }

  const renderUrl = process.env.RENDER_SERVICE_URL || 'https://thread-agent-api.onrender.com';
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
