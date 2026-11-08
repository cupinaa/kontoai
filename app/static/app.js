"use strict";

/* KontoAI web page: one screen. Same API as before; history and the analytic plan work in the
   background (confirmations are stored, the plan feeds the analytic dropdown). */

const $ = (id) => document.getElementById(id);
const CHECK_PATH = '<path d="M5 12.5l4.2 4.2L19 7"/>';
const STATUS_OK = '<span class="status status-ok" aria-label="Usklađeno"><svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="8"/><path d="M4.6 8.3l2.2 2.2 4.6-4.8"/></svg></span>';
const STATUS_WARN = '<span class="status status-warn" aria-label="Za proveru"></span>';

const state = {
  accounts: new Map(),   // konto -> naziv
  clients: [],
  clientId: null,
  plan: [],              // analytic accounts of the current client
  invoice: null,
  rows: [],              // { item, s, base, choice: {konto, analytic}, confirmed, tr }
  selected: -1,
};

/* ------------------------------------------------------------------ helpers */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function money(amount) {
  if (amount == null) return "—";
  return amount.toLocaleString("sr-Latn-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function date(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("sr-Latn-RS");
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
    throw new Error(detail || `Greška ${response.status}`);
  }
  return body;
}
let toastTimer;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}
function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (err) { /* private mode: not needed */ }
  return null;
}
function client() {
  return state.clients.find((c) => c.id === state.clientId) || { id: state.clientId, delatnost: "" };
}

/* ------------------------------------------------------------------ status */

function analyticOptions(konto) {
  return state.plan.filter((a) => a.sintetika === konto);
}
function syntheticAligned(row) {
  const s = row.s;
  if (s.given_konto) return s.given_check === "match";
  return Boolean(s.konto) && !s.needs_review;
}
// The analytic part is fine when there is nothing to choose, when the accountant picked it herself,
// or when the system's preselected analytic is confident and fits.
function analyticSettled(row) {
  if (!state.plan.length || analyticOptions(row.choice.konto).length === 0) return true;
  if (!row.choice.analytic) return false;
  if (row.analyticTouched) return true;
  const a = row.s.analytic;
  return Boolean(a) && a.konto === row.choice.analytic && !a.needs_review;
}
// Green check = the 3-digit account matches Iris (or is confident) AND the analytic account is settled.
function isAligned(row) {
  return syntheticAligned(row) && analyticSettled(row);
}
function readyToConfirm(row) {
  return !row.confirmed && isAligned(row);
}

/* Short display name for the table: the plan's "kratko" (e.g. "Zakup magacina"), else the full name. */
function shortName(account) {
  return (account && (account.kratko || account.naziv)) || "";
}
const STOP = new Set(["za", "i", "u", "na", "od", "po", "sa", "do", "troskovi", "trosak", "usluge", "usluga"]);
function stems(text) {
  const plain = (text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "dj");
  return new Set(plain.split(/[^a-z0-9]+/).filter((w) => w.length > 2 && !STOP.has(w) && !/^\d+$/.test(w)).map((w) => w.slice(0, 5)));
}
function closestOption(text, options) {
  const words = stems(text);
  let best = options[0];
  let score = -1;
  options.forEach((o) => {
    const s = [...stems(o.naziv)].filter((w) => words.has(w)).length;
    if (s > score) { best = o; score = s; }
  });
  return best;
}

/* ------------------------------------------------------------------ client */

async function loadPlan() {
  try {
    state.plan = (await api(`/analytic-plan/${encodeURIComponent(state.clientId)}`)).accounts;
  } catch (err) {
    state.plan = [];
  }
}

async function selectClient(id) {
  state.clientId = id;
  storage("kontoai.client", id);
  await loadPlan();
  resetInvoice();
}

/* ------------------------------------------------------------------ upload */

function resetInvoice() {
  state.invoice = null;
  state.rows = [];
  closePanel();
  $("result").hidden = true;
  $("all-done").hidden = true;
  $("drop").hidden = false;
  $("mascot").hidden = false;
  $("file").value = "";
}

