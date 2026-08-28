import { createTerminal, listTerminals, renameTerminal, deleteTerminal } from "./terminal-api.js";
import { createStore, saveStore } from "./terminal-store.js";
import { TerminalInstance } from "./terminal-instance.js";

export class TerminalPanel {
  constructor() {
    this.store = createStore();
    this.instances = new Map();
    this.root = null;
    this.tabsEl = null;
    this.hostEl = null;
    this.emptyEl = null;
    this._dragState = null;
  }

  mount(root) {
    this.root = root;
    this._renderShell();
    this._bindEvents();
    this._applyState();
    this._preloadXterm();
    this._restoreSessions();
    window.addEventListener("resize", () => {
      const inst = this.instances.get(this.store.activeTerminalId);
      if (inst) inst.fit();
    });
  }

  _preloadXterm() {
    import("./terminal-instance.js").then((m) => {
      m.TerminalInstance._loadXterm().catch(() => {});
      m.TerminalInstance._loadFitAddon().catch(() => {});
    }).catch(() => {});
  }

  _nextFrame() {
    return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  }

  _renderShell() {
    this.root.innerHTML = `
      <div class="terminal-resize-handle" id="termResizeHandle" title="Drag to resize, double-click to maximize"></div>
      <div class="terminal-header">
        <div class="terminal-header-left">
          <button class="terminal-toggle-btn" id="termToggleBtn" title="Toggle terminal (Ctrl+\\\`)" aria-label="Toggle terminal"><i class="fa-solid fa-terminal"></i> Terminal</button>
          <div class="terminal-tabs" id="termTabs"></div>
        </div>
        <div class="terminal-actions">
          <button class="term-action-btn" id="termNewBtn" title="New terminal"><i class="fa-solid fa-plus"></i></button>
          <button class="term-action-btn" id="termMaxBtn" title="Maximize/Restore"><i class="fa-solid fa-expand"></i></button>
          <button class="term-action-btn" id="termCloseBtn" title="Collapse"><i class="fa-solid fa-chevron-down"></i></button>
        </div>
      </div>
      <div class="terminal-body" id="termBody">
        <div class="terminal-host" id="termHost"></div>
        <div class="terminal-empty hidden" id="termEmpty">
          <p>No terminal yet</p>
          <button class="modal-btn primary small" id="termEmptyNewBtn">New Terminal</button>
        </div>
      </div>
    `;
    this.tabsEl = this.root.querySelector("#termTabs");
    this.hostEl = this.root.querySelector("#termHost");
    this.emptyEl = this.root.querySelector("#termEmpty");
  }

  _bindEvents() {
    this.root.querySelector("#termToggleBtn").addEventListener("click", () => this.toggle());
    this.root.querySelector("#termNewBtn").addEventListener("click", () => this.createNew());
    this.root.querySelector("#termEmptyNewBtn").addEventListener("click", () => this.createNew());
    this.root.querySelector("#termMaxBtn").addEventListener("click", () => this.toggleMaximize());
    this.root.querySelector("#termCloseBtn").addEventListener("click", () => this.collapse());
    const handle = this.root.querySelector("#termResizeHandle");
    handle.addEventListener("mousedown", (e) => this._startDrag(e));
    handle.addEventListener("dblclick", () => this.toggleMaximize());
  }

  _applyState() {
    if (this.store.panelOpen) {
      this.root.classList.add("open");
      this.root.style.height = (this.store.maximized ? "70vh" : this.store.panelHeight + "px");
    } else {
      this.root.classList.remove("open");
      this.root.classList.remove("maximized");
      this.root.style.height = "32px";
    }
    if (this.store.maximized) this.root.classList.add("maximized");
    else this.root.classList.remove("maximized");
    this._updateBodyVisibility();
  }

  _updateBodyVisibility() {
    const body = this.root.querySelector("#termBody");
    if (this.store.panelOpen) body.style.display = "flex";
    else body.style.display = "none";
  }

  async _restoreSessions() {
    try {
      const list = await listTerminals();
      this.store.terminals = list;
      if (list.length === 0) {
        this._renderTabs();
        this._showEmpty(true);
        return;
      }
      if (!this.store.activeTerminalId || !list.find(t => t.id === this.store.activeTerminalId)) {
        this.store.activeTerminalId = list[0].id;
      }
      this._showEmpty(false);
      await this._nextFrame();
      await Promise.all(list.map((t) => this._ensureInstance(t)));
      this._renderTabs();
      this._switchTo(this.store.activeTerminalId);
      saveStore(this.store);
    } catch (e) {
      this._renderTabs();
      this._showEmpty(this.store.terminals.length === 0);
    }
  }

