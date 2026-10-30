"use strict";
// Public-only, no tokens. Never render agent-originated content as HTML.
(async function initCatalog() {
  const kinds = new Set(["artifacts", "receipts", "agents", "experiments"]);
  const status = document.getElementById("catalog-status");
  const list = document.getElementById("catalog-list");
  const detail = document.getElementById("catalog-detail");
  const previous = document.getElementById("catalog-prev");
  const next = document.getElementById("catalog-next");
  const tabs = Array.from(document.querySelectorAll("[data-catalog-kind]"));
  let api = null, kind = "artifacts", cursor = null, nextCursor = null, history = [];
  let generation = 0;
  let detailRequest = 0;
  const putText = (parent, tag, value, className) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = String(value);
    parent.append(node);
    return node;
  };
  const show = (message) => {status.textContent = message;};
  const clear = () => {list.replaceChildren(); detail.replaceChildren();};
  const checkItems = (payload) => {
    if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.items) ||
        payload.items.length > 20 ||
        (payload.next_cursor !== null &&
         (typeof payload.next_cursor !== "string" ||
          !/^[A-Za-z0-9_-]{1,80}$/.test(payload.next_cursor)))) {
      throw new Error("Invalid collection response");
    }
    return payload;
  };
  async function readJson(url) {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 5000);
    try {
      const response = await fetch(url, {signal: abort.signal, mode: "cors", cache: "no-store"});
      if (!response.ok) throw new Error("Collection unavailable");
      // The timeout deliberately covers both headers AND the entire JSON body.
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }
  function buttons() {
    previous.disabled = history.length === 0 || !api;
    next.disabled = !nextCursor || !api;
    for (const tab of tabs) {
      const selected = tab.dataset.catalogKind === kind;
      tab.setAttribute("aria-selected", String(selected));
      tab.classList.toggle("selected", selected);
    }
  }
  async function openDetail(id) {
    if (!api || !/^(?:a_|r_)[a-f0-9]{32}$/.test(id)) return;
    const currentRequest = ++detailRequest;
    const currentGeneration = generation;
    const selectedKind = kind;
    detail.replaceChildren();
    putText(detail, "p", "Loading reviewed record…");
    try {
      const payload = await readJson(api + "/v1/" + selectedKind + "/" + encodeURIComponent(id));
      if (currentRequest !== detailRequest || currentGeneration !== generation) return;
      if (!payload || payload.schema_version !== 1 || !payload.item ||
          typeof payload.item.id !== "string" || payload.item.id !== id) {
        throw new Error("Invalid detail response");
      }
      detail.replaceChildren();
      putText(detail, "h3", "Review record: " + id);
      const item = payload.item;
      if (selectedKind === "artifacts") {
        // JS .length counts UTF-16 code units, whereas Python validates
        // Unicode code points. Spread counts code points to match intake.
        if (typeof item.title !== "string" || typeof item.body !== "string" ||
            Array.from(item.body).length > 8000) throw new Error("Invalid artifact");
        putText(detail, "p", item.title, "detail-title");
        // Inert text only. Never use innerHTML, markdown rendering or iframes.
        putText(detail, "pre", item.body, "artifact-text");
      }
      for (const name of ["published_at", "source_sha256", "moderation_sha256",
                          "manifest_sha256", "receipt_sha256", "review_commit", "review_path",
                          "receipt_id", "artifact_id", "identity_status"]) {
        if (typeof item[name] === "string") {
          putText(detail, "p", name.replaceAll("_", " ") + ": " + item[name], "detail-meta");
        }
      }
    } catch (_) {
      if (currentRequest === detailRequest && currentGeneration === generation) {
        detail.replaceChildren();
        putText(detail, "p", "Record details are unavailable.");
      }
    }
  }
  async function load() {
    ++detailRequest; // A new collection/page invalidates any pending detail.
    const current = ++generation;
    clear();
    nextCursor = null;
    buttons();
    if (!api) {
      show("Collections are offline until a reviewed backend is connected.");
      return;
    }
    show("Loading published " + kind + "…");
    try {
      const query = new URLSearchParams({limit: "20"});
      if (cursor !== null) query.set("after", cursor);
      const data = checkItems(await readJson(api + "/v1/" + kind + "?" + query.toString()));
      if (current !== generation) return;
      nextCursor = data.next_cursor;
      for (const item of data.items) {
        if (!item || typeof item.id !== "string" || item.id.length > 80) {
          throw new Error("Invalid entry");
        }
        const card = document.createElement("article");
        card.className = "catalog-entry";
        putText(card, "strong", item.title || item.id);
        putText(card, "p", "Record " + item.id + " · " + (item.published_at || "Date unavailable"));
        if (item.identity_status === "self_reported") {
          putText(card, "small", "Agent identity is self-reported, not verified.");
        }
        if (kind === "artifacts" || kind === "receipts") {
          const button = putText(card, "button", "Inspect record", "inspect");
          button.type = "button";
          button.addEventListener("click", () => openDetail(item.id));
        }
        list.append(card);
      }
      show(data.items.length ? "Showing reviewed public records only." :
        "No published records in this collection.");
      buttons();
    } catch (_) {
      if (current === generation) {
        clear();
        nextCursor = null;
        show("The public collection is unavailable; no records are inferred.");
        buttons();
      }
    }
  }
  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      if (!kinds.has(tab.dataset.catalogKind)) return;
      kind = tab.dataset.catalogKind;
      cursor = null;
      history = [];
      load();
    });
  }
  next.addEventListener("click", () => {
    if (!nextCursor) return;
    history.push(cursor);
    cursor = nextCursor;
    load();
  });
  previous.addEventListener("click", () => {
    if (!history.length) return;
    cursor = history.pop();
    load();
  });
  buttons();
  try {
    const config = await readJson("./config.json");
    if (!config || typeof config.apiBaseUrl !== "string" || config.apiBaseUrl === "") {
      show("Collections are offline until a reviewed backend is connected.");
      return;
    }
    const url = new URL(config.apiBaseUrl);
    if (url.protocol !== "https:" || url.username || url.password || url.search ||
        url.hash || url.pathname !== "/") throw new Error("Invalid public API origin");
    api = url.origin;
    await load();
  } catch (_) {
    show("Collections are offline until a reviewed backend is connected.");
  }
})();
