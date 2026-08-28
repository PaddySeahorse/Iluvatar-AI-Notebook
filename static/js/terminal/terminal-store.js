const LS_KEY = "iluvatar_terminal_state_v1";

const defaults = {
  panelOpen: false,
  panelHeight: 260,
  previousPanelHeight: 260,
  maximized: false,
  activeTerminalId: null,
  terminals: [],
};

export function loadStore() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return { ...defaults };
    const parsed = JSON.parse(raw);
    return {
      panelOpen: !!parsed.panelOpen,
      panelHeight: typeof parsed.panelHeight === "number" ? parsed.panelHeight : defaults.panelHeight,
      previousPanelHeight: typeof parsed.previousPanelHeight === "number" ? parsed.previousPanelHeight : defaults.panelHeight,
      maximized: !!parsed.maximized,
      activeTerminalId: parsed.activeTerminalId || null,
      terminals: Array.isArray(parsed.terminals) ? parsed.terminals : [],
    };
  } catch { return { ...defaults }; }
}

export function saveStore(s) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      panelOpen: s.panelOpen,
      panelHeight: s.panelHeight,
      previousPanelHeight: s.previousPanelHeight,
      maximized: s.maximized,
      activeTerminalId: s.activeTerminalId,
    }));
  } catch {}
}

export function createStore() {
  const store = loadStore();
  store.groups = [{ id: "group_1", terminalIds: store.terminals.map(t => t.id), sizes: [1] }];
  return store;
}

export function persistTerminalList(store) {
  try {
    const raw = localStorage.getItem(LS_KEY);
    const obj = raw ? JSON.parse(raw) : {};
    obj.terminals = store.terminals;
    obj.activeTerminalId = store.activeTerminalId;
    localStorage.setItem(LS_KEY, JSON.stringify(obj));
  } catch {}
}

export function nextTitle(terminals, profile = "bash") {
  const nums = terminals.filter(t => t.profile === profile).length;
  return `${profile} ${nums + 1}`;
}