  async _ensureInstance(meta) {
    if (this.instances.has(meta.id)) return this.instances.get(meta.id);
    const container = document.createElement("div");
    container.className = "terminal-instance";
    container.dataset.tid = meta.id;
    container.style.display = "none";
    this.hostEl.appendChild(container);
    const inst = new TerminalInstance({ id: meta.id, cols: meta.cols, rows: meta.rows, container });
    this.instances.set(meta.id, inst);
    try {
      await inst.init((status, exitCode) => this._onInstanceStatus(meta.id, status, exitCode));
    } catch (err) {
      container.innerHTML = `<div style="color:var(--error);padding:12px;font-family:monospace">Terminal init failed: ${err.message}</div>`;
      console.error("terminal init failed", err);
    }
    if (meta.status === "exited") {
      inst.status = "exited";
    }
    return inst;
  }

  _setCreating(v) {
    const btn = this.root.querySelector("#termNewBtn");
    const emptyBtn = this.root.querySelector("#termEmptyNewBtn");
    if (btn) btn.disabled = v;
    if (emptyBtn) emptyBtn.disabled = v;
    if (btn) btn.style.opacity = v ? "0.5" : "";
    if (emptyBtn) emptyBtn.style.opacity = v ? "0.5" : "";
  }

  _onInstanceStatus(id, status, exitCode) {
    const meta = this.store.terminals.find(t => t.id === id);
    if (meta) {
      meta.status = status;
      if (status === "exited") meta.exitCode = exitCode;
    }
    this._renderTabs();
  }

