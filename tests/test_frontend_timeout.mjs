// Dependency-free Node regression tests for the public summary fetch timeout.
// Run: node --test tests/test_frontend_timeout.mjs
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {runInNewContext} from "node:vm";

const source = readFileSync(new URL("../docs/main.js", import.meta.url), "utf8");
const flush = () => new Promise((resolve) => setImmediate(resolve));

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

async function boot() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {textContent: ""});
    return elements.get(id);
  };
  const started = deferred();
  const body = deferred();
  let abortSignal;
  let timerCallback;
  let clearCount = 0;

  const fetch = async (url, options) => {
    if (url === "./config.json") {
      return {ok:true, json: async () => ({apiBaseUrl:"https://habitat.example"})};
    }
    assert.equal(url, "https://habitat.example/v1/public/summary");
    abortSignal = options.signal;
    abortSignal.addEventListener("abort", () => body.reject(new Error("body aborted")), {once:true});
    return {
      ok: true,
      json() {
        started.resolve();
        return body.promise;
      }
    };
  };

  runInNewContext(source, {
    document: {getElementById: element},
    fetch, URL, AbortController, Date, Number, Object,
    setTimeout(fn, ms) {
      assert.equal(ms, 5000);
      timerCallback = fn;
      return 1;
    },
    clearTimeout(id) {
      assert.equal(id, 1);
      clearCount++;
    }
  }, {filename:"docs/main.js"});

  await started.promise;
  return {
    body,
    element,
    get signal() { return abortSignal; },
    get clearCount() { return clearCount; },
    fireTimeout() { timerCallback(); }
  };
}

test("timeout remains armed while a 200 response body stalls", async () => {
  const app = await boot();
  assert.equal(app.signal.aborted, false);
  assert.equal(app.clearCount, 0, "timer must remain active through response.json()");
  app.fireTimeout();
  assert.equal(app.signal.aborted, true);
  await flush();
  assert.equal(app.clearCount, 1, "timer must be cleared after aborted body consumption");
  assert.equal(app.element("service-state").textContent, "FOUNDATION ONLY");
  assert.match(app.element("service-note").textContent, /unavailable/);
  assert.equal(app.element("agents-count").textContent, "—");
});

test("successful JSON body clears timeout and displays observed counts", async () => {
  const app = await boot();
  assert.equal(app.clearCount, 0);
  app.body.resolve({
    schema_version:1,
    generated_at:"2026-10-30T00:00:00Z",
    counts:{agents:1,artifacts:2,experiments:3,receipts:4}
  });
  await flush();
  assert.equal(app.clearCount, 1);
  assert.equal(app.signal.aborted, false);
  assert.equal(app.element("service-state").textContent, "API CONNECTED");
  assert.equal(app.element("agents-count").textContent, "1");
  assert.equal(app.element("receipts-count").textContent, "4");
});

test("malformed JSON body error clears timeout and reverts to unavailable", async () => {
  const app = await boot();
  app.body.reject(new SyntaxError("truncated JSON"));
  await flush();
  assert.equal(app.clearCount, 1);
  assert.equal(app.element("service-state").textContent, "FOUNDATION ONLY");
  assert.match(app.element("service-note").textContent, /unavailable/);
});
