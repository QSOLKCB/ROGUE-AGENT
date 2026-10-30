"""Browser DOM-safety checks for the public Artifactory, with no network."""
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {runInNewContext} from "node:vm";

const source = readFileSync(new URL("../docs/catalog.js", import.meta.url), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor(kind = "") {
    this.kind = kind;
    this.children = [];
    this.textContent = "";
    this.dataset = {};
    this.attributes = {};
    this.disabled = false;
    this.events = {};
    this.classList = {toggle: () => {}};
  }
  append(node) {this.children.push(node);}
  replaceChildren(...nodes) {this.children = nodes;}
  setAttribute(key, value) {this.attributes[key] = value;}
  addEventListener(kind, fn) {this.events[kind] = fn;}
  click() {this.events.click?.();}
}

async function run(apiBaseUrl, summary) {
  const nodes = new Map();
  const ids = ["catalog-status", "catalog-list", "catalog-detail", "catalog-prev", "catalog-next"];
  for (const id of ids) nodes.set(id, new Element(id));
  const tabs = ["artifacts", "receipts", "agents", "experiments"].map(kind => {
    const tab = new Element("button");
    tab.dataset.catalogKind = kind;
    return tab;
  });
  const requests = [];
  const document = {
    getElementById: id => nodes.get(id),
    querySelectorAll: () => tabs,
    createElement: tag => new Element(tag),
  };
  const fetch = async url => {
    requests.push(url);
    if (url === "./config.json") return {ok:true,json:async()=>({apiBaseUrl})};
    if (url.includes("/v1/artifacts/a_")) {
      return {ok:true,json:async()=>({schema_version:1,item:{
        id:summary.items[0].id, title:"Test title",
        body:'<img src=x onerror="alert(1)">',
        source_sha256:"a".repeat(64), identity_status:"self_reported"
      }})};
    }
    return {ok:true,json:async()=>summary};
  };
  runInNewContext(source, {document, fetch, URL, URLSearchParams, AbortController,
    setTimeout, clearTimeout}, {filename:"docs/catalog.js"});
  await flush();await flush();await flush();
  return {nodes,tabs,requests};
}

test("unconfigured API stays offline; no fabricated collection request", async () => {
  const app = await run("", {schema_version:1,items:[],next_cursor:null});
  assert.deepEqual(app.requests, ["./config.json"]);
  assert.match(app.nodes.get("catalog-status").textContent, /offline/);
  assert.equal(app.nodes.get("catalog-list").children.length, 0);
});

test("reviewed artifact content is inserted as literal text, never parsed HTML", async () => {
  const id = "a_" + "a".repeat(32);
  const app = await run("https://habitat.example", {
    schema_version:1,items:[{id,title:"Example <script>alert(1)</script>",
      published_at:"2026-10-30T00:00:00Z",identity_status:"self_reported"}],
    next_cursor:null
  });
  const list = app.nodes.get("catalog-list");
  assert.equal(list.children.length, 1);
  const record = list.children[0];
  assert.equal(record.children[0].textContent, "Example <script>alert(1)</script>");
  const inspect = record.children.find(child => child.kind === "button");
  assert.ok(inspect);
  inspect.click();
  await flush();await flush();
  const detail = app.nodes.get("catalog-detail");
  const pre = detail.children.find(child => child.kind === "pre");
  assert.ok(pre);
  assert.equal(pre.textContent, '<img src=x onerror="alert(1)">');
  assert.equal(source.includes("innerHTML"), true, "source only mentions innerHTML in a warning comment");
  assert.equal(source.includes(".innerHTML ="), false);
});

test("invalid collection response cannot fabricate published items", async () => {
  const app = await run("https://habitat.example", {
    schema_version:1,items:[{id:"bad"}],next_cursor:"../escape"
  });
  assert.equal(app.nodes.get("catalog-list").children.length, 0);
  assert.match(app.nodes.get("catalog-status").textContent, /unavailable/);
});
