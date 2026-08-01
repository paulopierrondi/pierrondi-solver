import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import {
  solveChallenge,
  solverHealth,
  SolverValidationError,
  SolverUnsolvedError,
  SolverHTTPError,
  SolverArtifactPolicyError,
  SolverResponseError,
} from '../solver-client.mjs';

function fixture(handler) {
  const server = createServer(handler);
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      resolve({
        baseUrl: `http://127.0.0.1:${server.address().port}`,
        close: () => {
          server.closeAllConnections?.();
          return new Promise((r) => server.close(r));
        },
      });
    });
  });
}

const validReq = {
  type: 'recaptcha_v2',
  sitekey: '6Le-example-sitekey',
  pageUrl: 'https://example.com/login',
  purpose: 'authentication',
  operationId: 'op-123',
  attempt: 1,
};

function policy(purpose, consumption, mustNotReuse) {
  return { purpose, operation_id: 'op-123', attempt: 1, consumption, must_not_reuse_across_purposes: mustNotReuse };
}

function solvedBody(purpose, consumption) {
  return JSON.stringify({
    token: 'tok-example',
    strategy: 'v2_audio',
    provider: 'pierrondi',
    latency_ms: 1234,
    cost_usd: 0,
    extra: { engine: 'chromium', artifact_policy: policy(purpose, consumption, consumption === 'single_use') },
  });
}

test('exact JSON request contract + success decoding', async () => {
  let captured;
  const { baseUrl, close } = await fixture((req, res) => {
    let raw = '';
    req.on('data', (c) => (raw += c));
    req.on('end', () => {
      captured = { method: req.method, url: req.url, body: JSON.parse(raw) };
      res.writeHead(200, { 'content-type': 'application/json' }).end(solvedBody('authentication', 'single_use'));
    });
  });
  const res = await solveChallenge({ ...validReq, baseUrl });
  assert.equal(captured.method, 'POST');
  assert.equal(captured.url, '/solve');
  assert.deepEqual(captured.body, {
    type: 'recaptcha_v2',
    sitekey: '6Le-example-sitekey',
    page_url: 'https://example.com/login',
    lane: 'default',
    timeout_s: 120,
    purpose: 'authentication',
    operation_id: 'op-123',
    attempt: 1,
  });
  assert.equal(res.token, 'tok-example');
  assert.equal(res.provider, 'pierrondi');
  assert.equal(res.latencyMs, 1234);
  assert.equal(res.artifact.consumption, 'single_use');
  assert.equal(res.extra.engine, 'chromium');
  await close();
});

test('422 decodes into SolverUnsolvedError with typed fields', async () => {
  const { baseUrl, close } = await fixture((req, res) => {
    res.writeHead(422, { 'content-type': 'application/json' }).end(
      JSON.stringify({ error: 'unsolved', reason: 'all providers failed', fallback_recommended: true, attempts: ['a', 'b'] })
    );
  });
  await assert.rejects(
    solveChallenge({ ...validReq, baseUrl }),
    (err) => {
      assert.ok(err instanceof SolverUnsolvedError);
      assert.equal(err.reason, 'all providers failed');
      assert.equal(err.fallbackRecommended, true);
      assert.equal(err.attempts.length, 2);
      assert.equal(err.message, 'solver-client: challenge unsolved');
      return true;
    }
  );
  await close();
});

test('malformed JSON and oversized bodies become SolverResponseError', async () => {
  const bad = await fixture((req, res) => res.writeHead(200).end('not json'));
  await assert.rejects(solveChallenge({ ...validReq, baseUrl: bad.baseUrl }), SolverResponseError);
  await bad.close();

  const big = await fixture((req, res) => res.writeHead(200).end('x'.repeat((1 << 20) + 16)));
  await assert.rejects(solveChallenge({ ...validReq, baseUrl: big.baseUrl }), SolverResponseError);
  await big.close();
});

test('invalid requests fail before any network I/O', async () => {
  let hits = 0;
  const { baseUrl, close } = await fixture((req, res) => {
    hits += 1;
    res.writeHead(200).end(solvedBody('authentication', 'single_use'));
  });
  const cases = [
    { type: 'recaptcha_v9' },
    { purpose: 'write_only' },
    { sitekey: '' },
    { timeoutS: 4 },
    { timeoutS: 601 },
    { attempt: 0 },
    { attempt: 1001 },
    { operationId: '-bad' },
    { operationId: 'a'.repeat(81) },
    { pageUrl: 'http://' },
  ];
  for (const patch of cases) {
    await assert.rejects(solveChallenge({ ...validReq, baseUrl, ...patch }), SolverValidationError);
  }
  assert.equal(hits, 0);
  await close();
});