async function upload(file) {
  if (!file) return;
  const drop = $("drop");
  drop.classList.add("busy");
  $("drop-title").textContent = "Obrađujem…";
  const form = new FormData();
  form.append("file", file);
  form.append("client_activity", client().delatnost || "nepoznata delatnost");
  form.append("client_id", state.clientId);
  try {
    const data = await api("/invoices/xml", { method: "POST", body: form });
    renderInvoice(data);
  } catch (err) {
    toast(err.message);
  } finally {
    drop.classList.remove("busy");
    $("drop-title").textContent = "Prevucite fakturu ili izaberite fajl";
    $("file").value = "";
  }
}

/* ------------------------------------------------------------------ invoice */

function renderInvoice(data) {
  state.invoice = data.invoice;
  const inv = data.invoice || {};
  const total = data.items.reduce((sum, r) => sum + (r.item.amount || 0), 0);
  $("inv-supplier").textContent = (inv.supplier && inv.supplier.name) || "Faktura";
  $("inv-meta").textContent = [inv.number ? `Faktura ${inv.number}` : "", date(inv.issue_date)].filter(Boolean).join(" · ");
  $("inv-total").textContent = `${money(total)} ${inv.currency || "RSD"}`;

  state.rows = data.items.map(({ item, suggestion: s }) => {
    // Preselected account: the accountant's earlier decision for this item, else Iris, else the system.
    const base = (s.previous_choice && s.previous_choice.konto) || s.given_konto || s.konto;
    return { item, s, base, choice: { konto: base, analytic: (s.analytic && s.analytic.konto) || "" },
             confirmed: false, analyticTouched: false };
  });

  const tbody = $("items");
  tbody.innerHTML = "";
  state.rows.forEach((row, index) => {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.className = "fade-in";
    tr.style.animationDelay = `${Math.min(index, 8) * 30}ms`;
    row.tr = tr;
    tbody.appendChild(tr);
    renderRow(index);
    tr.addEventListener("click", (e) => {
      if (e.target.closest("select, button")) return;
      closePicker();
      openPanel(index);
    });
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target === tr) openPanel(index);
    });
  });

  $("item-count").textContent = `${state.rows.length} ${state.rows.length === 1 ? "stavka" : "stavki"}`;
  $("drop").hidden = true;
  $("mascot").hidden = true;
  $("result").hidden = false;
  updateConfirmAll();
}

function analyticSelect(row, cls) {
  if (!state.plan.length) return '<span class="dash">—</span>';
  const options = analyticOptions(row.choice.konto);
  if (!options.length) return '<span class="dash">—</span>';
  const empty = `<option value=""${row.choice.analytic ? "" : " selected"}>Izaberi…</option>`;
  const opts = options.map((a) =>
    `<option value="${esc(a.konto)}"${a.konto === row.choice.analytic ? " selected" : ""}>${esc(a.konto)} ${esc(a.naziv)}</option>`
  ).join("");
  return `<select class="${cls}${row.choice.analytic ? "" : " empty"}"${row.confirmed ? " disabled" : ""} aria-label="Analitika">${empty}${opts}</select>`;
}

/* The full account in one place: "533" + "1" (the analytic digit in blue), the short analytic name below. */
function kontoCell(row) {
  const konto = row.choice.konto;
  const status = isAligned(row) ? STATUS_OK : STATUS_WARN;
  if (!konto) {
    return `<button type="button" class="konto-cell" data-act="panel"><span class="konto-line"><span class="konto-num"><span class="k3">—</span></span>${status}</span>
      <span class="konto-sub">Izaberi</span></button>`;
  }
  if (!state.plan.length) {
    return `<span class="konto-cell static"><span class="konto-line"><span class="konto-num"><span class="k3">${esc(konto)}</span></span>${status}</span></span>`;
  }
  const options = analyticOptions(konto);
  const chosen = options.find((o) => o.konto === row.choice.analytic);
  if (!chosen) {
    // No analytic chosen (normally only when nothing exists below this account): the empty blue slot.
    const act = options.length ? "picker" : "panel";
    const hint = options.length ? "Izaberite analitiku" : `Ispod konta ${esc(konto)} nema analitike`;
    return `<button type="button" class="konto-cell" data-act="${act}" title="${hint}">
      <span class="konto-line"><span class="konto-num"><span class="k3">${esc(konto)}</span><span class="k4 empty">_</span></span>${status}</span>
      <span class="konto-sub">Izaberi</span></button>`;
  }
  const rest = chosen.konto.slice(konto.length);
  return `<button type="button" class="konto-cell" data-act="picker" aria-haspopup="listbox" title="${esc(chosen.konto)} ${esc(chosen.naziv)}">
    <span class="konto-line"><span class="konto-num"><span class="k3">${esc(konto)}</span><span class="k4">${esc(rest)}</span></span>${status}</span>
    <span class="konto-sub">${esc(shortName(chosen))}</span></button>`;
}

