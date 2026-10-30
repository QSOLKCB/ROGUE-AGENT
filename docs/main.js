"use strict";
(async function init() {
  const state = document.getElementById("service-state");
  const backend = document.getElementById("backend-state");
  const note = document.getElementById("service-note");
  const updated = document.getElementById("updated-at");
  const ids = {agents:"agents-count",artifacts:"artifacts-count",experiments:"experiments-count",receipts:"receipts-count"};
  const reset = (message) => {
    state.textContent = "FOUNDATION ONLY";
    backend.textContent = "NOT CONNECTED";
    note.textContent = message;
    updated.textContent = "Live data not yet connected";
    for (const id of Object.values(ids)) document.getElementById(id).textContent = "—";
  };
  reset("No live agent service or visitor activity is claimed.");
  try {
    const configResponse = await fetch("./config.json", {cache:"no-store"});
    if (!configResponse.ok) throw new Error("Configuration unavailable");
    const config = await configResponse.json();
    const origin = config.apiBaseUrl;
    if (origin === "") return;
    if (typeof origin !== "string") throw new Error("Invalid configuration");
    const api = new URL(origin);
    if (api.protocol !== "https:" || api.username || api.password || api.search || api.hash || api.pathname !== "/") throw new Error("Invalid HTTPS API origin");
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 5000);
    let payload;
    try {
      const response = await fetch(api.origin + "/v1/public/summary",{signal:abort.signal,mode:"cors",cache:"no-store"});
      if (!response.ok) throw new Error("Public summary unavailable");
      payload = await response.json();
    } finally {
      clearTimeout(timeout);
    }
    if (payload.schema_version !== 1 || !payload.counts || typeof payload.counts !== "object") throw new Error("Summary schema mismatch");
    if (typeof payload.generated_at !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$/.test(payload.generated_at) || Number.isNaN(Date.parse(payload.generated_at))) throw new Error("Summary timestamp invalid");
    for (const key of Object.keys(ids)) if (!Number.isSafeInteger(payload.counts[key]) || payload.counts[key] < 0) throw new Error("Invalid summary count");
    for (const [key,id] of Object.entries(ids)) document.getElementById(id).textContent = String(payload.counts[key]);
    state.textContent = "API CONNECTED";
    backend.textContent = "PUBLIC READ-ONLY";
    note.textContent = "Showing public, approved records only. Identity claims are not verified.";
    updated.textContent = "Summary generated " + new Date(payload.generated_at).toLocaleString();
  } catch (_) {
    reset("The live public summary is unavailable. No visitor counts are inferred.");
  }
})();

