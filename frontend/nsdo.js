/**
 * NSDO — Nigerian Student Diaspora Observatory
 * Shared API client and UI utilities
 *
 * All data comes from the live FastAPI backend at /api/*.
 * No mock data is used in production code; empty/error states are explicit.
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const API = window.NSDO_API_BASE ?? '';   // same-origin by default; override in dev

// ---------------------------------------------------------------------------
// Auth helpers — token stored in sessionStorage (cleared on tab/window close)
// ---------------------------------------------------------------------------
const auth = {
  getToken: () => sessionStorage.getItem('nsdo_token') || null,
  setToken: (t) => { sessionStorage.setItem('nsdo_token', t); sessionStorage.setItem('nsdo_token_at', Date.now()); },
  clearToken: () => { sessionStorage.removeItem('nsdo_token'); sessionStorage.removeItem('nsdo_token_at'); sessionStorage.removeItem('nsdo_role'); },
  isSignedIn: () => !!sessionStorage.getItem('nsdo_token'),
  getRole: () => sessionStorage.getItem('nsdo_role') || null,
  setRole: (r) => sessionStorage.setItem('nsdo_role', r),
  isAdmin: () => sessionStorage.getItem('nsdo_role') === 'admin',
  // Returns the Authorization header value, or an empty object if not signed in.
  // Decision C: GET endpoints work without auth; only write ops need the header.
  header: () => {
    const t = sessionStorage.getItem('nsdo_token');
    return t ? { 'Authorization': `Bearer ${t}` } : {};
  },
  signOut: () => {
    auth.clearToken();
    window.location.href = 'login.html';
  },
};

// ---------------------------------------------------------------------------
// API client — thin fetch wrapper, always returns {ok, data, error, status}
// Automatically sends Bearer token if present in sessionStorage.
// ---------------------------------------------------------------------------
async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(`${API}${path}`, {
      headers: { 'Accept': 'application/json', ...auth.header(), ...options.headers },
      ...options,
    });
    const data = res.headers.get('content-type')?.includes('application/json')
      ? await res.json()
      : await res.text();
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, error: err.message, data: null };
  }
}

async function apiFormData(path, formData, method = 'POST') {
  try {
    const res = await fetch(`${API}${path}`, {
      method,
      body: formData,
      headers: { ...auth.header() },  // let browser set Content-Type for multipart
    });
    const data = res.headers.get('content-type')?.includes('application/json')
      ? await res.json()
      : await res.text();
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, error: err.message, data: null };
  }
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
const fmt = {
  number: (n) => n == null ? '—' : Number(n).toLocaleString(),
  date: (d) => d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—',
  datetime: (d) => d ? new Date(d).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—',
  tier: (t) => ({
    official_primary:   'Official Primary',
    official_secondary: 'Official Secondary',
    credible_secondary: 'Credible Secondary',
    unverified:         'Unverified',
  })[t] ?? t,
  orgType: (t) => ({
    national_statistics_agency: 'National Statistics Agency',
    international_organization: 'International Organization',
    government_department:      'Government Department',
    ngo_or_press:               'NGO / Press',
    secondary_aggregator:       'Secondary Aggregator',
  })[t] ?? t,
};

// ---------------------------------------------------------------------------
// HTML helpers — safe attribute/text helpers (no innerHTML with user data)
// ---------------------------------------------------------------------------
function el(tag, attrs = {}, ...children) {
  const elem = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') elem.className = v;
    else if (k === 'style') Object.assign(elem.style, v);
    else if (k.startsWith('data-')) elem.dataset[k.slice(5)] = v;
    else if (k in elem) elem[k] = v;
    else elem.setAttribute(k, v);
  }
  for (const child of children) {
    if (child == null) continue;
    elem.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return elem;
}

function tierBadge(tier) {
  return el('span', { class: `tier tier-${tier}` }, fmt.tier(tier));
}

function statusBadge(status) {
  return el('span', { class: `status-badge status-${status}` }, status);
}

function countryChip(country) {
  return el('span', { class: 'country-chip' }, country);
}

// ---------------------------------------------------------------------------
// State rendering helpers
// ---------------------------------------------------------------------------
function renderLoading(container) {
  container.innerHTML = '';
  container.appendChild(
    el('div', { class: 'state-container' },
      el('div', { class: 'spinner' }),
      el('p', { class: 'state-body' }, 'Loading…')
    )
  );
}

function renderEmpty(container, title, body, action = null) {
  container.innerHTML = '';
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg  = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('class', 'state-icon');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.5');
  const path = document.createElementNS(svgNS, 'path');
  // Inbox / empty-tray icon
  path.setAttribute('d', 'M3 7h18M3 12h18M3 17h12');
  path.setAttribute('stroke-linecap', 'round');
  svg.appendChild(path);

  const children = [svg,
    el('p', { class: 'state-title' }, title),
    el('p', { class: 'state-body' }, body),
  ];
  if (action) children.push(action);
  container.appendChild(el('div', { class: 'state-container' }, ...children));
}

function renderError(container, message) {
  container.innerHTML = '';
  container.appendChild(
    el('div', { class: 'alert alert-error', style: { margin: '24px 0' } },
      el('strong', {}, 'Could not load data — '),
      message
    )
  );
}

// ---------------------------------------------------------------------------
// Nav: set active link + check API health
// ---------------------------------------------------------------------------
async function initNav(activePage) {
  // Mark active nav link
  document.querySelectorAll('.nav-link').forEach(a => {
    if (a.dataset.page === activePage) a.classList.add('active');
  });

  // Health check
  const dot  = document.getElementById('nav-status-dot');
  const text = document.getElementById('nav-status-text');
  if (!dot) return;

  const { ok, data } = await apiFetch('/api/health');
  if (ok && data?.status === 'ok') {
    dot.className = 'nav-status-dot ok';
    text.textContent = 'API online';
  } else {
    dot.className = 'nav-status-dot err';
    text.textContent = 'API offline';
  }
}

// ---------------------------------------------------------------------------
// Nav HTML (injected by each page)
// ---------------------------------------------------------------------------
function navHTML(activePage) {
  const links = [
    { page: 'dashboard', href: 'index.html',   label: 'Dashboard',    icon: dashIcon() },
    { page: 'datasets',  href: 'datasets.html', label: 'Datasets',     icon: dbIcon() },
    { page: 'sources',   href: 'sources.html',  label: 'Sources',      icon: srcIcon() },
    { page: 'analytics', href: 'analytics.html',label: 'Analytics',    icon: chartIcon() },
    { page: 'import',    href: 'import.html',   label: 'Import',       icon: upIcon() },
    { page: 'docs',      href: 'docs.html',     label: 'Methodology',  icon: docIcon() },
    { page: 'admin',     href: 'admin.html',    label: 'Admin',        icon: adminIcon(), adminOnly: true },
  ];
  return `
<nav class="site-nav">
  <div class="nav-inner">
    <div class="nav-brand">
      <span class="nav-brand-mark">NSDO</span>
      <span class="nav-brand-name">Nigerian Student Diaspora Observatory</span>
    </div>
    <div class="nav-links">
      ${links.filter(l => !l.adminOnly || auth.isAdmin()).map(l => `
        <a class="nav-link${activePage === l.page ? ' active' : ''}" href="${l.href}" data-page="${l.page}">
          ${l.icon}<span>${l.label}</span>
        </a>`).join('')}
    </div>
    <div class="nav-status">
<a href="login.html" id="nav-signin-link" style="color:inherit;text-decoration:none;margin-right:14px;font-size:13px;">Sign in</a>
<span class="nav-status-dot" id="nav-status-dot"></span>
<span id="nav-status-text">Checking…</span>
</div>
  </div>
</nav>`;
}

// SVG icons (inline, no external deps)
function dashIcon() { return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1" y="1" width="5" height="5" rx="1"/><rect x="10" y="1" width="5" height="5" rx="1"/><rect x="1" y="10" width="5" height="5" rx="1"/><rect x="10" y="10" width="5" height="5" rx="1"/></svg>`; }
function dbIcon()   { return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><ellipse cx="8" cy="4" rx="6" ry="2.5"/><path d="M2 4v8c0 1.38 2.69 2.5 6 2.5s6-1.12 6-2.5V4"/><path d="M2 8c0 1.38 2.69 2.5 6 2.5s6-1.12 6-2.5"/></svg>`; }
function srcIcon()  { return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 1.5"/></svg>`; }
function chartIcon(){ return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 12l4-4 3 2 4-5 3 2"/><path d="M1 14h14"/></svg>`; }
function upIcon()   { return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 10V3m0 0L5 6m3-3l3 3"/><path d="M3 11v1a2 2 0 002 2h6a2 2 0 002-2v-1"/></svg>`; }
function docIcon()  { return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 1H4a1 1 0 00-1 1v12a1 1 0 001 1h8a1 1 0 001-1V5L9 1z"/><path d="M9 1v4h4"/><path d="M5 8h6M5 11h4"/></svg>`; }
function adminIcon(){ return `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1l1.5 3h3l-2.5 2 1 3L8 7.5 5 9l1-3L3.5 4h3z"/><path d="M8 11v4M5 13h6"/></svg>`; }

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------
window.NSDO = { apiFetch, apiFormData, fmt, el, tierBadge, statusBadge,
  countryChip, renderLoading, renderEmpty, renderError, initNav, navHTML, auth };