function renderRow(index) {
  const row = state.rows[index];
  const { item, tr } = row;
  tr.classList.toggle("confirmed", row.confirmed);
  tr.classList.toggle("selected", index === state.selected);
  tr.innerHTML = `
    <td><div class="desc">${esc(item.name)}</div></td>
    <td class="num">${money(item.amount)}</td>
    <td>${kontoCell(row)}</td>
    <td class="col-action"><button type="button" class="confirm${row.confirmed ? " done" : ""}" aria-label="Potvrdi"${row.confirmed ? " disabled" : ""}><svg viewBox="0 0 24 24">${CHECK_PATH}</svg></button></td>`;

  const cell = tr.querySelector("button.konto-cell");
  if (cell) cell.addEventListener("click", (e) => {
    e.stopPropagation();
    if (cell.dataset.act === "picker" && !row.confirmed) openPicker(index, cell);
    else openPanel(index);
  });
  tr.querySelector(".confirm").addEventListener("click", () => confirmRow(index));
}

/* ------------------------------------------------------------------ analytic picker (small popover) */

let picker = null;
function closePicker() {
  if (!picker) return;
  picker.el.remove();
  picker = null;
}
function setAnalytic(index, analytic) {
  const row = state.rows[index];
  row.choice.analytic = analytic;
  row.analyticTouched = true;
  renderRow(index);
  updateConfirmAll();
  if (state.selected === index) renderPanel();
}
function openPicker(index, anchor) {
  closePicker();
  const row = state.rows[index];
  const options = analyticOptions(row.choice.konto);
  const el = document.createElement("div");
  el.className = "picker";
  el.setAttribute("role", "listbox");
  el.innerHTML = options.map((o) => `
      <button type="button" role="option" class="picker-item${o.konto === row.choice.analytic ? " current" : ""}" data-konto="${esc(o.konto)}" aria-selected="${o.konto === row.choice.analytic}">
        <span class="picker-num">${esc(o.konto)}</span><span class="picker-name">${esc(o.naziv)}</span>
      </button>`).join("") +
    '<button type="button" class="picker-item picker-more" data-more="1">Drugi konto…</button>';
  document.body.appendChild(el);
  const box = anchor.getBoundingClientRect();
  el.style.left = `${Math.min(box.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - el.offsetWidth - 12)}px`;
  el.style.top = `${box.bottom + window.scrollY + 6}px`;
  el.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    closePicker();
    if (btn.dataset.more) openPanel(index);
    else setAnalytic(index, btn.dataset.konto);
  });
  picker = { el, index };
  const current = el.querySelector(".current") || el.querySelector(".picker-item");
  if (current) current.focus();
}
document.addEventListener("click", (e) => { if (picker && !picker.el.contains(e.target)) closePicker(); });

function updateConfirmAll() {
  const ready = state.rows.filter(readyToConfirm).length;
  const btn = $("confirm-all");
  btn.disabled = ready === 0;
  btn.textContent = ready ? `Potvrdi sve usklađene (${ready})` : "Potvrdi sve usklađene";
  const allDone = state.rows.length > 0 && state.rows.every((r) => r.confirmed);
  $("all-done").hidden = !allDone;
  btn.hidden = allDone;
}

