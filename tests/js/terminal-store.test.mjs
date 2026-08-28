import assert from "assert";
import { createWebSocketUrl } from "../../static/js/terminal/terminal-api.js";

globalThis.location = new URL("http://localhost:5000/");
assert.equal(createWebSocketUrl("abc").startsWith("ws://"), true);
globalThis.location = new URL("https://example.com/app/");
let u = createWebSocketUrl("id1");
assert.ok(u.startsWith("wss://"));
assert.ok(u.includes("/ws/terminals/id1"));
console.log("store ws url ok");

// localStorage mock
globalThis.localStorage = (()=>{ const m=new Map(); return {getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};})();

import { loadStore, saveStore } from "../../static/js/terminal/terminal-store.js";
let s = loadStore();
assert.equal(s.panelOpen, false);
s.panelOpen = true; s.panelHeight=300; saveStore(s);
let s2 = loadStore();
assert.equal(s2.panelOpen, true);
assert.equal(s2.panelHeight, 300);
console.log("store persistence ok");

// check terminal state not in notebook export
import * as stateMod from "../../static/js/state.js";
assert.ok(!JSON.stringify(stateMod.state).includes("terminal"));
console.log("notebook state isolated ok");
console.log("ALL JS STORE TESTS PASSED");
