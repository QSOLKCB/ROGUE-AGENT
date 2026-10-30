// Browser DOM-safety and pagination checks for the public Artifactory.
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

async function run(apiBaseUrl, summary, fetchDetail = null) {
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
    if (fetchDetail && /\/v1\/(?:artifacts|receipts)\//.test(url)) return fetchDetail(url);
    if (url.includes("/v1/artifacts/a_")) {
      return {ok:true,json:async()=>({schema_version:1,item:{
        id:summary.items[0].id, title:"Test title",
        body:'<img src=x onerror="alert(1)">',
        source_sha256:"a".repeat(64), identity_status:"self_reported"
      }})};
    }
    return {ok:true,json:async()=>typeof summary === "function" ? summary(url) : summary};
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


function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes;reject = no;});
  return {promise, resolve, reject};
}
const itemResult = (id, body) => ({schema_version:1,item:{
  id, title:"Reviewed artifact", body, identity_status:"self_reported"
}});
const records = (ids) => ({
  schema_version:1,items:ids.map(id=>({
    id,title:"Reviewed " + id,published_at:"2026-10-30T00:00:00Z"
  })),next_cursor:null
});
function inspect(app, index) {
  const card = app.nodes.get("catalog-list").children[index];
  const button = card.children.find(node => node.kind === "button");
  assert.ok(button);
  button.click();
}

test("valid Unicode code-point length is accepted, despite UTF-16 length > 8000", async () => {
  const id = "a_" + "c".repeat(32);
  const content = "🦘".repeat(3000) + "A".repeat(2100);
  assert.equal(content.length, 8100);
  assert.equal(Array.from(content).length, 5100);
  const app = await run("https://habitat.example", records([id]), () => ({
    ok:true,json:async()=>itemResult(id,content)
  }));
  inspect(app,0);
  await flush();await flush();
  const text = app.nodes.get("catalog-detail").children.find(x=>x.kind==="pre");
  assert.ok(text,"valid published artifact must render");
  assert.equal(text.textContent,content);
});

test("older detail success cannot overwrite the most recently selected record", async () => {
  const id1="a_"+"a".repeat(32), id2="a_"+"b".repeat(32);
  const pending = new Map([[id1,deferred()],[id2,deferred()]]);
  const app=await run("https://habitat.example",records([id1,id2]),url => ({
    ok:true,json:()=>pending.get(url.split("/").at(-1)).promise
  }));
  inspect(app,0);
  inspect(app,1);
  pending.get(id2).resolve(itemResult(id2,"SECOND record"));
  await flush();await flush();
  pending.get(id1).resolve(itemResult(id1,"FIRST record"));
  await flush();await flush();
  const detail=app.nodes.get("catalog-detail").children;
  assert.ok(detail.some(node=>node.textContent==="Review record: "+id2));
  assert.equal(detail.find(node=>node.kind==="pre")?.textContent,"SECOND record");
  assert.ok(!detail.some(node=>node.textContent==="Review record: "+id1));
});

test("older detail failure cannot erase newer successful details", async () => {
  const id1="a_"+"d".repeat(32),id2="a_"+"e".repeat(32);
  const pending=new Map([[id1,deferred()],[id2,deferred()]]);
  const app=await run("https://habitat.example",records([id1,id2]),url => ({
    ok:true,json:()=>pending.get(url.split("/").at(-1)).promise
  }));
  inspect(app,0);
  inspect(app,1);
  pending.get(id2).resolve(itemResult(id2,"newer good record"));
  await flush();await flush();
  pending.get(id1).reject(new Error("Older response failed"));
  await flush();await flush();
  const detail=app.nodes.get("catalog-detail").children;
  assert.equal(detail.find(node=>node.kind==="pre")?.textContent,"newer good record");
  assert.ok(!detail.some(node=>/unavailable/i.test(node.textContent)));
});

test("switching collections invalidates an in-flight detail response", async () => {
  const id="a_"+"f".repeat(32);
  const pending=deferred();
  const app=await run("https://habitat.example",records([id]),()=>({
    ok:true,json:()=>pending.promise
  }));
  inspect(app,0);
  app.tabs[1].click(); // switch to receipts while artifact detail is loading
  await flush();await flush();
  pending.resolve(itemResult(id,"obsolete artifact details"));
  await flush();await flush();
  assert.equal(app.nodes.get("catalog-detail").children.length,0);
});

test("browser follows versioned cursors for long opaque agent IDs", async () => {
  const id1 = "agent:" + "x".repeat(100);
  const id2 = "agent:" + "y".repeat(100);
  const cursor = "v1_" + Buffer.from(id1, "utf8").toString("base64url");
  assert.ok(cursor.length > 80, "regression must exceed legacy 80-character limit");
  const app = await run("https://habitat.example", url => {
    if (!url.includes("/v1/agents?")) {
      return {schema_version:1,items:[],next_cursor:null};
    }
    const after = new URL(url).searchParams.get("after");
    if (after === null) {
      return {schema_version:1,items:[{id:id1,published_at:"2026-10-30T00:00:00Z"}],
        next_cursor:cursor};
    }
    assert.equal(after, cursor);
    return {schema_version:1,items:[{id:id2,published_at:"2026-10-30T00:00:01Z"}],
      next_cursor:null};
  });
  app.tabs[2].click();
  await flush();await flush();
  assert.equal(app.nodes.get("catalog-list").children[0].children[0].textContent, id1);
  assert.equal(app.nodes.get("catalog-next").disabled, false);
  app.nodes.get("catalog-next").click();
  await flush();await flush();
  assert.equal(app.nodes.get("catalog-list").children[0].children[0].textContent, id2);
  assert.equal(app.nodes.get("catalog-prev").disabled, false);
  app.nodes.get("catalog-prev").click();
  await flush();await flush();
  assert.equal(app.nodes.get("catalog-list").children[0].children[0].textContent, id1);
});

test("contract-valid long Unicode experiment ID renders without fabricating an API error", async () => {
  const id = "experiment:🤖:" + "x".repeat(300);
  const app = await run("https://habitat.example", url => {
    if (url.includes("/v1/experiments?")) {
      return {schema_version:1,items:[{id,published_at:"2026-10-30T00:00:00Z"}],next_cursor:null};
    }
    return {schema_version:1,items:[],next_cursor:null};
  });
  app.tabs[3].click();
  await flush();await flush();
  assert.equal(app.nodes.get("catalog-list").children.length, 1);
  assert.equal(app.nodes.get("catalog-list").children[0].children[0].textContent, id);
  assert.match(app.nodes.get("catalog-status").textContent, /Showing reviewed/);
});

test("empty identifier is rejected without displaying an invented record", async () => {
  const app = await run("https://habitat.example", {
    schema_version:1,items:[{id:"",published_at:"2026-10-30T00:00:00Z"}],next_cursor:null
  });
  assert.equal(app.nodes.get("catalog-list").children.length, 0);
  assert.match(app.nodes.get("catalog-status").textContent, /unavailable/);
});