async function confirmRow(index, { quiet = false } = {}) {
  const row = state.rows[index];
  if (row.confirmed) return true;
  if (!row.choice.konto) { openPanel(index); return false; }
  if (analyticOptions(row.choice.konto).length && !row.choice.analytic) {
    if (!quiet) toast("Izaberite analitiku");
    const cell = row.tr.querySelector("button.konto-cell");
    if (cell && !quiet) cell.click();
    return false;
  }
  const s = row.s;
  const a = s.analytic;
  try {
    await api("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: state.clientId,
        item_name: row.item.name,
        konto: row.choice.konto,
        supplier_name: row.item.supplier_name,
        supplier_pib: row.item.supplier_pib,
        // What was preselected (her earlier decision, Iris' account or the system's suggestion).
        suggested_konto: row.base,
        suggested_source: s.previous_choice ? "history" : (s.given_konto ? "input" : s.source),
        given_konto: s.given_konto || null,
        analytic_konto: row.choice.analytic || null,
        suggested_analytic: a ? a.konto : null,
        suggested_analytic_source: a ? a.source : null,
      }),
    });
  } catch (err) {
    toast(err.message);
    return false;
  }
  row.confirmed = true;
  renderRow(index);
  row.tr.querySelector(".confirm").classList.add("pop");
  updateConfirmAll();
  if (state.selected === index) renderPanel();
  return true;
}

async function confirmAll() {
  const indexes = state.rows.map((r, i) => (readyToConfirm(r) ? i : -1)).filter((i) => i >= 0);
  const btn = $("confirm-all");
  btn.disabled = true;
  let done = 0;
  for (const i of indexes) {
    if (await confirmRow(i, { quiet: true })) done += 1;
  }
  updateConfirmAll();
  if (done) toast(done === 1 ? "Potvrđena 1 stavka" : `Potvrđeno stavki: ${done}`);
}

/* ------------------------------------------------------------------ panel */

function openPanel(index) {
  const previous = state.selected;
  state.selected = index;
  if (previous >= 0 && state.rows[previous]) state.rows[previous].tr.classList.remove("selected");
  state.rows[index].tr.classList.add("selected");
  renderPanel();
  const panel = $("panel");
  panel.inert = false;
  panel.setAttribute("aria-hidden", "false");
  panel.classList.add("open");
  document.querySelector(".app").classList.add("panel-open");
}

function closePanel() {
  const panel = $("panel");
  panel.classList.remove("open");
  panel.setAttribute("aria-hidden", "true");
  panel.inert = true;
  document.querySelector(".app").classList.remove("panel-open");
  if (state.selected >= 0 && state.rows[state.selected]) state.rows[state.selected].tr.classList.remove("selected");
  state.selected = -1;
}

function kontoName(konto) {
  return state.accounts.get(konto) || "";
}

