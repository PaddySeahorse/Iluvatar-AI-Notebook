import assert from "assert";
import { createWebSocketUrl, parseWsPath } from "../../static/js/terminal/terminal-api.js";

globalThis.location = new URL("http://localhost:8000/");
assert.ok(createWebSocketUrl("t1").includes("ws://"));
globalThis.location = new URL("https://host:443/foo/bar");
let u = createWebSocketUrl("xyz");
assert.ok(u.startsWith("wss://"));
assert.ok(u.endsWith("/ws/terminals/xyz"));
console.log("protocol ws url ok");

// unknown message handling simulation
function handleMessage(msg){
  try { let o=JSON.parse(msg); if(!["output","status","exit","pong","error"].includes(o.type)) return "unknown"; return o.type; } catch{ return "error"; }
}
assert.equal(handleMessage('{"type":"output","data":"hi"}'), "output");
assert.equal(handleMessage('{"type":"bogus"}'), "unknown");
console.log("protocol message ok");
console.log("ALL PROTOCOL TESTS PASSED");
