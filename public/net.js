/* JSON requests that survive a serverless cold start.
 * A first request after a quiet period can stall or fail while the function
 * boots; retry it with a timeout instead of leaving the page spinning. */
const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

class RequestError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

async function fetchJSON(url, options = {}, {timeout = 20000, retries = 2, onRetry, signal} = {}) {
  for (let attempt = 0; ; attempt++) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, timeout);
    try {
      const response = await fetch(url, {...options, signal: controller.signal});
      const payload = await response.json().catch(() => null);
      if (response.ok) return payload;
      const detail = payload?.detail;
      const message = typeof detail === 'string' ? detail : detail?.message || `Sunucu hata verdi (${response.status}).`;
      const error = new RequestError(message, response.status, payload);
      if (!RETRYABLE_STATUS.has(response.status) || attempt >= retries) throw error;
    } catch (error) {
      if (signal?.aborted) throw error;
      if (error instanceof RequestError && !RETRYABLE_STATUS.has(error.status)) throw error;
      if (attempt >= retries) {
        throw error instanceof RequestError ? error
          : new RequestError('Sunucuya ulaşılamadı. Bağlantını kontrol edip yeniden dene.', 0);
      }
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
    onRetry?.(attempt + 1);
    await new Promise(resolve => setTimeout(resolve, 800 * 2 ** attempt));
  }
}

if (typeof module !== 'undefined') module.exports = {fetchJSON, RequestError};
