export function bindTerminalShortcuts(panel) {
  document.addEventListener("keydown", (e) => {
    const isMac = navigator.platform.toUpperCase().indexOf("MAC") >= 0;
    const mod = isMac ? e.metaKey : e.ctrlKey;
    if (mod && e.key === "`") {
      const active = document.activeElement;
      const isInput = active && (active.tagName === "TEXTAREA" || active.tagName === "INPUT" || active.isContentEditable);
      if (isInput && active.closest && active.closest(".terminal-instance")) return;
      e.preventDefault();
      panel.toggle();
    }
  });
}
