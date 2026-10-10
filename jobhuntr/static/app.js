"use strict";
/* JobHuntr front end — plain JS, no build step. Talks to the Flask API in web.py. */

const STATUSES = ["applied", "interviewing", "offer", "rejected", "ghosted", "withdrawn"];
const BOARD = ["applied", "interviewing", "offer", "rejected", "ghosted"];
const MAX_COMPARE = 4;
const CLIENT_ID = Math.random().toString(36).slice(2);  // identifies this window to the server
const PAGE_SIZE = 150;

const ICON = {
  recruiter: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/></svg>',
  star: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/></svg>',
  starOn: '<svg class="i" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/></svg>',
  hide: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.9 17.9A10 10 0 0 1 12 20c-7 0-10-8-10-8a18 18 0 0 1 5.1-5.9M9.9 4.2A9 9 0 0 1 12 4c7 0 10 8 10 8a18 18 0 0 1-2.2 3.2M1 1l22 22"/></svg>',
  show: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  chevron: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>',
  external: '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>',
};

/* ------------------------------------------------------------------ state */
const S = {
  view: "jobs",
  searches: [],
  searchId: null,
  jobs: [],
  shown: PAGE_SIZE,
  expanded: new Set(),
  details: new Map(),          // job id -> full job (with description)
  detailErrors: new Map(),     // job id -> message, shown with a Retry button
  reading: new Set(),          // job ids whose description is being fetched right now
  autoRead: new Set(),         // compare view auto-reads each description at most once
  ai: new Map(),               // job id -> {loading, text, error} from AI tailoring
  compare: new Set(load("compare", [])),
  tracker: null,
  settings: null,
  crawl: { running: false },
  loading: false,
  loadToken: 0,                // ignores responses from searches the user has already clicked away from
  jobCache: new Map(),         // search id -> jobs, so switching tabs is instant
  filters: load("filtersBySearch", {}),
};

// Filters are kept per search, so a track chip picked in one search can't hide everything in another.
const FILTER_DEFAULTS = { q: "", tracks: [], category: "", onlyNew: false, hideSenior: true, localOnly: false,
                          starred: false, showHidden: false, noActiveClear: false, sort: "best" };
Object.defineProperty(S, "f", {
  get() {
    const key = S.searchId ?? "none";
    if (!S.filters[key]) {
      const mode = S.searches.find(s => s.id === S.searchId)?.mode;
      S.filters[key] = { ...FILTER_DEFAULTS, hideSenior: mode === "it" };
    }
    return S.filters[key];
  },
});
const saveFilters = () => save("filtersBySearch", S.filters);
const NARROWING = ["q", "tracks", "category", "onlyNew", "localOnly", "starred", "noActiveClear"];
const activeFilterCount = f => NARROWING.filter(k => Array.isArray(f[k]) ? f[k].length : f[k]).length;

function load(key, dflt) { try { return JSON.parse(localStorage.getItem("jh." + key)) ?? dflt; } catch { return dflt; } }
function save(key, val) { try { localStorage.setItem("jh." + key, JSON.stringify(val)); } catch { /* storage off */ } }

/* ---------------------------------------------------------------- helpers */
const $ = (sel, root = document) => root.querySelector(sel);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = () => $("#view");

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  // Never wait forever: a request that hangs would leave the screen stuck on "Loading…"
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout || 45000);
  init.signal = ctrl.signal;
  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    if (err.name === "AbortError") throw new Error("The request took too long. Try again.");
    connectionLost();
    throw new Error("Can't reach the JobHuntr server");
  } finally {
    clearTimeout(timer);
  }
  connectionOk();
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* Connection banner: shown if the local server stops answering; retries until it's back. */
let offline = false, retryTimer = null;
function connectionLost() {
  if (offline) return;
  offline = true;
  const bar = document.createElement("div");
  bar.className = "offline";
  bar.innerHTML = `<b>Lost connection to JobHuntr.</b> Reconnecting… If this doesn't clear, close this window and open JobHuntr again.`;
  document.body.prepend(bar);
  const retry = async () => {
    try { await fetch(`/api/ping?client=${CLIENT_ID}`, { method: "POST" }); connectionOk(true); }
    catch { retryTimer = setTimeout(retry, 3000); }
  };
  retryTimer = setTimeout(retry, 3000);
}
function connectionOk(reload = false) {
  if (!offline) return;
  offline = false; clearTimeout(retryTimer);
  document.querySelector(".offline")?.remove();
  if (reload) { toast("Reconnected"); refreshAll(); }
}

let toastTimer;
function toast(msg) {
  let el = $(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.append(el); }
  el.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 3200);
}

function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts.replace(" ", "T"));
  return isNaN(d) ? ts : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function ago(ts) {
  if (!ts) return "never";
  const mins = Math.round((Date.now() - new Date(ts.replace(" ", "T"))) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
}
const isRemote = j => /remote|telework|work from home|\bhome\b/i.test(j.location) && !(S.areaRx && S.areaRx.test(j.location));
const isActiveClear = j => j.facts ? j.facts.clearance === "Active required" : j.tags.includes("Clearance");

function recruiterBadge(f) {
  if (!f || !f.recruiter) return "";
  const r = f.recruiter;
  const tip = ["Recruiter / contact listed", r.name, r.email, r.snippet].filter(Boolean).join("\n");
  return `<span class="recruiter" title="${esc(tip)}" aria-label="Recruiter listed">${ICON.recruiter}</span>`;
}

function matchTag(m) {
  if (!m) return "";
  const cls = m.score >= 60 ? "match-hi" : m.score >= 35 ? "match-mid" : "match-lo";
  return `<span class="tag ${cls}" title="Your resume covers ${m.have.length} of ${m.have.length + m.missing.length} skills this posting mentions">${m.score}% match</span>`;
}

function skillsHtml(m) {
  if (!m) return "";
  return `<div style="margin-bottom:10px"><dt style="font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint)">Resume match · ${m.score}%</dt>
    <div class="skill-list">${m.have.map(s => `<span class="skill have" title="On your resume">✓ ${esc(s)}</span>`).join("")}
    ${m.missing.map(s => `<span class="skill miss" title="Not on your resume">${esc(s)}</span>`).join("")}</div></div>`;
}

function similarHtml(j) {
  if (!j.similar?.length) return "";
  return `<div style="margin-bottom:10px"><dt style="font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint)">Also posted as</dt>
    <ul class="similar-list">${j.similar.map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.location)}</a>${x.posted ? ` <span class="sub">· ${esc(x.posted)}</span>` : ""}</li>`).join("")}</ul></div>`;
}

function aiHtml(j) {
  const out = S.ai.get(j.id);
  return `<div class="ai-bar"><span class="sub">AI help:</span>
      <button class="btn small" data-act="ai" data-task="cover_letter">Cover letter</button>
      <button class="btn small" data-act="ai" data-task="bullets">Resume bullets</button>
      <button class="btn small" data-act="ai" data-task="interview">Interview prep</button>
      ${out?.text ? '<button class="btn small ghost" data-act="ai-copy">Copy</button>' : ""}</div>
    ${out ? `<div class="ai-out">${out.loading ? "Writing… (this can take up to a minute)" : esc(out.error || out.text)}</div>` : ""}`;
}

function factTags(f) {
  if (!f) return "";
  const t = [];
  if (f.clearance === "Active required") t.push('<span class="tag bad">Active clearance req.</span>');
  else if (f.clearance === "Can obtain (sponsored)") t.push('<span class="tag good">Clearance sponsored</span>');
  if (f.pay) t.push(`<span class="tag good">${esc(f.pay.text)}</span>`);
  if (f.certs.includes("Security+") || f.certs.includes("DoD 8140/8570")) t.push('<span class="tag violet">Sec+</span>');
  if (f.years != null) t.push(`<span class="tag ${f.years <= 2 ? "good" : f.years >= 5 ? "warn" : ""}">${f.years}+ yrs</span>`);
  if (f.workplace) t.push(`<span class="tag">${esc(f.workplace)}</span>`);
  return t.join("");
}

/* ------------------------------------------------------------- navigation */
function go(v) {
  S.view = v;
  history.replaceState(null, "", "#" + v);
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("active", b.dataset.view === v));
  renderSidebar();
  const render = { jobs: renderJobs, compare: renderCompare, tracker: renderTracker, insights: renderInsights,
                   profile: renderProfile, searches: renderSearches, settings: renderSettings }[v];
  // Any page that fails to load shows the error and a Retry button instead of hanging on "Loading…"
  Promise.resolve().then(render).catch(err => {
    if (S.view !== v) return;
    view().innerHTML = `<div class="empty">Couldn't load this page: ${esc(err.message)}<br><br>
      <button class="btn" data-act="retry-view">Retry</button></div>`;
  });
  $(".main").scrollTop = 0;
}
$("#nav").addEventListener("click", e => { const b = e.target.closest("button"); if (b) go(b.dataset.view); });
// links like #tracker or #insights switch pages without a reload
window.addEventListener("hashchange", () => {
  const v = location.hash.slice(1).split("=")[0];
  if (v !== S.view && ["jobs", "compare", "tracker", "insights", "profile", "searches", "settings"].includes(v)) go(v);
});

function renderSidebar() {
  $("#searchList").innerHTML = S.searches.map(s => `
    <button data-search="${s.id}" class="${S.view === "jobs" && s.id === S.searchId ? "active" : ""}">
      ${esc(s.name)} ${s.new ? `<span class="new">${s.new} new</span>` : ""}<span class="n">${s.count}</span>
    </button>`).join("");
  $("#compareCount").textContent = S.compare.size;
}
$("#searchList").addEventListener("click", e => {
  const b = e.target.closest("[data-search]");
  if (b) selectSearch(+b.dataset.search);
});

// Switch tabs immediately (cached jobs or a loading state), then refresh from the server.
function selectSearch(id) {
  S.searchId = id; save("search", id);
  S.shown = PAGE_SIZE; S.expanded.clear();
  const cached = S.jobCache.get(id);
  S.jobs = cached || [];
  S.loading = !cached;
  go("jobs");
  loadJobs().then(() => { if (S.view === "jobs" && S.searchId === id) renderJobs(); });
}

async function loadSearches() {
  S.searches = await api("/api/searches");
  const remembered = load("search", null);
  if (!S.searches.some(s => s.id === S.searchId)) {
    S.searchId = S.searches.some(s => s.id === remembered) ? remembered : S.searches[0]?.id ?? null;
  }
  renderSidebar();
}
async function loadJobs({ fresh = false } = {}) {
  if (fresh) S.jobCache.clear();  // after a crawl or a search edit every cached list is stale
  const id = S.searchId, token = ++S.loadToken;
  if (id == null) { S.jobs = []; S.loading = false; return; }
  try {
    const jobs = await api(`/api/jobs?search=${id}`);
    S.jobCache.set(id, jobs);
    if (token === S.loadToken) S.jobs = jobs;
  } catch (err) {
    if (token === S.loadToken) toast(`Couldn't load jobs: ${err.message}`);
  } finally {
    if (token === S.loadToken) S.loading = false;
  }
}
async function loadTrackerCount() {
  S.tracker = await api("/api/tracker");
  $("#trackCount").textContent = S.tracker.jobs.length;
}