  _renderTabs() {
    if (!this.tabsEl) return;
    this.tabsEl.innerHTML = "";
    for (const t of this.store.terminals) {
      const tab = document.createElement("div");
      tab.className = "terminal-tab" + (t.id === this.store.activeTerminalId ? " active" : "") + (t.status === "exited" ? " exited" : "");
      tab.dataset.tid = t.id;
      const dot = t.status === "running" || t.status === "connected" ? "●" : t.status === "exited" ? "○" : "◐";
      tab.innerHTML = `
        <span class="term-tab-dot">${dot}</span>
        <span class="term-tab-title" title="${t.title}">${t.title}${t.status === "exited" ? ` (${t.exitCode ?? ""})` : ""}</span>
        <button class="term-tab-close" title="Close" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
      `;
      tab.addEventListener("click", (e) => {
        if (e.target.closest(".term-tab-close")) return;
        this._switchTo(t.id);
      });
      tab.querySelector(".term-tab-close").addEventListener("click", (e) => {
        e.stopPropagation();
        this.closeTerminal(t.id);
      });
      tab.querySelector(".term-tab-title").addEventListener("dblclick", (e) => {
        e.stopPropagation();
        const nv = prompt("Rename terminal:", t.title);
        if (nv && nv.trim()) this.renameTerminal(t.id, nv.trim());
      });
      const menuBtn = document.createElement("button");
      menuBtn.className = "term-tab-menu-btn";
      menuBtn.innerHTML = "⋮";
      menuBtn.title = "Close others";
      menuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.closeOthers(t.id);
      });
      tab.appendChild(menuBtn);
      this.tabsEl.appendChild(tab);
    }
    this._showEmpty(this.store.terminals.length === 0);
  }

  _showEmpty(show) {
    if (!this.emptyEl) return;
    if (show) this.emptyEl.classList.remove("hidden");
    else this.emptyEl.classList.add("hidden");
    this.hostEl.style.display = show ? "none" : "block";
  }

  _switchTo(id) {
    if (!id) return;
    const prev = this.store.activeTerminalId;
    if (prev && this.instances.has(prev)) this.instances.get(prev).deactivate();
    this.store.activeTerminalId = id;
    const inst = this.instances.get(id);
    if (inst) inst.activate();
    saveStore(this.store);
    this._renderTabs();
  }

  toggle() {
    if (this.store.panelOpen) this.collapse();
    else this.expand();
  }

  async expand() {
    this.store.panelOpen = true;
    if (this.store.panelHeight < 100) this.store.panelHeight = this.store.previousPanelHeight || 260;
    this._applyState();
    saveStore(this.store);
    await this._nextFrame();
    if (this.store.terminals.length === 0) {
      await this.createNew();
    } else {
      const inst = this.instances.get(this.store.activeTerminalId);
      if (inst) { inst.fit(); setTimeout(() => inst.fit(), 80); }
    }
  }

  collapse() {
    if (this.store.maximized) {
      this.store.maximized = false;
      this.root.classList.remove("maximized");
    }
    this.store.previousPanelHeight = this.store.panelHeight;
    this.store.panelOpen = false;
    this._applyState();
    saveStore(this.store);
  }

  toggleMaximize() {
    if (!this.store.panelOpen) { this.expand(); return; }
    this.store.maximized = !this.store.maximized;
    if (this.store.maximized) {
      this.store.previousPanelHeight = this.store.panelHeight;
      this.root.style.height = "70vh";
      this.root.classList.add("maximized");
    } else {
      this.root.style.height = this.store.panelHeight + "px";
      this.root.classList.remove("maximized");
    }
    saveStore(this.store);
    const inst = this.instances.get(this.store.activeTerminalId);
    if (inst) setTimeout(() => inst.fit(), 100);
  }

  async createNew() {
    if (this._creating) return;
    this._creating = true;
    this._setCreating(true);
    if (!this.store.panelOpen) {
      this.store.panelOpen = true;
      this._applyState();
      await this._nextFrame();
    }
    this._showEmpty(false);
    await this._nextFrame();
    const instTmp = this.instances.get(this.store.activeTerminalId);
    let cols = 80, rows = 24;
    if (instTmp) { cols = instTmp.cols; rows = instTmp.rows; }
    try {
      const meta = await createTerminal({ profile: "bash", cols, rows });
      this.store.terminals.push(meta);
      this._renderTabs();
      await this._ensureInstance(meta);
      this._switchTo(meta.id);
      this._renderTabs();
      saveStore(this.store);
      const ni = this.instances.get(meta.id);
      if (ni) { ni.fit(); setTimeout(() => ni.fit(), 80); }
    } catch (e) {
      if (String(e.message).includes("429") || String(e.message).toLowerCase().includes("max terminals")) {
        const msg = "Terminal limit reached (10). Close a terminal first.";
        if (window.showFloatingNotification) window.showFloatingNotification(msg);
        else alert(msg);
        this._showEmpty(this.store.terminals.length === 0);
        return;
      }
      try {
        const m = await createTerminal({ profile: "sh", cols, rows });
        this.store.terminals.push(m);
        this._renderTabs();
        await this._ensureInstance(m);
        this._switchTo(m.id);
        this._renderTabs();
        saveStore(this.store);
      } catch (err) {
        const msg = "Failed to create terminal: " + (err.message || e.message);
        const host = this.hostEl;
        const div = document.createElement("div");
        div.style.cssText = "color:var(--error);padding:12px;font-family:monospace";
        div.textContent = msg;
        host.appendChild(div);
        setTimeout(() => { try { div.remove(); } catch {} }, 4000);
        if (window.showFloatingNotification) window.showFloatingNotification(msg);
        console.error(msg, err || e);
        this._showEmpty(this.store.terminals.length === 0);
      }
    } finally {
      this._creating = false;
      this._setCreating(false);
    }
  }

  async renameTerminal(id, title) {
    try {
      const updated = await renameTerminal(id, title);
      const t = this.store.terminals.find(x => x.id === id);
      if (t) t.title = updated.title;
      this._renderTabs();
    } catch {}
  }

  async closeTerminal(id) {
    const idx = this.store.terminals.findIndex(t => t.id === id);
    if (idx === -1) return;
    try { await deleteTerminal(id); } catch {}
    const inst = this.instances.get(id);
    if (inst) { inst.dispose(); this.instances.delete(id); const el = this.hostEl.querySelector(`[data-tid="${id}"]`); if (el) el.remove(); }
    this.store.terminals.splice(idx, 1);
    if (this.store.activeTerminalId === id) {
      if (this.store.terminals.length > 0) {
        const next = this.store.terminals[Math.min(idx, this.store.terminals.length - 1)];
        this.store.activeTerminalId = next.id;
        const ni = this.instances.get(next.id);
        if (ni) ni.activate();
      } else {
        this.store.activeTerminalId = null;
      }
    }
    saveStore(this.store);
    this._renderTabs();
    this._showEmpty(this.store.terminals.length === 0);
  }

  async closeOthers(keepId) {
    const others = this.store.terminals.filter(t => t.id !== keepId).map(t => t.id);
    for (const oid of others) await this.closeTerminal(oid);
  }

  _startDrag(e) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = this.root.getBoundingClientRect().height;
    const onMove = (ev) => {
      const dy = startY - ev.clientY;
      let nh = startH + dy;
      nh = Math.max(32, Math.min(window.innerHeight * 0.7, nh));
      if (nh <= 40) {
        this.store.panelOpen = false;
        this._applyState();
      } else {
        this.store.panelOpen = true;
        this.store.panelHeight = nh;
        this.root.style.height = nh + "px";
        this.root.classList.add("open");
        this.root.querySelector("#termBody").style.display = "flex";
      }
      const inst = this.instances.get(this.store.activeTerminalId);
      if (inst) inst.fit();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (this.store.panelOpen) {
        this.store.previousPanelHeight = this.store.panelHeight;
        saveStore(this.store);
      } else {
        saveStore(this.store);
      }
      this._applyState();
      const inst = this.instances.get(this.store.activeTerminalId);
      if (inst) inst.fit();
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }
}
