/**
 * solver-client.mjs — canonical career-ops client for the pierrondi-solver HTTP API.
 *
 * Implements the "CAPTCHA / Cloudflare auto-solve with pierrondi-solver" custom
 * workflow (modes/_custom.md): typed POST /solve + GET /health, local validation,
 * artifact-policy enforcement, redacted errors, zero implicit retry.
 *
 * Contract mirrors the Python API (src/pierrondi_solver/models.py):
 *   POST /solve {type, sitekey, page_url, lane, timeout_s, purpose, operation_id, attempt}
 *   200 -> {token, strategy, provider, latency_ms, cost_usd, extra.artifact_policy}
 *   422 -> {error, reason, fallback_recommended, attempts}
 *
 * Rules enforced here:
 *   - non-cloudflare challenges require a sitekey; timeout_s 5..600; attempt 1..1000;
 *     operation_id empty or [A-Za-z0-9][A-Za-z0-9._:-]{0,79}; known type/purpose.
 *   - a returned artifact_policy purpose must equal the requested purpose;
 *     a non-cloudflare result must be single_use; cloudflare must be session_bound.
 *   - exactly one HTTP request per call — retries belong to the solver cascade,
 *     never to this transport (state_change is sent once, even on 5xx).
 *   - error messages never contain tokens, cookies, sitekeys, operation IDs or bodies.
 *
 * Cloudflare clearance is session_bound: reuse extra.cookies.cf_clearance together
 * with extra.user_agent from the same IP — it is not a form-field token.
 *
 * Usage:
 *   import { solveChallenge, solverHealth } from './solver-client.mjs';
 *   const health = await solverHealth();
 *   const res = await solveChallenge({
 *     type: 'turnstile', sitekey: key, pageUrl: url, purpose: 'state_change',
 *   });
 */

const DEFAULT_BASE_URL = 'http://127.0.0.1:8791';
const MAX_RESPONSE_BYTES = 1 << 20; // 1 MiB

export const CHALLENGE_TYPES = new Set([
  'recaptcha_v2',
  'recaptcha_v3',
  'hcaptcha',
  'turnstile',
  'cloudflare',
]);
export const PURPOSES = new Set(['generic', 'authentication', 'read_only', 'state_change']);
const OPERATION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/;

export class SolverValidationError extends Error {
  constructor(field, msg) {
    super(`solver-client: invalid ${field}: ${msg}`);
    this.name = 'SolverValidationError';
    this.field = field;
  }
}

export class SolverUnsolvedError extends Error {
  /** Structured 422. Reason/attempts are fields, never in .message. */
  constructor({ error, reason, fallback_recommended, attempts }) {
    super('solver-client: challenge unsolved');
    this.name = 'SolverUnsolvedError';
    this.kind = error;
    this.reason = reason;
    this.fallbackRecommended = Boolean(fallback_recommended);
    this.attempts = Array.isArray(attempts) ? attempts : [];
  }
}

export class SolverHTTPError extends Error {
  constructor(status) {
    super(`solver-client: unexpected HTTP status ${status}`);
    this.name = 'SolverHTTPError';
    this.status = status;
  }
}

export class SolverArtifactPolicyError extends Error {
  constructor(msg) {
    super(`solver-client: artifact policy violation: ${msg}`);
    this.name = 'SolverArtifactPolicyError';
  }
}

export class SolverResponseError extends Error {
  constructor(msg) {
    super(`solver-client: response error: ${msg}`);
    this.name = 'SolverResponseError';
  }
}

function baseUrlFrom(override) {
  return (override || process.env.PIERRONDI_SOLVER_URL || DEFAULT_BASE_URL).replace(/\/+$/, '');
}

