"""JavaScript snippets injected into the pywebview page for DOM inspection and control."""

INIT_SCRIPT = r"""
(function() {
  if (window.__pywebviewMcp) return;
  window.__pywebviewMcp = {
    nextId: 0,
    ids: new WeakMap(),
    lastActivity: Date.now(),
    pywebviewReady: !!(window.pywebview && window.pywebview.api),
  };
  const obs = new MutationObserver(() => {
    window.__pywebviewMcp.lastActivity = Date.now();
  });
  obs.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, characterData: true
  });
  window.addEventListener('pywebviewready', () => {
    window.__pywebviewMcp.pywebviewReady = true;
    window.__pywebviewMcp.lastActivity = Date.now();
  });
})();
"""

MCP_ID_FN = r"""
function __mcpId(el) {
  if (!el || el.nodeType !== 1) return null;
  const s = window.__pywebviewMcp;
  if (!s.ids.has(el)) {
    const id = String(s.nextId++);
    s.ids.set(el, id);
    el.setAttribute('data-mcp-id', id);
  }
  return s.ids.get(el);
}
"""

ELEMENT_SUMMARY_FN = r"""
function __mcpElementSummary(el, depth, maxDepth) {
  if (!el || el.nodeType !== 1) return null;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const visible = style.display !== 'none' && style.visibility !== 'hidden'
    && rect.width > 0 && rect.height > 0;
  const text = (el.innerText || el.textContent || '').trim().slice(0, 120) || null;
  const d = {
    id: __mcpId(el),
    tag: el.tagName.toLowerCase(),
    html_id: el.id || null,
    class: el.className && typeof el.className === 'string' ? el.className : null,
    role: el.getAttribute('role') || null,
    name: el.getAttribute('name') || null,
    type: el.getAttribute('type') || null,
    visible,
    enabled: !el.disabled,
    bounds: {
      x: Math.round(rect.x), y: Math.round(rect.y),
      w: Math.round(rect.width), h: Math.round(rect.height),
    },
    text,
  };
  if (depth < maxDepth) {
    const kids = [];
    for (const c of el.children) {
      if (c.nodeType === 1) {
        const child = __mcpElementSummary(c, depth + 1, maxDepth);
        if (child) kids.push(child);
      }
    }
    if (kids.length) d.children = kids;
  }
  return d;
}
"""

DOM_TREE = INIT_SCRIPT + MCP_ID_FN + ELEMENT_SUMMARY_FN + r"""
(function() {
  return { elements: [__mcpElementSummary(document.body, 0, 8)] };
})()
"""

ELEMENT_INFO = INIT_SCRIPT + MCP_ID_FN + ELEMENT_SUMMARY_FN + r"""
(function() {
  const id = %s;
  const el = document.querySelector('[data-mcp-id="' + id + '"]');
  if (!el) return { error: 'Element ' + id + ' not found' };
  const info = __mcpElementSummary(el, 0, 2);
  info.value = el.value !== undefined ? el.value : null;
  info.checked = el.checked !== undefined ? !!el.checked : null;
  info.href = el.href || null;
  info.aria_label = el.getAttribute('aria-label') || null;
  return info;
})()
"""

FIND_ELEMENTS = INIT_SCRIPT + MCP_ID_FN + ELEMENT_SUMMARY_FN + r"""
(function() {
  const criteria = %s;
  const results = [];
  const walk = (el) => {
    if (!el || el.nodeType !== 1) return;
    let ok = true;
    if (criteria.selector) {
      try { ok = el.matches(criteria.selector); } catch (e) { ok = false; }
    }
    if (ok && criteria.tag) ok = el.tagName.toLowerCase() === criteria.tag.toLowerCase();
    if (ok && criteria.html_id) ok = el.id === criteria.html_id;
    if (ok && criteria.role) ok = (el.getAttribute('role') || '') === criteria.role;
    if (ok && criteria.text) {
      const t = (el.innerText || el.textContent || '').toLowerCase();
      ok = t.includes(String(criteria.text).toLowerCase());
    }
    if (ok && criteria.visible !== undefined) {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const vis = style.display !== 'none' && style.visibility !== 'hidden'
        && rect.width > 0 && rect.height > 0;
      ok = vis === criteria.visible;
    }
    if (ok) results.push(__mcpElementSummary(el, 0, 0));
    for (const c of el.children) walk(c);
  };
  walk(document.body);
  return { elements: results, count: results.length };
})()
"""

CLICK_ELEMENT = INIT_SCRIPT + MCP_ID_FN + r"""
(function() {
  const id = %s;
  const opts = %s;
  const el = document.querySelector('[data-mcp-id="' + id + '"]');
  if (!el) return { error: 'Element ' + id + ' not found' };
  el.focus();
  const rect = el.getBoundingClientRect();
  const x = opts.x !== undefined ? rect.left + opts.x : rect.left + rect.width / 2;
  const y = opts.y !== undefined ? rect.top + opts.y : rect.top + rect.height / 2;
  const btn = opts.button === 'right' ? 2 : (opts.button === 'middle' ? 1 : 0);
  const events = opts.double ? ['mousedown', 'mouseup', 'click', 'mousedown', 'mouseup', 'click', 'dblclick']
    : ['mousedown', 'mouseup', 'click'];
  for (const type of events) {
    el.dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: btn,
    }));
  }
  window.__pywebviewMcp.lastActivity = Date.now();
  return { ok: true };
})()
"""

