import { createWebSocketUrl } from "./terminal-api.js";

export class TerminalInstance {
  constructor({ id, cols = 80, rows = 24, container }) {
    this.id = id;
    this.cols = cols;
    this.rows = rows;
    this.container = container;
    this.terminal = null;
    this.fitAddon = null;
    this.ws = null;
    this.status = "connecting";
    this.reconnectAttempts = 0;
    this.maxReconnect = 5;
    this._resizeTimer = null;
    this._disposed = false;
    this._onStatusChange = null;
  }

  async init(onStatus) {
    this._onStatusChange = onStatus;
    const Terminal = await TerminalInstance._loadXterm();
    const FitAddon = await TerminalInstance._loadFitAddon();
    this.terminal = new Terminal({
      fontFamily: "Fira Code, monospace",
      fontSize: 13,
      theme: {
        background: "#0e1322",
        foreground: "#f1f5f9",
        cursor: "#00f2fe",
        selectionBackground: "rgba(0,242,254,0.3)",
      },
      cursorBlink: true,
      convertEol: true,
      scrollback: 5000,
    });
    this.fitAddon = new FitAddon();
    this.terminal.loadAddon(this.fitAddon);
    this.terminal.open(this.container);
    try { this.fitAddon.fit(); } catch {}
    const dims = this.fitAddon.proposeDimensions();
    if (dims) { this.cols = dims.cols; this.rows = dims.rows; }
    this.terminal.onData((data) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send(JSON.stringify({ type: "input", data })); } catch {}
      }
    });
    this.terminal.onResize(({ cols, rows }) => {
      this.cols = cols; this.rows = rows;
      this._debouncedResize();
    });
    this._observeResize();
    this.connect();
  }


  static _xtermPromise = null;
  static _fitPromise = null;
  static _loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("failed to load " + src));
      document.head.appendChild(s);
    });
  }
  static async _loadXterm() {
    if (globalThis.Terminal) return globalThis.Terminal;
    if (!TerminalInstance._xtermPromise) {
      TerminalInstance._xtermPromise = TerminalInstance._loadScript("/static/vendor/xterm/xterm.js").then(() => {
        if (globalThis.Terminal) return globalThis.Terminal;
        if (globalThis.window && globalThis.window.Terminal) return globalThis.window.Terminal;
        throw new Error("Terminal not loaded");
      });
    }
    return TerminalInstance._xtermPromise;
  }
  static async _loadFitAddon() {
    const unwrap = (m) => (m && m.FitAddon ? m.FitAddon : m);
    if (globalThis.FitAddon) {
      const u = unwrap(globalThis.FitAddon);
      if (typeof u === "function") return u;
    }
    if (globalThis.window && globalThis.window.FitAddon) {
      const u = unwrap(globalThis.window.FitAddon);
      if (typeof u === "function") return u;
    }
    if (!TerminalInstance._fitPromise) {
      TerminalInstance._fitPromise = TerminalInstance._loadScript("/static/vendor/xterm/addon-fit.js").then(() => {
        let m = globalThis.FitAddon || (globalThis.window && globalThis.window.FitAddon);
        m = unwrap(m);
        if (!m || typeof m !== "function") throw new Error("FitAddon not loaded");
        return m;
      });
    }
    return TerminalInstance._fitPromise;
  }

  _observeResize() {
    if (typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver(() => {
        clearTimeout(this._resizeTimer);
        this._resizeTimer = setTimeout(() => { this.fit(); }, 100);
      });
      this._ro.observe(this.container);
    }
    window.addEventListener("resize", this._onWinResize);
  }
  _onWinResize = () => {
    clearTimeout(this._resizeTimer);
    this._resizeTimer = setTimeout(() => this.fit(), 150);
  };

  fit() {
    if (this._disposed || !this.fitAddon || !this.terminal) return;
    try {
      this.fitAddon.fit();
      const d = this.fitAddon.proposeDimensions();
      if (d && (d.cols !== this.cols || d.rows !== this.rows)) {
        this.cols = d.cols; this.rows = d.rows;
        this._debouncedResize();
      }
    } catch {}
  }

  _debouncedResize() {
    clearTimeout(this._resizeTimer);
    this._resizeTimer = setTimeout(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send(JSON.stringify({ type: "resize", cols: this.cols, rows: this.rows })); } catch {}
      }
    }, 200);
  }

  connect() {
    if (this._disposed) return;
    if (this.ws) { try { this.ws.close(); } catch {} }
    const url = createWebSocketUrl(this.id);
    const ws = new WebSocket(url);
    this.ws = ws;
    this.status = "connecting";
    this._emitStatus();
    ws.onopen = () => {
      this.status = "connected";
      this.reconnectAttempts = 0;
      this._emitStatus();
      try { ws.send(JSON.stringify({ type: "resize", cols: this.cols, rows: this.rows })); } catch {}
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "output" && typeof msg.data === "string") {
        this.terminal.write(msg.data);
      } else if (msg.type === "status") {
        this.status = msg.status;
        this._emitStatus();
      } else if (msg.type === "exit") {
        this.status = "exited";
        this._emitStatus(msg.exitCode);
        this.terminal.write(`\r\n\x1b[90m[exited ${msg.exitCode ?? ""}]\x1b[0m\r\n`);
      } else if (msg.type === "error") {
        this.terminal.write(`\r\n\x1b[31m${msg.message}\x1b[0m\r\n`);
      }
    };
    ws.onclose = () => {
      if (this._disposed) return;
      if (this.status !== "exited") {
        this.status = "disconnected";
        this._emitStatus();
        this._scheduleReconnect();
      }
    };
    ws.onerror = () => {};
  }

  _scheduleReconnect() {
    if (this._disposed || this.status === "exited") return;
    if (this.reconnectAttempts >= this.maxReconnect) return;
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 8000);
    this.reconnectAttempts++;
    setTimeout(() => this.connect(), delay);
  }

  reconnect() {
    this.reconnectAttempts = 0;
    this.connect();
  }

  _emitStatus(exitCode) {
    if (this._onStatusChange) this._onStatusChange(this.status, exitCode);
  }

  activate() {
    if (this.container) this.container.style.display = "block";
    setTimeout(() => this.fit(), 50);
    try { this.terminal.focus(); } catch {}
  }
  deactivate() {
    if (this.container) this.container.style.display = "none";
  }
  dispose() {
    this._disposed = true;
    clearTimeout(this._resizeTimer);
    if (this._ro) try { this._ro.disconnect(); } catch {}
    window.removeEventListener("resize", this._onWinResize);
    if (this.ws) try { this.ws.close(); } catch {}
    if (this.terminal) try { this.terminal.dispose(); } catch {}
  }
}