/* -------------------------------------------------------------- jobs view */
function filteredJobs() {
  const f = S.f, q = f.q.trim().toLowerCase();
  const rows = S.jobs.filter(j =>
    (f.showHidden || !j.hidden) &&
    (!f.tracks.length || f.tracks.includes(j.track)) &&
    (!f.category || j.category === f.category) &&
    (!f.onlyNew || j.is_new) &&
    (!f.hideSenior || !j.tags.includes("Senior")) &&
    (!f.localOnly || !isRemote(j)) &&
    (!f.starred || j.starred) &&
    (!f.noActiveClear || !isActiveClear(j)) &&
    (!q || `${j.title} ${j.company} ${j.location} ${j.extra}`.toLowerCase().includes(q)));
  const pay = j => j.facts?.pay?.annual_mid ?? -1;
  const sorters = {
    best: (a, b) => b.is_new - a.is_new || b.score - a.score || a.company.localeCompare(b.company),
    newest: (a, b) => b.first_seen.localeCompare(a.first_seen) || b.score - a.score,
    company: (a, b) => a.company.localeCompare(b.company) || b.score - a.score,
    pay: (a, b) => pay(b) - pay(a) || b.score - a.score,
    fit: (a, b) => (b.match?.score ?? -1) - (a.match?.score ?? -1) || b.score - a.score,
  };
  return rows.sort(sorters[f.sort] || sorters.best);
}