function validateRequest({ type, sitekey = '', pageUrl, timeoutS, purpose, operationId, attempt }) {
  if (!CHALLENGE_TYPES.has(type)) throw new SolverValidationError('type', 'unknown challenge type');
  if (type !== 'cloudflare' && !sitekey)
    throw new SolverValidationError('sitekey', 'required for non-cloudflare challenges');
  if (typeof pageUrl !== 'string' || pageUrl.length < 8)
    throw new SolverValidationError('page_url', 'must be at least 8 characters');
  if (!Number.isInteger(timeoutS) || timeoutS < 5 || timeoutS > 600)
    throw new SolverValidationError('timeout_s', 'must be between 5 and 600');
  if (!Number.isInteger(attempt) || attempt < 1 || attempt > 1000)
    throw new SolverValidationError('attempt', 'must be between 1 and 1000');
  if (!PURPOSES.has(purpose)) throw new SolverValidationError('purpose', 'unknown purpose');
  if (operationId !== '' && !OPERATION_ID_RE.test(operationId))
    throw new SolverValidationError('operation_id', 'must match [A-Za-z0-9][A-Za-z0-9._:-]{0,79}');
}

async function fetchBounded(url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    const reader = resp.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_RESPONSE_BYTES) {
        await reader.cancel().catch(() => {});
        throw new SolverResponseError('body exceeds 1 MiB limit');
      }
      chunks.push(value);
    }
    const body = Buffer.concat(chunks).toString('utf8');
    return { status: resp.status, body };
  } finally {
    clearTimeout(timer);
  }
}

function parseJson(body) {
  try {
    return JSON.parse(body);
  } catch {
    throw new SolverResponseError('malformed JSON body');
  }
}

/**
 * Health check: GET /health -> {status, providers}.
 */
export async function solverHealth({ baseUrl, timeoutMs = 5000 } = {}) {
  const url = `${baseUrlFrom(baseUrl)}/health`;
  const { status, body } = await fetchBounded(url, { headers: { accept: 'application/json' } }, timeoutMs);
  if (status !== 200) throw new SolverHTTPError(status);
  return parseJson(body);
}

/**
 * Solve a challenge via POST /solve. Exactly one HTTP request per call.
 *
 * @param {object} req
 * @param {'recaptcha_v2'|'recaptcha_v3'|'hcaptcha'|'turnstile'|'cloudflare'} req.type
 * @param {string} [req.sitekey] required unless type === 'cloudflare'
 * @param {string} req.pageUrl visible page URL
 * @param {string} [req.lane='career-ops']
 * @param {number} [req.timeoutS=120]
 * @param {'generic'|'authentication'|'read_only'|'state_change'} [req.purpose='generic']
 * @param {string} [req.operationId='']
 * @param {number} [req.attempt=1]
 * @param {string} [req.baseUrl] overrides PIERRONDI_SOLVER_URL
 * @returns {Promise<{token:string, strategy:string, provider:string, latencyMs:number, costUsd:number, extra:object, artifact:object}>}
 */
export async function solveChallenge(req) {
  const {
    type,
    sitekey = '',
    pageUrl,
    lane = 'default',
    timeoutS = 120,
    purpose = 'generic',
    operationId = '',
    attempt = 1,
    baseUrl,
  } = req;
  validateRequest({ type, sitekey, pageUrl, timeoutS, purpose, operationId, attempt });

  const payload = JSON.stringify({
    type,
    sitekey,
    page_url: pageUrl,
    lane,
    timeout_s: timeoutS,
    purpose,
    operation_id: operationId,
    attempt,
  });
  const url = `${baseUrlFrom(baseUrl)}/solve`;
  // HTTP timeout slightly above the solve budget, like the Go client default.
  const { status, body } = await fetchBounded(
    url,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: payload,
    },
    (timeoutS + 10) * 1000
  );

  if (status === 422) {
    throw new SolverUnsolvedError(parseJson(body));
  }
  if (status !== 200) {
    throw new SolverHTTPError(status);
  }

  const data = parseJson(body);
  const artifact = data?.extra?.artifact_policy ?? {};
  if (artifact.purpose !== purpose) {
    throw new SolverArtifactPolicyError('returned purpose differs from requested purpose');
  }
  if (type === 'cloudflare') {
    if (artifact.consumption !== 'session_bound') {
      throw new SolverArtifactPolicyError('cloudflare result must be session_bound');
    }
  } else if (artifact.consumption !== 'single_use') {
    throw new SolverArtifactPolicyError('non-cloudflare result must be single_use');
  }

  return {
    token: data.token,
    strategy: data.strategy,
    provider: data.provider,
    latencyMs: data.latency_ms,
    costUsd: data.cost_usd,
    extra: data.extra ?? {},
    artifact,
  };
}
