export async function createTerminal({ profile = "bash", cwd = ".", cols = 80, rows = 24 } = {}) {
  const res = await fetch("/api/terminals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile, cwd, cols, rows }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || `create failed ${res.status}`);
  return data;
}
export async function listTerminals() {
  const res = await fetch("/api/terminals");
  if (!res.ok) throw new Error("list failed");
  return res.json();
}
export async function renameTerminal(id, title) {
  const res = await fetch(`/api/terminals/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || "rename failed");
  return data;
}
export async function deleteTerminal(id) {
  const res = await fetch(`/api/terminals/${encodeURIComponent(id)}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || "delete failed");
  return data;
}
export function createWebSocketUrl(terminalId) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const host = location.host;
  const base = location.pathname.replace(/\/[^/]*$/, "");
  let prefix = "";
  if (base && base !== "/" && !location.pathname.endsWith("/")) {
    prefix = base;
  } else if (base && base !== "/") {
    prefix = base.replace(/\/$/, "");
  }
  return `${proto}//${host}${prefix}/ws/terminals/${encodeURIComponent(terminalId)}`;
}
export function parseWsPath(url) {
  try {
    const u = new URL(url);
    return u.pathname;
  } catch { return url; }
}
