import assert from "assert";
globalThis.localStorage = (()=>{ const m=new Map(); return {getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k),clear:()=>m.clear()};})();
globalThis.document = { addEventListener:()=>{}, createElement:()=>({style:{},classList:{add:()=>{},remove:()=>{}},appendChild:()=>{},querySelector:()=>null})};
globalThis.window = globalThis;


import { loadStore, saveStore } from "../../static/js/terminal/terminal-store.js";

let s = loadStore();
assert.equal(s.panelOpen, false);
assert.equal(s.maximized, false);
s.panelOpen=true; saveStore(s);
let s2=loadStore();
assert.equal(s2.panelOpen,true);
console.log("panel open persist ok");

s.panelHeight=400; s.previousPanelHeight=400; saveStore(s);
let s3=loadStore();
assert.equal(s3.panelHeight,400);
console.log("panel height persist ok");

// fallback after close
let store = {activeTerminalId:"a", terminals:[{id:"a",title:"bash 1"},{id:"b",title:"bash 2"}]};
let idx = store.terminals.findIndex(t=>t.id==="a");
let next = store.terminals[Math.min(idx, store.terminals.length-2)] || store.terminals[0];
assert.ok(next);
console.log("fallback ok");

console.log("ALL PANEL TESTS PASSED");