function renderPanel() {
  const index = state.selected;
  const row = state.rows[index];
  if (!row) return;
  const s = row.s;
  $("panel-title").textContent = row.item.name;

  let compare;
  if (s.given_konto) {
    const verdict = {
      match: [STATUS_OK, "Poklapa se sa Iris-om"],
      mismatch: [STATUS_WARN, "Razlikuje se od Iris-a"],
      unverified: [STATUS_WARN, "Sistem nema predlog"],
      not_in_chart: [STATUS_WARN, "Iris konto nije u kontnom okviru"],
    }[s.given_check] || [STATUS_WARN, ""];
    compare = `
      <div class="compare">
        <div class="compare-row"><span class="compare-who">Iris</span><span class="compare-konto">${esc(s.given_konto)}</span><span class="compare-name">${esc(kontoName(s.given_konto))}</span></div>
        <div class="compare-row"><span class="compare-who">Sistem</span><span class="compare-konto">${esc(s.konto || "—")}</span><span class="compare-name">${esc(s.konto ? kontoName(s.konto) : "")}</span></div>
      </div>
      <div class="verdict">${verdict[0]}<span>${esc(verdict[1])}</span></div>
      ${s.previous_choice ? `<div class="previous">Prošli put ste izabrali ${esc(s.previous_choice.konto)}${s.previous_choice.analytic_konto ? " · " + esc(s.previous_choice.analytic_konto) : ""}</div>` : ""}`;
  } else {
    compare = `
      <div class="compare">
        <div class="compare-row"><span class="compare-who">Predlog</span><span class="compare-konto">${esc(s.konto || "—")}</span><span class="compare-name">${esc(s.konto ? kontoName(s.konto) : "")}</span></div>
      </div>`;
  }

  const pct = Math.round((s.confidence || 0) * 100);
  const options = analyticOptions(row.choice.konto);
  const a = s.analytic;
  const kontoOptions = [...state.accounts.entries()].map(([k, n]) =>
    `<option value="${esc(k)}"${k === row.choice.konto ? " selected" : ""}>${esc(k)} ${esc(n)}</option>`).join("");

  $("panel-body").innerHTML = `
    <div>${compare}</div>
    <div>
      <div class="field-label">Sigurnost</div>
      <div class="meter-row"><div class="meter${pct < 75 ? " low" : ""}"><i style="width:${pct}%"></i></div><span>${pct}%</span></div>
    </div>
    <div>
      <div class="field-label">Obrazloženje</div>
      <p class="reason">${esc(s.source === "none" ? "Sistem nema predlog za ovu stavku." : s.explanation)}</p>
    </div>
    <div>
      <div class="field-label">Konto</div>
      <select id="panel-konto"${row.confirmed ? " disabled" : ""}>${row.choice.konto ? "" : '<option value="" selected disabled>Izaberi…</option>'}${kontoOptions}</select>
    </div>
    ${state.plan.length ? `
    <div>
      <div class="field-label">Analitika</div>
      ${options.length ? analyticSelect(row, "panel-analytic") : '<span class="dash">Nema analitike ispod ovog konta</span>'}
      ${a && a.poor_fit && a.konto === row.choice.analytic ? `
        <div class="poor-fit">
          <span>Nijedna analitika ne odgovara dobro</span>
          ${a.better_konto && a.better_konto !== row.choice.konto ? `<button type="button" class="btn-ghost btn-sm" id="use-better">Predlog: ${esc(a.better_konto)} ${esc(a.better_konto_name || "")}</button>` : ""}
        </div>` : ""}
      ${a && a.explanation && options.length && a.source !== "none" && !s.previous_choice ? `<p class="reason reason-sub">${esc(a.explanation.replace(/^Nijedna analitika ne odgovara dobro\.\s*/, ""))}</p>` : ""}
    </div>` : ""}
    <button class="btn-primary" id="panel-confirm" type="button"${row.confirmed ? " disabled" : ""}>${row.confirmed ? "Potvrđeno" : "Potvrdi"}</button>`;

  const switchKonto = (konto) => {
    row.choice.konto = konto;
    const opts = analyticOptions(konto);
    if (!opts.some((o) => o.konto === row.choice.analytic)) {
      // Always preselect: the system's analytic if it belongs to the new account, else the closest by wording.
      row.choice.analytic = a && opts.some((o) => o.konto === a.konto) ? a.konto
        : (opts.length ? closestOption(row.item.name, opts).konto : "");
      row.analyticTouched = false;
    }
    renderRow(index);
    updateConfirmAll();
    renderPanel();
  };
  const kontoSel = $("panel-konto");
  kontoSel.addEventListener("change", () => switchKonto(kontoSel.value));
  const better = $("use-better");
  if (better) better.addEventListener("click", () => switchKonto(a.better_konto));
  const analytic = $("panel-body").querySelector("select.panel-analytic");
  if (analytic) analytic.addEventListener("change", () => {
    row.choice.analytic = analytic.value;
    row.analyticTouched = true;
    renderRow(index);
    updateConfirmAll();
  });
  $("panel-confirm").addEventListener("click", () => confirmRow(index));
}

/* ------------------------------------------------------------------ start */

function setupDrop() {
  const drop = $("drop");
  const input = $("file");
  input.addEventListener("change", () => upload(input.files[0]));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
  });
}

async function init() {
  const [accounts, clients] = await Promise.all([
    api("/accounts").catch(() => []),
    fetch("/static/clients.json").then((r) => r.json()).catch(() => []),
  ]);
  accounts.forEach((a) => state.accounts.set(a.konto, a.naziv));
  state.clients = clients;
  const select = $("client");
  select.innerHTML = clients.map((c) => `<option value="${esc(c.id)}">${esc(c.id)} · ${esc(c.naziv)}</option>`).join("");
  const saved = storage("kontoai.client");
  const initial = clients.some((c) => c.id === saved) ? saved : (clients[0] && clients[0].id) || "K001";
  select.value = initial;
  select.addEventListener("change", () => selectClient(select.value));
  $("client-picker").hidden = clients.length <= 1;  // one client: nothing to choose, show nothing
  await selectClient(initial);
}

setupDrop();
$("new-invoice").addEventListener("click", resetInvoice);
$("confirm-all").addEventListener("click", confirmAll);
$("panel-close").addEventListener("click", closePanel);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (picker) closePicker();
  else closePanel();
});
init();