function renderJobs() {
  const s = S.searches.find(x => x.id === S.searchId);
  if (!s) { view().innerHTML = `<div class="empty">Create a saved search to get started.</div>`; return; }
  const tracks = [...new Set(S.jobs.map(j => j.track))].sort();
  const cats = [...new Set(S.jobs.map(j => j.category))].sort();
  const f = S.f;
  if (!S.loading) {
    // Drop filters that point at tracks/categories this search no longer has (they'd hide everything, with no chip to undo them)
    const tracksOk = f.tracks.filter(t => tracks.includes(t));
    if (tracksOk.length !== f.tracks.length || (f.category && !cats.includes(f.category))) {
      f.tracks = tracksOk;
      if (!cats.includes(f.category)) f.category = "";
      saveFilters();
    }
  }
  view().innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>${esc(s.name)}</h1><p>${S.loading ? "Loading jobs…" : `${S.jobs.length} matching jobs · ${s.new || 0} new since the last crawl`}</p></div>
      <button class="btn" data-act="edit-search">Edit search</button>
    </div>
    <div class="filters" id="filters">
      <input type="search" id="fq" placeholder="Filter by title, company, location…" value="${esc(f.q)}">
      <select id="fcat" aria-label="Category"><option value="">All categories</option>${cats.map(c => `<option ${c === f.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      <select id="fsort" aria-label="Sort">
        ${[["best", "Best match"], ["newest", "Newest found"], ["company", "Company"], ["pay", "Highest pay"], ["fit", "Resume match"]].map(([v, l]) => `<option value="${v}" ${f.sort === v ? "selected" : ""}>Sort: ${l}</option>`).join("")}
      </select>
      <label class="tog"><input type="checkbox" data-f="onlyNew" ${f.onlyNew ? "checked" : ""}> New only</label>
      <label class="tog"><input type="checkbox" data-f="hideSenior" ${f.hideSenior ? "checked" : ""}> Hide senior/lead</label>
      <label class="tog"><input type="checkbox" data-f="noActiveClear" ${f.noActiveClear ? "checked" : ""}> Hide active-clearance</label>
      <label class="tog"><input type="checkbox" data-f="localOnly" ${f.localOnly ? "checked" : ""}> Local only</label>
      <label class="tog"><input type="checkbox" data-f="starred" ${f.starred ? "checked" : ""}> Starred</label>
      <label class="tog"><input type="checkbox" data-f="showHidden" ${f.showHidden ? "checked" : ""}> Show hidden</label>
      <div class="chips" id="trackChips">${tracks.map(t => `<button class="chip" data-track="${esc(t)}" aria-pressed="${f.tracks.includes(t)}">${esc(t)}</button>`).join("")}</div>
    </div>
    <div class="count" id="jobCount"></div>
    <div class="jobs" id="jobList"></div>
    ${S.compare.size ? `<button class="btn primary compare-fab" data-act="go-compare">Compare ${S.compare.size} job${S.compare.size > 1 ? "s" : ""}</button>` : ""}`;
  renderJobList();
}

function renderJobList() {
  if (S.loading) {
    $("#jobCount").textContent = "";
    $("#jobList").innerHTML = `<div class="empty">Loading jobs…</div>`;
    return;
  }
  const rows = filteredJobs();
  const active = activeFilterCount(S.f);
  const clear = active ? ` · <button class="btn ghost small" data-act="clear-filters">Clear ${active} filter${active > 1 ? "s" : ""}</button>` : "";
  $("#jobCount").innerHTML = `Showing ${Math.min(rows.length, S.shown)} of ${rows.length} (${S.jobs.length} total)${clear}`;
  let empty = "Run a crawl to fill this search.";
  if (S.jobs.length) empty = active
    ? `${S.jobs.length} jobs are hidden by your filters. <button class="btn small" data-act="clear-filters">Clear filters</button>`
    : "No jobs match these filters.";
  $("#jobList").innerHTML = rows.length
    ? rows.slice(0, S.shown).map(jobCard).join("") +
      (rows.length > S.shown ? `<button class="btn" data-act="more" style="justify-self:center">Show more</button>` : "")
    : `<div class="empty">${empty}</div>`;
}

function jobCard(j) {
  const open = S.expanded.has(j.id);
  return `
  <article class="job ${j.is_new ? "isnew" : ""} ${j.hidden ? "hidden-job" : ""}" data-id="${j.id}">
    <div class="job-row">
      <input type="checkbox" data-act="compare" ${S.compare.has(j.id) ? "checked" : ""} aria-label="Add to compare">
      <div>
        <div class="title-line">
          <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>${recruiterBadge(j.facts)}
          ${j.is_new ? '<span class="tag new">NEW</span>' : ""}
        </div>
        <div class="sub"><b>${esc(j.company)}</b> · ${esc(j.location)}${j.extra ? " · " + esc(j.extra) : ""}${j.posted ? " · " + esc(j.posted) : ""}</div>
        <div class="tags">
          ${matchTag(j.match)}
          <span class="tag track">${esc(j.track)}</span>
          ${j.similar?.length ? `<span class="tag" title="Same title posted ${j.similar.length + 1} times">×${j.similar.length + 1} postings</span>` : ""}
          <span class="tag">${esc(j.category)}</span>
          ${j.tags.map(t => `<span class="tag ${t === "Clearance" ? "warn" : ""}">${esc(t)}</span>`).join("")}
          ${factTags(j.facts)}
        </div>
      </div>
      <div class="actions">
        ${j.status ? `<span class="status-pill s-${j.status}" title="Tracked in Applications">${j.status}</span>`
                   : `<button class="btn small" data-act="apply">Mark applied</button>`}
        <button class="btn ghost ${j.starred ? "on" : ""}" data-act="star" title="${j.starred ? "Unstar" : "Star"}">${j.starred ? ICON.starOn : ICON.star}</button>
        <button class="btn ghost" data-act="hide" title="${j.hidden ? "Unhide" : "Hide this job"}">${j.hidden ? ICON.show : ICON.hide}</button>
        <button class="btn ghost" data-act="expand" title="Details" aria-expanded="${open}" style="${open ? "transform:rotate(180deg)" : ""}">${ICON.chevron}</button>
      </div>
    </div>
    ${open ? `<div class="job-detail" id="detail-${j.id}">${detailHtml(j)}</div>` : ""}
  </article>`;
}

function factsGrid(f) {
  if (!f) return "";
  const r = f.recruiter;
  const items = [
    ["Pay", f.pay?.text || "Not listed"],
    ["Clearance", f.clearance],
    ["Experience", f.years != null ? `${f.years}+ years` : "Not stated"],
    ["Degree", f.degree || "Not stated"],
    ["Workplace", f.workplace || "Not stated"],
    ["Certs mentioned", f.certs.length ? f.certs.join(", ") : "None"],
  ];
  return `<dl class="facts">${items.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}
    ${r ? `<div style="grid-column:1/-1"><dt>Recruiter / contact</dt><dd>${esc(r.name || "")}${r.email ? ` · <a href="mailto:${esc(r.email)}">${esc(r.email)}</a>` : ""}<div class="sub">${esc(r.snippet)}</div></dd></div>` : ""}
  </dl>`;
}

function detailHtml(j) {
  const d = S.details.get(j.id);
  const err = S.detailErrors.get(j.id);
  if (err) return `<p class="sub">Couldn't load details: ${esc(err)}</p><button class="btn small" data-act="retry-details">Retry</button>`;
  if (S.reading.has(j.id)) return `<div class="sub">Reading the job description…</div>`;
  if (!d) return `<div class="sub">Loading…</div>`;
  if (!d.facts) {
    return `<p class="sub">${d.details_error ? "Couldn't read this posting: " + esc(d.details_error) : "Details haven't been read yet."}</p>
            <button class="btn small" data-act="load-details">Read job description</button>`;
  }
  return `${skillsHtml(d.match)}${similarHtml(j)}${factsGrid(d.facts)}
    ${d.description ? `<div class="desc">${esc(d.description.slice(0, 6000))}</div>` : ""}
    <p style="margin:10px 0 0"><a href="${esc(j.url)}" target="_blank" rel="noopener">Open the full posting ${ICON.external}</a></p>
    ${aiHtml(j)}`;
}

function redrawDetails() {
  if (S.view === "jobs") renderJobList(); else if (S.view === "compare") renderCompare();
}

async function expand(j) {
  if (S.expanded.has(j.id)) { S.expanded.delete(j.id); renderJobList(); return; }
  S.expanded.add(j.id);
  S.detailErrors.delete(j.id);
  renderJobList();
  if (S.details.has(j.id)) return;
  try {
    const full = await api(`/api/jobs/${j.id}`);
    S.details.set(j.id, full);
    if (!full.facts && !full.details_error) return loadDetails(j);
  } catch (e) {
    S.detailErrors.set(j.id, e.message);
  }
  redrawDetails();
}

async function loadDetails(j) {
  if (S.reading.has(j.id)) return;  // already in flight (double click)
  S.reading.add(j.id);
  S.detailErrors.delete(j.id);
  redrawDetails();
  try {
    const { facts } = await api(`/api/jobs/${j.id}/details`, { method: "POST", timeout: 60000 });
    j.facts = facts;
    const listed = S.jobs.find(x => x.id === j.id);
    if (listed) listed.facts = facts;
    S.details.set(j.id, await api(`/api/jobs/${j.id}`));
  } catch (e) {
    S.detailErrors.set(j.id, e.message);
  } finally {
    S.reading.delete(j.id);
  }
  redrawDetails();
}

function toggleCompare(id, on) {
  if (on && S.compare.size >= MAX_COMPARE) { toast(`You can compare up to ${MAX_COMPARE} jobs`); return false; }
  on ? S.compare.add(id) : S.compare.delete(id);
  save("compare", [...S.compare]);
  renderSidebar();
  return true;
}

async function setStatus(id, status, note = "") {
  await api(`/api/jobs/${id}/status`, { method: "POST", body: { status, note } });
  const j = S.jobs.find(x => x.id === id);
  if (j) j.status = status;
  if (S.details.has(id)) S.details.get(id).status = status;
  await loadTrackerCount();
}

view().addEventListener("click", async e => {
  const actEl = e.target.closest("[data-act]");
  if (!actEl) {
    const chip = e.target.closest("[data-track]");
    if (chip) {
      const t = chip.dataset.track, on = !S.f.tracks.includes(t);
      S.f.tracks = on ? [...S.f.tracks, t] : S.f.tracks.filter(x => x !== t);
      chip.setAttribute("aria-pressed", on); saveFilters(); S.shown = PAGE_SIZE; renderJobList();
    }
    return;
  }
  const act = actEl.dataset.act;
  const card = actEl.closest("[data-id]");
  const id = card ? +card.dataset.id : null;
  const j = id != null ? S.jobs.find(x => x.id === id) : null;
  try {
    switch (act) {
      case "more": S.shown += PAGE_SIZE; renderJobList(); break;
      case "retry-view": await refreshAll(); break;
      case "edit-area": openAreaDialog(); break;
      case "notify-test": await api("/api/notify-test", { method: "POST" }); toast("Sent. Check the bottom-right of your screen."); break;
      case "ai": {
        const task = actEl.dataset.task;
        S.ai.set(id, { loading: true });
        renderJobList();
        try {
          const r = await api(`/api/jobs/${id}/tailor`, { method: "POST", body: { task }, timeout: 200000 });
          S.ai.set(id, { text: r.text });
        } catch (err) { S.ai.set(id, { error: err.message }); }
        if (S.view === "jobs") renderJobList();
        break;
      }
      case "ai-copy":
        await navigator.clipboard.writeText(S.ai.get(id)?.text || "");
        toast("Copied to clipboard"); break;
      case "clear-filters":
        Object.assign(S.f, { q: "", tracks: [], category: "", onlyNew: false, localOnly: false, starred: false, noActiveClear: false });
        saveFilters(); S.shown = PAGE_SIZE; renderJobs(); break;
      case "edit-search": go("searches"); break;
      case "go-compare": go("compare"); break;
      case "compare": if (!toggleCompare(id, actEl.checked)) actEl.checked = false; else if (S.view === "jobs") renderJobs(); break;
      case "expand": await expand(j); break;
      case "load-details": await loadDetails(j || { id }); break;
      case "retry-details":
        S.detailErrors.delete(id);
        if (S.details.has(id)) await loadDetails(j || { id });
        else { S.expanded.delete(id); await expand(j); }
        break;
      case "star":
        j.starred = j.starred ? 0 : 1;
        await api(`/api/jobs/${id}/state`, { method: "POST", body: { starred: j.starred } });
        renderJobList(); break;
      case "hide":
        j.hidden = j.hidden ? 0 : 1;
        await api(`/api/jobs/${id}/state`, { method: "POST", body: { hidden: j.hidden } });
        toast(j.hidden ? "Hidden. Tick “Show hidden” to see it again." : "Unhidden");
        renderJobList(); break;
      case "apply":
        await setStatus(id, "applied");
        toast(`Tracking “${j ? j.title : "job"}” as applied`);
        if (S.view === "jobs") renderJobList(); else renderCompare();
        break;
      case "uncompare": toggleCompare(id, false); renderCompare(); break;
      case "clear-compare": S.compare.clear(); save("compare", []); renderSidebar(); renderCompare(); break;
      default: await trackerAction(act, actEl, id);
    }
  } catch (err) { toast(err.message); }
});

view().addEventListener("input", e => {
  const t = e.target;
  if (S.view !== "jobs") return;
  if (t.id === "fq") S.f.q = t.value;
  else if (t.id === "fcat") S.f.category = t.value;
  else if (t.id === "fsort") S.f.sort = t.value;
  else if (t.dataset.f) S.f[t.dataset.f] = t.checked;
  else return;
  saveFilters(); S.shown = PAGE_SIZE; renderJobList();
});

/* ----------------------------------------------------------- compare view */
async function renderCompare() {
  const ids = [...S.compare];
  view().innerHTML = `
    <div class="page-head"><div class="grow"><h1>Compare</h1><p>Tick the box on up to ${MAX_COMPARE} jobs to line them up side by side.</p></div>
      ${ids.length ? '<button class="btn" data-act="clear-compare">Clear all</button>' : ""}</div>
    <div id="cmp">${ids.length ? '<div class="sub">Loading…</div>' : '<div class="empty">Nothing selected yet. Go to Jobs and tick a few.</div>'}</div>`;
  if (!ids.length) return;
  const gone = [];
  await Promise.all(ids.map(async id => {
    if (S.details.has(id)) return;
    try { S.details.set(id, await api(`/api/jobs/${id}`)); }
    catch (e) { if (/404|not found/i.test(e.message)) gone.push(id); }
  }));
  if (gone.length) {  // jobs that no longer exist would otherwise be stuck in the compare list
    gone.forEach(id => S.compare.delete(id)); save("compare", [...S.compare]); renderSidebar();
  }
  if (S.view !== "compare") return;
  const live = [...S.compare].map(id => S.details.get(id)).filter(Boolean);
  $("#cmp").innerHTML = live.length ? compareTable(live)
    : '<div class="empty">Couldn\'t load these jobs. <button class="btn small" data-act="clear-compare">Clear the list</button></div>';
  // Read each missing description once per session; failures show a Retry instead of looping
  const missing = live.filter(j => !j.facts && !j.details_error && !S.autoRead.has(j.id));
  missing.forEach(j => S.autoRead.add(j.id));
  if (missing.length) {
    await Promise.all(missing.map(j => loadDetails(j)));
  }
}

function fit(f) {
  if (!f) return [];
  const checks = [];
  checks.push(f.clearance === "Active required" ? ["bad", "Needs an active clearance"]
            : f.clearance === "Can obtain (sponsored)" ? ["good", "Will sponsor clearance"]
            : f.clearance === "Mentioned" ? ["warn", "Clearance mentioned"] : ["good", "No clearance needed"]);
  if (f.years != null) checks.push(f.years <= 2 ? ["good", `${f.years}+ yrs: entry-friendly`] : f.years <= 4 ? ["warn", `${f.years}+ yrs experience`] : ["bad", `${f.years}+ yrs experience`]);
  if (f.certs.includes("Security+")) checks.push(["good", "Wants Security+ (you're studying it)"]);
  else if (f.certs.includes("DoD 8140/8570")) checks.push(["good", "DoD 8140: Security+ qualifies"]);
  if (f.degree && /master/i.test(f.degree)) checks.push(["warn", "Asks for a master's"]);
  return checks;
}

function compareTable(jobs) {
  const cell = fn => jobs.map(j => `<td>${fn(j)}</td>`).join("");
  const f = j => j.facts || {};
  const rows = [
    ["Fit check", j => j.facts ? fit(j.facts).map(([c, t]) => `<div><span class="tag ${c}">${esc(t)}</span></div>`).join("")
      : S.reading.has(j.id) ? '<span class="sub">Reading the description…</span>'
      : `<span class="sub">${esc(S.detailErrors.get(j.id) || j.details_error || "Not read yet")}</span><div><button class="btn small" data-act="retry-details">Retry</button></div>`],
    ["Company", j => `<b>${esc(j.company)}</b><div class="sub">${esc(j.category)}</div>`],
    ["Location", j => esc(j.location)],
    ["Workplace", j => esc(f(j).workplace || "Not stated")],
    ["Pay", j => f(j).pay ? `<b>${esc(f(j).pay.text)}</b>` : '<span class="sub">Not listed</span>'],
    ["Resume match", j => j.match ? `${matchTag(j.match)}<div class="skill-list">${j.match.missing.slice(0, 8).map(x => `<span class="skill miss">${esc(x)}</span>`).join("")}</div>`
      : `<span class="sub">${S.profileSet ? "Too few skills listed to score" : 'Add your resume under "My resume"'}</span>`],
    ["Clearance", j => esc(f(j).clearance || "")],
    ["Experience", j => f(j).years != null ? `${f(j).years}+ years` : '<span class="sub">Not stated</span>'],
    ["Degree", j => esc(f(j).degree || "Not stated")],
    ["Certs", j => (f(j).certs || []).map(c => `<span class="tag ${c === "Security+" ? "violet" : ""}">${esc(c)}</span>`).join(" ") || '<span class="sub">None</span>'],
    ["Recruiter", j => f(j).recruiter ? `<span class="recruiter">${ICON.recruiter}</span> ${esc(f(j).recruiter.name || "")} ${f(j).recruiter.email ? `<a href="mailto:${esc(f(j).recruiter.email)}">${esc(f(j).recruiter.email)}</a>` : ""}` : '<span class="sub">None listed</span>'],
    ["Found", j => `${fmtDate(j.first_seen)}${j.posted ? `<div class="sub">${esc(j.posted)}</div>` : ""}`],
    ["Status", j => j.status ? `<span class="status-pill s-${j.status}">${j.status}</span>` : `<button class="btn small" data-act="apply">Mark applied</button>`],
  ];
  return `<div class="compare-wrap"><table class="compare">
    <thead><tr><th scope="row"></th>${jobs.map(j => `<th data-id="${j.id}"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
      <div><button class="btn ghost small" data-act="uncompare">Remove</button></div></th>`).join("")}</tr></thead>
    <tbody>${rows.map(([label, fn]) => `<tr><th scope="row">${label}</th>${jobs.map(j => `<td data-id="${j.id}">${fn(j)}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

/* ----------------------------------------------------------- tracker view */
async function renderTracker() {
  view().innerHTML = '<div class="sub">Loading…</div>';
  await loadTrackerCount();
  if (S.view !== "tracker") return;
  const { jobs, stats, ghost_days } = S.tracker;
  const by = stats.by_status;
  const stale = jobs.filter(j => j.suggest_ghosted);
  const followUps = jobs.filter(j => j.suggest_follow_up);
  const upcoming = jobs.filter(j => j.interview_at && new Date(j.interview_at) > Date.now() - 3600e3)
                       .sort((a, b) => a.interview_at.localeCompare(b.interview_at));
  const col = st => jobs.filter(j => j.status === st || (st === "rejected" && j.status === "withdrawn"));
  view().innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>Applications</h1><p>Drag cards between columns or use the dropdown. Everything is saved automatically.</p></div>
      <a class="btn" href="/api/tracker.csv">Export CSV</a>
      <button class="btn primary" data-act="add-manual">+ Add application</button>
    </div>
    <div class="stats">
      ${[["Applications", stats.total], ["Response rate", stats.response_rate + "%"], ["Interviewing", by.interviewing || 0],
         ["Offers", by.offer || 0], ["Rejected", (by.rejected || 0) + (by.withdrawn || 0)], ["Ghosted", by.ghosted || 0]]
        .map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("")}
    </div>
    ${upcoming.length ? `<div class="upcoming">${upcoming.map(j => `<div class="item">📅 <b>${esc(new Date(j.interview_at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}</b>
       ${esc(j.title)} · ${esc(j.company)} <a class="btn small" style="margin-left:auto" href="/api/jobs/${j.id}/interview.ics">Add to calendar</a></div>`).join("")}</div>` : ""}
    ${followUps.length ? `<div class="notice info"><div class="row"><b>Time to follow up (${S.tracker.follow_up_days}+ days since applying):</b></div>
       ${followUps.map(j => `<div class="row" data-id="${j.id}">${esc(j.title)} · ${esc(j.company)}
         <button class="btn small" data-act="followed-up" style="margin-left:auto">I followed up</button></div>`).join("")}</div>` : ""}
    ${stale.length ? `<div class="notice"><b>${stale.length} application${stale.length > 1 ? "s have" : " has"} had no reply in ${ghost_days}+ days.</b>
       <span>${stale.slice(0, 4).map(j => esc(j.company)).join(", ")}${stale.length > 4 ? "…" : ""}</span>
       <button class="btn small" data-act="ghost-all">Mark as ghosted</button></div>` : ""}
    ${jobs.length ? `<div class="board">${BOARD.map(st => `
      <section class="col" data-col="${st}"><h3>${st}<span>${col(st).length}</span></h3>
        ${col(st).map(trackerCard).join("") || '<div class="sub" style="padding:6px">Nothing here</div>'}
      </section>`).join("")}</div>`
      : `<div class="empty">No applications yet. Hit “Mark applied” on a job, or add one you found elsewhere.</div>`}
    ${stats.companies.length ? `<h2 class="section">Who's doing what</h2>
    <table class="grid"><thead><tr><th>Company</th><th class="num">Applied</th><th class="num">Replied</th><th class="num">Interviews</th>
      <th class="num">Offers</th><th class="num">Rejected</th><th class="num">Ghosted</th><th class="num">Avg. days to reply</th></tr></thead>
      <tbody>${stats.companies.map(c => `<tr><td>${esc(c.company)}</td><td class="num">${c.applied}</td><td class="num">${c.responded}</td>
        <td class="num">${c.interviewing}</td><td class="num">${c.offer}</td><td class="num">${c.rejected}</td><td class="num">${c.ghosted}</td>
        <td class="num">${c.avg_response_days ?? "–"}</td></tr>`).join("")}</tbody></table>` : ""}`;
  wireDrag();
}

function trackerCard(j) {
  return `<div class="tcard" draggable="true" data-id="${j.id}">
    <a href="${esc(j.url.startsWith("manual:") ? "#" : j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>${recruiterBadge(j.facts)}
    <div class="sub">${esc(j.company)}</div>
    <div class="sub">Applied ${fmtDate(j.applied_at)} · ${j.days_in_status ?? 0}d in ${j.status}</div>
    ${j.status === "withdrawn" ? '<span class="status-pill s-withdrawn">withdrawn</span>' : ""}
    ${!j.active ? '<div class="closed">Posting has closed</div>' : ""}
    ${j.status === "interviewing" ? `<label class="sub" style="display:block;margin-top:6px">Interview
      <input type="datetime-local" data-act="interview" value="${esc((j.interview_at || "").slice(0, 16))}"></label>
      ${j.interview_at ? `<a class="sub" href="/api/jobs/${j.id}/interview.ics">Add to calendar</a>` : ""}` : ""}
    ${j.followed_up_at ? `<div class="sub">Followed up ${fmtDate(j.followed_up_at)}</div>` : ""}
    <select data-act="set-status" aria-label="Status">
      ${STATUSES.map(s => `<option value="${s}" ${s === j.status ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}
      <option value="">Remove from tracker</option>
    </select>
    <details style="margin-top:6px"><summary class="sub" style="cursor:pointer">Notes &amp; history</summary>
      <textarea rows="3" data-act="notes" placeholder="Interview date, contact, follow-up…">${esc(j.notes)}</textarea>
      <ul class="hist">${j.history.map(h => `<li>${fmtDate(h.at)} · ${esc(h.status)}${h.note ? " – " + esc(h.note) : ""}</li>`).join("")}</ul>
    </details>
  </div>`;
}

async function trackerAction(act, el, id) {
  if (act === "followed-up") {
    await api(`/api/jobs/${id}/followed-up`, { method: "POST" });
    toast("Logged. Nice."); return renderTracker();
  }
  if (act === "add-manual") {
    $("#manualForm").reset();
    $("#manualForm [name=location]").value = S.region?.label || "";
    $("#manualDialog").returnValue = "";
    $("#manualDialog").showModal();
    return;
  }
  if (act === "ghost-all") {
    for (const j of S.tracker.jobs.filter(x => x.suggest_ghosted)) await setStatus(j.id, "ghosted", "No reply");
    toast("Marked as ghosted"); return renderTracker();
  }
}

view().addEventListener("change", async e => {
  const el = e.target, card = el.closest(".tcard");
  if (!card) return;
  const id = +card.dataset.id;
  try {
    if (el.dataset.act === "set-status") {
      if (!el.value && !confirm("Stop tracking this application? Its history will be cleared.")) { renderTracker(); return; }
      await setStatus(id, el.value || null); renderTracker();
    } else if (el.dataset.act === "interview") {
      await api(`/api/jobs/${id}/interview`, { method: "POST", body: { at: el.value || null } });
      toast(el.value ? "Interview saved" : "Interview cleared"); renderTracker();
    } else if (el.dataset.act === "notes") {
      await api(`/api/jobs/${id}/state`, { method: "POST", body: { notes: el.value } }); toast("Notes saved");
    }
  } catch (err) { toast(err.message); }
});

function wireDrag() {
  let dragId = null;
  view().querySelectorAll(".tcard").forEach(c => c.addEventListener("dragstart", () => { dragId = +c.dataset.id; }));
  view().querySelectorAll(".col").forEach(col => {
    col.addEventListener("dragover", e => { e.preventDefault(); col.classList.add("drop"); });
    col.addEventListener("dragleave", () => col.classList.remove("drop"));
    col.addEventListener("drop", async e => {
      e.preventDefault(); col.classList.remove("drop");
      const j = S.tracker.jobs.find(x => x.id === dragId);
      if (j && j.status !== col.dataset.col) { await setStatus(dragId, col.dataset.col); renderTracker(); }
    });
  });
}

$("#manualDialog").addEventListener("close", async () => {
  if ($("#manualDialog").returnValue !== "ok") return;
  const body = Object.fromEntries(new FormData($("#manualForm")));
  try { await api("/api/jobs/manual", { method: "POST", body }); toast("Application added"); renderTracker(); }
  catch (err) { toast(err.message); }
});

/* ---------------------------------------------------------- searches view */
const CATEGORIES = ["Hospital", "Government", "Defense/Contractor", "Private", "Education"];

function searchForm(s) {
  const isNew = !s.id;
  return `<form class="panel form" data-search-form="${s.id || ""}">
    <h3>${isNew ? "New search" : esc(s.name)}</h3>
    ${isNew ? '<p class="help">Searches filter every job JobHuntr has found. Keyword-only sites (Baptist/Tenet, USAJobs) pick up new keywords on the next crawl.</p>' : ""}
    <div class="row3">
      <label class="f">Name<input type="text" name="name" value="${esc(s.name || "")}" required></label>
      <label class="f">Type<select name="mode">
        <option value="keywords" ${s.mode !== "it" ? "selected" : ""}>Keywords</option>
        <option value="it" ${s.mode === "it" ? "selected" : ""}>Built-in IT profile (+ keywords)</option></select></label>
      <label class="f">&nbsp;<span class="tog"><input type="checkbox" name="search_descriptions" ${s.search_descriptions ? "checked" : ""}> Also search descriptions</span></label>
    </div>
    <label class="f">Keywords (comma separated, any can match)<input type="text" name="keywords" value="${esc((s.keywords || []).join(", "))}" placeholder="e.g. soc analyst, splunk, incident response"></label>
    <label class="f">Exclude if title contains<input type="text" name="exclude" value="${esc((s.exclude || []).join(", "))}" placeholder="e.g. senior, manager"></label>
    <div class="f" style="font-size:13px;color:var(--muted)">Only these categories (none ticked = all)
      <div class="chips" style="margin-top:4px">${CATEGORIES.map(c => `<label class="tog"><input type="checkbox" name="cat" value="${c}" ${(s.categories || []).includes(c) ? "checked" : ""}> ${c}</label>`).join("")}</div>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      ${isNew ? "" : '<button type="button" class="btn danger" data-act="delete-search">Delete</button>'}
      <button class="btn primary">${isNew ? "Create search" : "Save"}</button>
    </div>
  </form>`;
}

function renderSearches() {
  view().innerHTML = `
    <div class="page-head"><div class="grow"><h1>Saved searches</h1><p>Each search shows up in the sidebar with its own count of matching and new jobs.</p></div></div>
    <div class="searchcards">${searchForm({ mode: "keywords" })}${S.searches.map(searchForm).join("")}</div>`;
}

view().addEventListener("submit", async e => {
  const form = e.target.closest("[data-search-form]");
  if (!form) return;
  e.preventDefault();
  const fd = new FormData(form);
  const list = v => String(v || "").split(",").map(x => x.trim()).filter(Boolean);
  const body = { name: fd.get("name").trim(), mode: fd.get("mode"), keywords: list(fd.get("keywords")),
                 exclude: list(fd.get("exclude")), categories: fd.getAll("cat"), search_descriptions: fd.has("search_descriptions") };
  if (body.mode === "keywords" && !body.keywords.length) { toast("Add at least one keyword"); return; }
  try {
    const id = form.dataset.searchForm;
    if (id) await api(`/api/searches/${id}`, { method: "PUT", body });
    else { const r = await api("/api/searches", { method: "POST", body }); S.searchId = r.id; save("search", r.id); }
    await loadSearches(); await loadJobs({ fresh: true });
    toast("Search saved"); go("jobs");
  } catch (err) { toast(err.message); }
});
view().addEventListener("click", async e => {
  const del = e.target.closest('[data-act="delete-search"]');
  if (!del) return;
  const id = +del.closest("[data-search-form]").dataset.searchForm;
  if (!confirm("Delete this search? Jobs and applications are kept.")) return;
  try {
    await api(`/api/searches/${id}`, { method: "DELETE" });
    S.jobCache.delete(id); delete S.filters[id]; saveFilters();
    await loadSearches(); await loadJobs({ fresh: true }); renderSearches();
    toast("Search deleted");
  } catch (err) { toast(err.message); }
});

/* ---------------------------------------------------------- settings view */
async function renderSettings() {
  const [settings, sched] = await Promise.all([api("/api/settings"), api("/api/schedule").catch(() => ({ enabled: false, time: "08:00" }))]);
  S.settings = settings;
  if (S.view !== "settings") return;
  const st = S.settings;
  const status = l => !l ? '<span class="sub">–</span>'
    : l.state === "ok" ? `<span class="ok">✓ ${l.count} listings${l.new ? `, ${l.new} new` : ""}</span>`
    : l.state === "skipped" ? `<span class="skip">${esc(l.error)}</span>` : `<span class="err">✗ ${esc(l.error || l.state)}</span>`;
  view().innerHTML = `
    <div class="page-head"><div class="grow"><h1>Sources &amp; settings</h1><p>Last crawl ${ago(st.last_run?.finished_at)}.</p></div></div>
    <div class="panel">
      <h3>Your area</h3>
      <p class="help">${st.region ? `Searching <b>${esc(st.region.label)}</b>${st.region.nearby.length ? ` plus ${st.region.nearby.length} nearby place${st.region.nearby.length > 1 ? "s" : ""}` : ""}.`
        : "Not set yet. JobHuntr needs to know where you're looking before it can crawl."}
        ${st.pack.sources ? ` Your personal pack adds ${st.pack.sources} local employer${st.pack.sources > 1 ? "s" : ""}.` : ""}</p>
      <button type="button" class="btn" data-act="edit-area">${st.region ? "Change area" : "Set your area"}</button>
    </div>
    <form class="panel form" id="prefsForm">
      <h3>Crawl options</h3>
      <div class="row2">
        <label class="tog"><input type="checkbox" name="include_remote" ${st.include_remote ? "checked" : ""}> Include remote jobs from these employers</label>
        <label class="f">Suggest “ghosted” after this many days without a reply<input type="number" name="ghost_days" min="1" value="${st.ghost_days}"></label>
        <span></span>
        <label class="f">Remind me to follow up after this many days<input type="number" name="follow_up_days" min="1" value="${st.follow_up_days}"></label>
      </div>
      <div style="text-align:right"><button class="btn primary">Save</button></div>
    </form>
    <form class="panel form" id="scheduleForm">
      <h3>Daily automatic crawl</h3>
      <p class="help">Windows runs a crawl every day at this time, even when JobHuntr is closed, and shows a notification when new jobs match your searches.
        ${sched.enabled ? `<b class="ok">On${sched.next_run ? ` · next run ${esc(sched.next_run)}` : ""}</b>` : ""}</p>
      <div class="row3">
        <label class="tog"><input type="checkbox" name="enabled" ${sched.enabled ? "checked" : ""}> Crawl every day</label>
        <label class="f">At<input type="time" name="time" value="${esc(sched.time || "08:00")}"></label>
        <span></span>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button type="button" class="btn" data-act="notify-test">Send a test notification</button>
        <button class="btn primary">Save</button>
      </div>
    </form>
    <form class="panel form" id="aiForm">
      <h3>AI help (optional)</h3>
      <p class="help">Adds Cover letter, Resume bullets and Interview prep buttons to each job, written by Claude from your resume and the posting.
        Uses your own Anthropic API key (<a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">get one here</a>; usage is billed to you, roughly a few cents per click). The key is stored only on this PC.
        ${st.has_ai_key ? '<b class="ok">Key saved ✓</b>' : ""}</p>
      <label class="f">Anthropic API key<input type="password" name="ai_key" placeholder="${st.has_ai_key ? "•••••• (saved; paste a new one to replace, leave blank and save to remove)" : "sk-ant-…"}"></label>
      <div style="text-align:right"><button class="btn primary">Save</button></div>
    </form>
    <form class="panel form" id="usajobsForm">
      <h3>USAJobs (federal jobs: VA, military bases, agencies)</h3>
      <p class="help">Federal jobs need a free API key: request one at <a href="https://developer.usajobs.gov/apirequest/" target="_blank" rel="noopener">developer.usajobs.gov</a>, and it gets emailed to you.
        ${st.usajobs.has_key ? '<b class="ok">Key saved ✓</b>' : ""}</p>
      <div class="row2">
        <label class="f">Email you registered with<input type="email" name="email" value="${esc(st.usajobs.email)}"></label>
        <label class="f">API key<input type="password" name="api_key" placeholder="${st.usajobs.has_key ? "•••••• (saved)" : "paste key"}"></label>
      </div>
      <div style="text-align:right"><button class="btn primary">Save</button></div>
    </form>
    <div class="panel">
      <h3>Employers being crawled</h3>
      <p class="help">Untick to skip a site. Status is from the last crawl.</p>
      <table class="grid src-table"><thead><tr><th></th><th>Employer</th><th>Category</th><th>Platform</th><th>Last crawl</th><th></th></tr></thead>
        <tbody>${st.sources.map(s => `<tr><td><input type="checkbox" data-src="${esc(s.name)}" ${s.enabled ? "checked" : ""} aria-label="Enable ${esc(s.name)}"></td>
          <td>${esc(s.name)}</td><td>${esc(s.category)}</td><td>${esc(s.type)}</td><td>${status(s.last)}</td>
          <td>${s.custom ? `<button class="btn ghost small danger" data-del-src="${esc(s.name)}">Remove</button>` : ""}</td></tr>`).join("")}</tbody></table>
    </div>
    <form class="panel form" id="addSourceForm">
      <h3>Add an employer that uses Workday</h3>
      <p class="help">Open their careers page. If the address has <code>myworkdayjobs.com</code> in it, paste it here.</p>
      <div class="row3">
        <label class="f">Careers URL<input type="url" name="url" placeholder="https://company.wd5.myworkdayjobs.com/External" required></label>
        <label class="f">Name<input type="text" name="name" placeholder="Company"></label>
        <label class="f">Category<select name="category">${CATEGORIES.map(c => `<option>${c}</option>`).join("")}</select></label>
      </div>
      <div style="text-align:right"><button class="btn primary">Add employer</button></div>
    </form>
    <div class="panel">
      <h3>Check these by hand</h3>
      <p class="help">These sites block crawlers or have no usable feed.</p>
      <div class="links">${st.manual_links.map(l => `<div><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)}</a> <span class="sub">${esc(l.category)}</span></div>`).join("")}</div>
    </div>`;
}

view().addEventListener("submit", async e => {
  const id = e.target.id;
  if (!["prefsForm", "usajobsForm", "addSourceForm", "scheduleForm", "aiForm"].includes(id)) return;
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    if (id === "prefsForm") await api("/api/settings", { method: "POST", body: { include_remote: fd.has("include_remote"), ghost_days: +fd.get("ghost_days"), follow_up_days: +fd.get("follow_up_days") } });
    if (id === "scheduleForm") {
      const r = await api("/api/schedule", { method: "POST", body: { enabled: fd.has("enabled"), time: fd.get("time") } });
      toast(r.enabled ? `Daily crawl set for ${r.time}` : "Daily crawl turned off"); renderSettings(); return;
    }
    if (id === "aiForm") await api("/api/settings", { method: "POST", body: { ai_key: fd.get("ai_key") } });
    if (id === "usajobsForm") await api("/api/settings", { method: "POST", body: { usajobs: { email: fd.get("email"), api_key: fd.get("api_key") } } });
    if (id === "addSourceForm") await api("/api/sources", { method: "POST", body: Object.fromEntries(fd) });
    toast(id === "addSourceForm" ? "Employer added. It's included from the next crawl." : "Saved");
    renderSettings();
  } catch (err) { toast(err.message); }
});
view().addEventListener("change", async e => {
  const name = e.target.dataset?.src;
  if (name === undefined) return;
  try {
    await api("/api/sources/toggle", { method: "POST", body: { name, enabled: e.target.checked } });
    toast(`${name} ${e.target.checked ? "enabled" : "disabled"}`);
  } catch (err) { e.target.checked = !e.target.checked; toast(err.message); }
});
view().addEventListener("click", async e => {
  const b = e.target.closest("[data-del-src]");
  if (!b || !confirm(`Remove ${b.dataset.delSrc}?`)) return;
  try {
    await api(`/api/sources/${encodeURIComponent(b.dataset.delSrc)}`, { method: "DELETE" });
    renderSettings();
  } catch (err) { toast(err.message); }
});

/* ----------------------------------------------------------- resume view */
async function loadProfile() {
  S.profile = await api("/api/profile");
  S.profileSet = (S.profile.skills || []).length > 0;
}

async function renderProfile() {
  await loadProfile();
  if (S.view !== "profile") return;
  const p = S.profile;
  view().innerHTML = `
    <div class="page-head"><div class="grow"><h1>My resume</h1>
      <p>JobHuntr compares this to every job description to score matches and show which skills you're missing. It stays on this PC.</p></div></div>
    <form class="panel form" id="profileForm">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <h3 style="margin:0">Resume text</h3>
        <label class="btn small" style="margin-left:auto">Upload .pdf / .docx / .txt<input type="file" id="resumeFile" accept=".pdf,.docx,.txt,.md" hidden></label>
      </div>
      <textarea name="resume_text" rows="14" placeholder="Paste your resume here, or upload the file.">${esc(p.resume_text)}</textarea>
      <label class="f">Skills or certifications not on your resume yet (comma separated)
        <input type="text" name="extra" value="${esc(p.extra)}" placeholder="e.g. Security+ (studying), Splunk, Active Directory"></label>
      <div style="text-align:right"><button class="btn primary">Save &amp; re-score jobs</button></div>
    </form>
    <div class="panel">
      <h3>Skills JobHuntr found (${p.skills.length})</h3>
      <p class="help">${p.skills.length ? "These are matched against each job's description." : "Save your resume to see the skills it picks up."}</p>
      <div class="skill-list">${p.skills.map(x => `<span class="skill have">${esc(x)}</span>`).join("")}</div>
    </div>`;
}

view().addEventListener("change", async e => {
  if (e.target.id !== "resumeFile" || !e.target.files.length) return;
  const fd = new FormData();
  fd.append("file", e.target.files[0]);
  try {
    const res = await fetch("/api/profile/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed");
    $("#profileForm [name=resume_text]").value = data.resume_text;
    toast("Resume read. Check it, then Save.");
  } catch (err) { toast(err.message); }
});

view().addEventListener("submit", async e => {
  if (e.target.id !== "profileForm") return;
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api("/api/profile", { method: "POST", body: { resume_text: fd.get("resume_text"), extra: fd.get("extra") } });
    await loadJobs({ fresh: true });
    S.details.clear();
    toast("Saved. Match scores updated.");
    renderProfile();
  } catch (err) { toast(err.message); }
});

/* --------------------------------------------------------- insights view */
const money = v => "$" + Math.round(v / 1000) + "k";
const shortDate = w => { const d = new Date(w + "T00:00"); return `${d.getMonth() + 1}/${d.getDate()}`; };

// Column with a 4px rounded top, square at the baseline.
function colPath(x, y, w, h) {
  if (h <= 0) return "";
  const r = Math.min(4, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
// Horizontal bar with a 4px rounded end, square at the left baseline.
function barPath(x, y, w, h) {
  if (w <= 0) return "";
  const r = Math.min(4, w, h / 2);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}

function columnChart(rows, key, color, unit) {
  const W = 520, H = 170, L = 28, B = 22, T = 8;
  const max = Math.max(1, ...rows.map(r => r[key]));
  const top = Math.ceil(max / 2) * 2 || 2;
  const band = (W - L) / rows.length, bw = Math.min(24, band * 0.6);
  const y = v => T + (H - T - B) * (1 - v / top);
  const grid = [0, top / 2, top].map(v => `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)"/>
      <text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
  const bars = rows.map((r, i) => {
    const x = L + i * band + (band - bw) / 2;
    const tipText = `<b>Week of ${shortDate(r.week)}</b>${r[key]} ${unit}`;
    return `<path d="${colPath(x, y(r[key]), bw, y(0) - y(r[key]))}" fill="${color}"/>
      <rect class="hit" x="${L + i * band}" y="${T}" width="${band}" height="${H - T - B}" data-tip="${esc(tipText)}"/>
      ${i % 3 === 2 || i === rows.length - 1 ? `<text x="${L + i * band + band / 2}" y="${H - 6}" text-anchor="middle">${shortDate(r.week)}</text>` : ""}`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(unit)} per week">${grid}${bars}</svg>`;
}

function hbarChart(rows, { label, value, color, fmt = v => v, tip: tipFor, W = 520 }) {
  // W matches the card's real width so text renders at its normal size instead of being scaled up
  const rowH = 26, L = W > 700 ? 180 : 150, R = 48;
  const max = Math.max(1, ...rows.map(value));
  const H = rows.length * rowH;
  const body = rows.map((r, i) => {
    const w = (W - L - R) * value(r) / max, y0 = i * rowH + 5;
    return `<text x="${L - 8}" y="${y0 + 12}" text-anchor="end">${esc(label(r))}</text>
      <path d="${barPath(L, y0, w, 16)}" fill="${color(r)}"/>
      <text class="val" x="${L + w + 6}" y="${y0 + 12}">${fmt(value(r))}</text>
      <rect class="hit" x="0" y="${i * rowH}" width="${W}" height="${rowH}" data-tip="${esc(tipFor(r))}"/>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${body}</svg>`;
}

function payChart(rows) {
  const W = 520, rowH = 34, L = 170, R = 20, B = 20;
  const lo = Math.min(...rows.map(r => r.min)), hi = Math.max(...rows.map(r => r.max));
  const a = Math.floor(lo / 20000) * 20000, b = Math.max(Math.ceil(hi / 20000) * 20000, a + 20000);
  const x = v => L + (W - L - R) * (v - a) / (b - a);
  const H = rows.length * rowH + B;
  const ticks = [];
  for (let v = a; v <= b + 1; v += (b - a) / 4) ticks.push(v);
  const grid = ticks.map(v => `<line x1="${x(v)}" x2="${x(v)}" y1="0" y2="${H - B}" stroke="var(--grid)"/>
      <text x="${x(v)}" y="${H - 4}" text-anchor="middle">${money(v)}</text>`).join("");
  const body = rows.map((r, i) => {
    const cy = i * rowH + rowH / 2;
    const tipText = `<b>${esc(r.track)}</b>${money(r.min)} – ${money(r.max)} · median ${money(r.median)}<br>${r.n} posting${r.n > 1 ? "s" : ""} list pay`;
    return `<text x="${L - 10}" y="${cy + 4}" text-anchor="end">${esc(r.track)}</text>
      <line x1="${x(r.min)}" x2="${Math.max(x(r.max), x(r.min) + 1)}" y1="${cy}" y2="${cy}" stroke="var(--series-1)" stroke-width="2" stroke-linecap="round"/>
      <circle cx="${x(r.median)}" cy="${cy}" r="5" fill="var(--series-1)" stroke="var(--surface)" stroke-width="2"/>
      <rect class="hit" x="0" y="${i * rowH}" width="${W}" height="${rowH}" data-tip="${esc(tipText)}"/>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pay range by track">${grid}${body}</svg>`;
}

function tableView(head, rows) {
  return `<details class="table-view"><summary>Show as table</summary><table class="grid">
    <thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></details>`;
}

async function renderInsights() {
  view().innerHTML = '<div class="sub">Loading…</div>';
  const d = await api("/api/insights");
  if (S.view !== "insights") return;
  const f = d.funnel;
  const funnel = [["Applied", f.applied], ["Got a reply", f.responded], ["Interviewed", f.interviewed], ["Offers", f.offers]];
  const pct = n => f.applied ? ` (${Math.round(100 * n / f.applied)}%)` : "";
  view().innerHTML = `
    <div class="page-head"><div class="grow"><h1>Insights</h1>
      <p>Based on ${d.matched_jobs} jobs matching your searches (${d.with_details} with full descriptions) and ${f.applied} applications.</p></div></div>
    <div class="viz viz-grid">
      <section class="card"><h3>Applications per week</h3><p class="cap">Last 12 weeks</p>
        ${columnChart(d.weeks, "applied", "var(--series-1)", "applications")}
        ${tableView(["Week of", "Applied"], d.weeks.map(w => [shortDate(w.week), w.applied]))}</section>
      <section class="card"><h3>New matching jobs found per week</h3><p class="cap">Jobs first seen by a crawl, last 12 weeks</p>
        ${columnChart(d.weeks, "found", "var(--series-1)", "new jobs")}
        ${tableView(["Week of", "New jobs"], d.weeks.map(w => [shortDate(w.week), w.found]))}</section>
      <section class="card"><h3>Application funnel</h3><p class="cap">How far your applications get</p>
        ${f.applied ? hbarChart(funnel, { label: r => r[0], value: r => r[1], color: () => "var(--series-1)",
            tip: r => `<b>${r[0]}</b>${r[1]}${pct(r[1])}` }) : '<p class="sub">Mark some jobs as applied to see this.</p>'}
        ${f.applied ? tableView(["Stage", "Count"], funnel.map(r => [r[0], r[1] + pct(r[1])])) : ""}</section>
      <section class="card"><h3>Pay range by track</h3><p class="cap">Entry &amp; mid-level roles only · line = lowest to highest listed pay · dot = median (hourly pay × 2,080)</p>
        ${d.pay.length ? payChart(d.pay) : '<p class="sub">No listed pay yet. It appears after descriptions are read.</p>'}
        ${d.pay.length ? tableView(["Track", "Low", "Median", "High", "Postings"], d.pay.map(r => [esc(r.track), money(r.min), money(r.median), money(r.max), r.n])) : ""}</section>
      <section class="card" style="grid-column:1/-1"><h3>Most requested skills</h3>
        <p class="cap">Across matching job descriptions${d.has_profile ? " · compared with your resume" : ' · add your resume under "My resume" to see which you have'}</p>
        ${d.has_profile ? `<div class="legend"><span><i style="background:var(--series-1)"></i>On your resume</span><span><i style="background:var(--series-2)"></i>Missing</span></div>` : ""}
        ${d.skills.length ? hbarChart(d.skills, { W: 1060, label: r => r.skill, value: r => r.jobs,
            color: r => !d.has_profile || r.have ? "var(--series-1)" : "var(--series-2)",
            tip: r => `<b>${esc(r.skill)}</b>${r.jobs} job${r.jobs > 1 ? "s" : ""} mention it${d.has_profile ? (r.have ? " · on your resume" : " · not on your resume") : ""}` })
          : '<p class="sub">No skills found yet.</p>'}
        ${d.skills.length ? tableView(["Skill", "Jobs", "On resume"], d.skills.map(r => [esc(r.skill), r.jobs, d.has_profile ? (r.have ? "Yes" : "No") : "–"])) : ""}</section>
    </div>`;
}

// One tooltip for every chart: follows the pointer over any [data-tip] hit area.
const chartTip = document.createElement("div");
chartTip.className = "tip"; chartTip.hidden = true; document.body.append(chartTip);
view().addEventListener("mousemove", e => {
  const t = e.target.closest("[data-tip]");
  if (!t) { chartTip.hidden = true; return; }
  chartTip.innerHTML = t.dataset.tip; chartTip.hidden = false;
  const x = Math.min(e.clientX + 14, innerWidth - chartTip.offsetWidth - 8);
  chartTip.style.left = x + "px"; chartTip.style.top = (e.clientY + 14) + "px";
});
view().addEventListener("mouseleave", () => { chartTip.hidden = true; });

/* ------------------------------------------------------------------ crawl */
let pollTimer = null;
$("#crawlBtn").addEventListener("click", async () => {
  if (!S.region) { openAreaDialog(); return; }
  try {
    await api("/api/crawl", { method: "POST" });
    S.crawl.running = true;
    pollCrawl();
  } catch (err) { toast(err.message); }
});

async function pollCrawl() {
  clearTimeout(pollTimer);
  let st;
  try { st = await api("/api/crawl"); }
  catch { pollTimer = setTimeout(pollCrawl, 3000); return; }  // server busy/unreachable: keep the current state and retry
  const wasRunning = S.crawl.running;
  S.crawl = st;
  const btn = $("#crawlBtn"), bar = $("#crawlBar"), meta = $("#crawlMeta");
  if (st.running) {
    const srcs = Object.values(st.sources || {});
    const done = srcs.filter(s => ["ok", "error", "skipped"].includes(s.state)).length;
    const d = st.details || { done: 0, total: 0 };
    const pct = st.phase === "Reading job descriptions"
      ? 60 + 40 * (d.total ? d.done / d.total : 1) : 60 * (srcs.length ? done / srcs.length : 0);
    btn.disabled = true; btn.textContent = "Crawling…";
    bar.hidden = false; bar.firstElementChild.style.width = pct.toFixed(0) + "%";
    meta.textContent = st.phase === "Reading job descriptions" ? `Reading descriptions ${d.done}/${d.total}` : `Searching sites ${done}/${srcs.length}`;
    pollTimer = setTimeout(pollCrawl, 1200);
    return;
  }
  btn.disabled = false; btn.textContent = "Run crawl"; bar.hidden = true;
  if (wasRunning && st.error) {
    toast(st.error);
  } else if (wasRunning) {
    const failed = Object.values(st.sources || {}).filter(s => s.state === "error").length;
    toast(`Crawl finished: ${st.new || 0} new jobs${failed ? `, ${failed} site(s) failed (see Sources)` : ""}`);
    try { await refreshAll(); } catch (err) { toast(err.message); }
    return;  // refreshAll polls again, which updates the footer
  }
  const s = await api("/api/settings").catch(() => null);
  meta.textContent = s?.last_run ? `Last crawl ${ago(s.last_run.finished_at)} · ${s.last_run.new} new` : "Never crawled. Hit Run crawl.";
}

/* ------------------------------------------------------------------- area */
const escapeRx = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

async function loadRegion() {
  const st = await api("/api/settings");
  S.region = st.region;
  S.states = st.states;
  S.areaRx = st.region ? new RegExp(`\\b(?:${st.region.area_terms.map(escapeRx).join("|")})\\b`, "i") : null;
}

function openAreaDialog() {
  const f = $("#areaForm"), r = S.region;
  $("#areaState").innerHTML = '<option value="">State…</option>' +
    Object.entries(S.states || {}).map(([code, name]) => `<option value="${code}">${esc(name)}</option>`).join("");
  f.city.value = r?.city || "";
  f.state.value = r?.state || "";
  f.nearby.value = (r?.nearby || []).join(", ");
  f.radius.value = r?.radius || 50;
  $("#areaDialog").returnValue = "";
  $("#areaDialog").showModal();
}

$("#areaDialog").addEventListener("close", async () => {
  if ($("#areaDialog").returnValue !== "ok") return;
  const body = Object.fromEntries(new FormData($("#areaForm")));
  try {
    await api("/api/settings", { method: "POST", body: { region: body } });
    await loadRegion();
    toast(`Area set to ${S.region.label}. Hit Run crawl to search it.`);
    if (S.view === "settings") renderSettings();
  } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------------------ theme */
function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  document.querySelectorAll("#themeSwitch [data-theme-set]").forEach(b => b.setAttribute("aria-pressed", b.dataset.themeSet === t));
}
applyTheme(load("theme", "system"));
$("#themeSwitch").addEventListener("click", e => {
  const b = e.target.closest("[data-theme-set]");
  if (!b) return;
  save("theme", b.dataset.themeSet);
  applyTheme(b.dataset.themeSet);
});

/* ------------------------------------------------------------------- boot */
// Heartbeat + goodbye let the server quit only after every window is really closed.
const heartbeat = () => fetch(`/api/ping?client=${CLIENT_ID}`, { method: "POST" }).then(connectionOk, connectionLost);
setInterval(heartbeat, 20000);
heartbeat();
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") heartbeat(); });
window.addEventListener("pagehide", () => navigator.sendBeacon(`/api/bye?client=${CLIENT_ID}`));

async function refreshAll() {
  await loadSearches();
  await Promise.all([loadJobs({ fresh: true }), loadTrackerCount(), loadProfile(), loadRegion()]);
  go(S.view);
  pollCrawl();
}

(async function boot() {
  try {
    await loadSearches();
    await Promise.all([loadJobs(), loadTrackerCount(), loadProfile(), loadRegion()]);
    if (!S.region) openAreaDialog();
    // deep links: #tracker, #settings, #compare=12,34
    const [hashView, ids] = location.hash.slice(1).split("=");
    if (ids) { S.compare = new Set(ids.split(",").map(Number).slice(0, MAX_COMPARE)); save("compare", [...S.compare]); }
    go(["jobs", "compare", "tracker", "insights", "profile", "searches", "settings"].includes(hashView) ? hashView : "jobs");
    await pollCrawl();
  } catch (err) {
    view().innerHTML = `<div class="empty">Couldn't reach the JobHuntr server: ${esc(err.message)}</div>`;
  }
})();
