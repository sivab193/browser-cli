// snapshot.js
// Atomic DOM snapshot: produce an indexed table of visible, interactable controls.
// Returns a JSON-serializable array. Each entry carries enough identity for the
// executor to re-resolve the live node and verify it before acting.
//
// This runs inside the page via Playwright's page.evaluate. It must be a single
// expression that returns the table.

(() => {
  const MAX_TEXT = 120;

  function isVisible(el) {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (parseFloat(style.opacity || "1") === 0) return false;
    // At least partially within the viewport.
    const vw = window.innerWidth || document.documentElement.clientWidth;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    if (rect.bottom < 0 || rect.right < 0 || rect.top > vh || rect.left > vw) return false;
    return true;
  }

  function accessibleName(el) {
    // Best-effort accessible name. Not the full spec, but covers common cases.
    const aria = el.getAttribute("aria-label");
    if (aria && aria.trim()) return aria.trim();

    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const parts = labelledby
        .split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((n) => (n.innerText || n.textContent || "").trim());
      const joined = parts.join(" ").trim();
      if (joined) return joined;
    }

    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) {
        const t = (lbl.innerText || lbl.textContent || "").trim();
        if (t) return t;
      }
    }

    // Wrapping <label>
    const parentLabel = el.closest("label");
    if (parentLabel) {
      const t = (parentLabel.innerText || parentLabel.textContent || "").trim();
      if (t) return t;
    }

    const placeholder = el.getAttribute("placeholder");
    if (placeholder && placeholder.trim()) return placeholder.trim();

    const title = el.getAttribute("title");
    if (title && title.trim()) return title.trim();

    const alt = el.getAttribute("alt");
    if (alt && alt.trim()) return alt.trim();

    const txt = (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ");
    if (txt) return txt;

    const name = el.getAttribute("name");
    if (name) return name;

    return "";
  }

  function roleOf(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (["checkbox"].includes(type)) return "checkbox";
      if (["radio"].includes(type)) return "radio";
      if (["submit", "button", "reset", "image"].includes(type)) return "button";
      if (["range"].includes(type)) return "slider";
      return "textbox";
    }
    if (el.isContentEditable) return "textbox";
    return tag;
  }

  function valueOf(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === "select") {
      const opt = el.options[el.selectedIndex];
      return opt ? (opt.text || opt.value || "") : "";
    }
    if (tag === "input" || tag === "textarea") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "checkbox" || type === "radio") return el.checked ? "checked" : "unchecked";
      return el.value || "";
    }
    if (el.isContentEditable) return (el.innerText || "").trim();
    return "";
  }

  function optionsOf(el) {
    if (el.tagName.toLowerCase() !== "select") return null;
    return Array.from(el.options).map((o, i) => ({
      index: i,
      label: (o.text || o.value || "").trim().slice(0, MAX_TEXT),
      value: o.value,
    }));
  }

  const SELECTOR = [
    "a[href]",
    "button",
    "input:not([type=hidden])",
    "select",
    "textarea",
    "[role=button]",
    "[role=link]",
    "[role=checkbox]",
    "[role=radio]",
    "[role=tab]",
    "[role=menuitem]",
    "[role=option]",
    "[contenteditable=true]",
    "[onclick]",
  ].join(",");

  const seen = new Set();
  const nodes = Array.from(document.querySelectorAll(SELECTOR));
  const table = [];
  let idx = 0;

  for (const el of nodes) {
    if (seen.has(el)) continue;
    if (el.disabled) continue;
    if (!isVisible(el)) continue;
    seen.add(el);

    const role = roleOf(el);
    const name = accessibleName(el).slice(0, MAX_TEXT);
    const value = valueOf(el).slice(0, MAX_TEXT);
    if (!name && !value && role !== "textbox") continue;

    idx += 1;
    // Tag the node so the executor can re-find this exact element.
    const ref = "bcli-" + idx;
    el.setAttribute("data-bcli-ref", ref);

    const rect = el.getBoundingClientRect();
    table.push({
      index: idx,
      ref,
      role,
      name,
      value,
      options: optionsOf(el),
      tag: el.tagName.toLowerCase(),
      editable:
        role === "textbox" ||
        role === "combobox" ||
        el.isContentEditable === true,
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
    });
  }

  // Visible page text, trimmed, for DONE verification and context.
  const bodyText = (document.body ? document.body.innerText : "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 4000);

  return {
    url: location.href,
    title: document.title,
    elements: table,
    text: bodyText,
    scroll: { y: window.scrollY, maxY: document.body ? document.body.scrollHeight : 0, vh: window.innerHeight },
  };
})();