test('artifact-policy mismatch is rejected', async () => {
  const wrongPurpose = await fixture((req, res) => res.writeHead(200).end(solvedBody('read_only', 'single_use')));
  await assert.rejects(solveChallenge({ ...validReq, baseUrl: wrongPurpose.baseUrl }), SolverArtifactPolicyError);
  await wrongPurpose.close();

  const wrongConsumption = await fixture((req, res) => res.writeHead(200).end(solvedBody('authentication', 'session_bound')));
  await assert.rejects(solveChallenge({ ...validReq, baseUrl: wrongConsumption.baseUrl }), SolverArtifactPolicyError);
  await wrongConsumption.close();
});

test('cloudflare session_bound semantics: no sitekey, clearance context preserved', async () => {
  const { baseUrl, close } = await fixture((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' }).end(
      JSON.stringify({
        token: 'cf-clearance-context',
        strategy: 'clearance',
        provider: 'pierrondi',
        latency_ms: 10,
        cost_usd: 0,
        extra: {
          user_agent: 'ua-example',
          cookies: { cf_clearance: 'cookie-example' },
          artifact_policy: policy('read_only', 'session_bound', false),
        },
      })
    );
  });
  const res = await solveChallenge({
    type: 'cloudflare',
    pageUrl: 'https://example.com/protected',
    purpose: 'read_only',
    baseUrl,
  });
  assert.equal(res.artifact.consumption, 'session_bound');
  assert.equal(res.extra.cookies.cf_clearance, 'cookie-example');
  assert.equal(res.extra.user_agent, 'ua-example');
  await close();
});

test('state_change is sent exactly once, even on 5xx', async () => {
  let hits = 0;
  const { baseUrl, close } = await fixture((req, res) => {
    hits += 1;
    res.writeHead(500).end('{"detail":"boom"}');
  });
  await assert.rejects(
    solveChallenge({ ...validReq, purpose: 'state_change', baseUrl }),
    (err) => {
      assert.ok(err instanceof SolverHTTPError);
      assert.equal(err.status, 500);
      return true;
    }
  );
  assert.equal(hits, 1);
  await close();
});

test('errors never contain token, cookie, sitekey or operation_id values', async () => {
  const secrets = ['SITEKEY-SECRET-9f8e', 'OPID-SECRET-7d6c', 'TOKEN-SECRET-1a2b', 'COOKIE-SECRET-4d5e'];
  const echo = JSON.stringify({
    error: 'unsolved',
    reason: `saw ${secrets[0]} and ${secrets[2]}`,
    fallback_recommended: false,
    attempts: [`saw ${secrets[1]}`, `saw ${secrets[3]}`],
  });
  for (const status of [422, 502]) {
    const { baseUrl, close } = await fixture((req, res) => res.writeHead(status).end(echo));
    try {
      await solveChallenge({ ...validReq, sitekey: secrets[0], operationId: secrets[1], baseUrl });
      assert.fail('should have thrown');
    } catch (err) {
      for (const s of secrets) assert.ok(!err.message.includes(s), `leaked ${s} in ${err.message}`);
    }
    await close();
  }
  // validation errors also never echo values
  try {
    await solveChallenge({ ...validReq, operationId: `-${secrets[1]}`, baseUrl: 'http://127.0.0.1:1' });
    assert.fail('should have thrown');
  } catch (err) {
    for (const s of secrets) assert.ok(!err.message.includes(s), `leaked ${s} in ${err.message}`);
  }
});

test('solverHealth returns typed status and providers', async () => {
  const { baseUrl, close } = await fixture((req, res) => {
    assert.equal(req.url, '/health');
    res.writeHead(200, { 'content-type': 'application/json' }).end(
      JSON.stringify({ status: 'ok', providers: ['pierrondi', 'capsolver'] })
    );
  });
  const health = await solverHealth({ baseUrl });
  assert.equal(health.status, 'ok');
  assert.deepEqual(health.providers, ['pierrondi', 'capsolver']);
  await close();
});

test('PIERRONDI_SOLVER_URL env is honored and trailing slash trimmed', async () => {
  const { baseUrl, close } = await fixture((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ status: 'ok', providers: [] }));
  });
  process.env.PIERRONDI_SOLVER_URL = `${baseUrl}/`;
  try {
    const health = await solverHealth();
    assert.equal(health.status, 'ok');
  } finally {
    delete process.env.PIERRONDI_SOLVER_URL;
    await close();
  }
});