CLICK_COORD = INIT_SCRIPT + r"""
(function() {
  const opts = %s;
  const el = document.elementFromPoint(opts.x, opts.y);
  if (!el) return { error: 'No element at coordinates' };
  const btn = opts.button === 'right' ? 2 : (opts.button === 'middle' ? 1 : 0);
  el.dispatchEvent(new MouseEvent('click', {
    bubbles: true, cancelable: true, view: window,
    clientX: opts.x, clientY: opts.y, button: btn,
  }));
  window.__pywebviewMcp.lastActivity = Date.now();
  return { ok: true, element: el.tagName.toLowerCase() };
})()
"""

TYPE_TEXT = INIT_SCRIPT + MCP_ID_FN + r"""
(function() {
  const id = %s;
  const text = %s;
  const el = document.querySelector('[data-mcp-id="' + id + '"]');
  if (!el) return { error: 'Element ' + id + ' not found' };
  el.focus();
  if ('value' in el) {
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (el.isContentEditable) {
    el.textContent = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }
  window.__pywebviewMcp.lastActivity = Date.now();
  return { ok: true };
})()
"""

PRESS_KEY = INIT_SCRIPT + r"""
(function() {
  const key = %s;
  const target = document.activeElement || document.body;
  const map = {
    enter: 'Enter', return: 'Enter', escape: 'Escape', tab: 'Tab',
    backspace: 'Backspace', delete: 'Delete',
    up: 'ArrowUp', down: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight',
    space: ' ', home: 'Home', end: 'End', pageup: 'PageUp', pagedown: 'PageDown',
    f1: 'F1', f2: 'F2', f3: 'F3', f4: 'F4', f5: 'F5', f6: 'F6',
  };
  const k = map[key.toLowerCase()] || key;
  const opts = { key: k, bubbles: true, cancelable: true };
  target.dispatchEvent(new KeyboardEvent('keydown', opts));
  target.dispatchEvent(new KeyboardEvent('keyup', opts));
  if (k.length === 1 && target !== document.body) {
    if ('value' in target) {
      target.value += k;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  window.__pywebviewMcp.lastActivity = Date.now();
  return { ok: true };
})()
"""

SCROLL = INIT_SCRIPT + MCP_ID_FN + r"""
(function() {
  const opts = %s;
  let el = null;
  if (opts.element_id) {
    el = document.querySelector('[data-mcp-id="' + opts.element_id + '"]');
  }
  if (!el) el = document.scrollingElement || document.documentElement;
  el.scrollBy(opts.dx || 0, opts.dy || 0);
  window.__pywebviewMcp.lastActivity = Date.now();
  return { ok: true };
})()
"""

LIST_ACTIONS = INIT_SCRIPT + MCP_ID_FN + r"""
(function() {
  const selectors = 'button, a[href], input[type=button], input[type=submit], [role=button], [role=menuitem], [role=tab]';
  const actions = [];
  for (const el of document.querySelectorAll(selectors)) {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (style.display === 'none' || rect.width === 0) continue;
    const text = (el.innerText || el.getAttribute('aria-label') || el.value || '').trim();
    actions.push({
      id: __mcpId(el),
      tag: el.tagName.toLowerCase(),
      html_id: el.id || null,
      text: text || null,
      enabled: !el.disabled,
      href: el.href || null,
    });
  }
  return { actions, count: actions.length };
})()
"""

TRIGGER_ACTION = INIT_SCRIPT + MCP_ID_FN + r"""
(function() {
  const criteria = %s;
  const selectors = 'button, a[href], input[type=button], input[type=submit], [role=button]';
  for (const el of document.querySelectorAll(selectors)) {
    const text = (el.innerText || el.getAttribute('aria-label') || el.value || '').trim();
    const matchName = criteria.name && el.id === criteria.name;
    const matchText = criteria.text && text === criteria.text;
    if (matchName || matchText) {
      if (el.disabled) return { error: 'Action disabled: ' + (criteria.name || criteria.text) };
      el.click();
      window.__pywebviewMcp.lastActivity = Date.now();
      return { ok: true, triggered: criteria.name || criteria.text };
    }
  }
  return { error: 'Action not found: ' + (criteria.name || criteria.text) };
})()
"""

READY_STATE = INIT_SCRIPT + r"""
(function() {
  const s = window.__pywebviewMcp || { lastActivity: Date.now(), pywebviewReady: false };
  const quietMs = %s;
  const idleMs = Date.now() - s.lastActivity;
  const domReady = document.readyState === 'complete';
  const body = document.body;
  const hasContent = !!(body && body.children.length > 0);
  const ready = domReady && hasContent && s.pywebviewReady && idleMs >= quietMs;
  return {
    ready,
    dom_ready: domReady,
    pywebview_ready: s.pywebviewReady,
    has_content: hasContent,
    idle_ms: idleMs,
    title: document.title || null,
    url: location.href || null,
  };
})()
"""

IDLE_STATE = INIT_SCRIPT + r"""
(function() {
  const s = window.__pywebviewMcp || { lastActivity: Date.now() };
  return { idle_ms: Date.now() - s.lastActivity };
})()
"""

APP_STATE = INIT_SCRIPT + MCP_ID_FN + r"""
(function() {
  const active = document.activeElement;
  return {
    title: document.title || null,
    url: location.href || null,
    ready_state: document.readyState,
    pywebview_ready: !!(window.__pywebviewMcp && window.__pywebviewMcp.pywebviewReady),
    focus_element: active && active.nodeType === 1 ? __mcpId(active) : null,
    focus_tag: active && active.nodeType === 1 ? active.tagName.toLowerCase() : null,
    platform: (window.pywebview && window.pywebview.platform) || null,
  };
})()
"""
