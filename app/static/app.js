"use strict";

const SOURCE_LABELS = { history: "Istorija", rule: "Pravilo", llm: "LLM", input: "Ulaz", none: "—" };
const ANALYTIC_LABELS = { history: "Istorija", only_option: "Jedina opcija", llm: "LLM", none: "Bira knjigovođa" };
const $ = (id) => document.getElementById(id);

const state = { accounts: [], clientId: null, threshold: 0.75, plan: [], planStatus: null };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function money(amount, currency) {
  if (amount == null) return "—";
  return amount.toLocaleString("sr-Latn-RS", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " " + (currency || "RSD");
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

function showError(message) {
  const box = $("error");
  box.textContent = message;
  box.hidden = !message;
}

async function init() {
  try {
    const [health, accounts] = await Promise.all([api("/health"), api("/accounts")]);
    state.accounts = accounts;
    state.threshold = health.review_threshold;
    const status = $("status");
    if (health.llm) {
      status.textContent = `LLM: ${health.llm.model}`;
      status.className = "pill pill-ok";
    } else {
      status.textContent = "LLM nije konfigurisan (samo istorija i pravila)";
      status.className = "pill pill-warn";
    }
  } catch (err) {
    $("status").textContent = "Server nije dostupan";
    $("status").className = "pill pill-warn";
  }
}

async function loadPlan(clientId) {
  try {
    const plan = await api(`/analytic-plan/${encodeURIComponent(clientId)}`);
    state.plan = plan.accounts;
    state.planStatus = plan.status;
  } catch (err) {
    state.plan = [];
    state.planStatus = null;
  }
  const note = $("plan-note");
  note.hidden = !state.plan.length;
  if (state.plan.length) {
    note.textContent = state.planStatus === "probni"
      ? `Analitički plan klijenta (${state.plan.length} konta) je PROBNI — biće zamenjen izvozom iz knjigovodstvenog programa.`
      : `Analitički plan klijenta: ${state.plan.length} konta.`;
  }
}

function accountOptions(selected) {
  const placeholder = selected ? "" : '<option value="" selected disabled>Izaberi konto…</option>';
  return placeholder + state.accounts
    .map((a) => `<option value="${esc(a.konto)}"${a.konto === selected ? " selected" : ""}>${esc(a.konto)} — ${esc(a.naziv)}</option>`)
    .join("");
}

function analyticOptions(sintetika, selected) {
  const options = state.plan.filter((a) => a.sintetika === sintetika);
  if (!options.length) return { html: '<option value="">Nema analitike ispod ovog konta</option>', count: 0 };
  const placeholder = `<option value=""${selected ? "" : " selected"}>Izaberi analitiku…</option>`;
  const html = placeholder + options
    .map((a) => `<option value="${esc(a.konto)}"${a.konto === selected ? " selected" : ""}>${esc(a.konto)} — ${esc(a.naziv)}</option>`)
    .join("");
  return { html, count: options.length };
}

function renderMeta(data) {
  const inv = data.invoice;
  $("invoice-title").textContent = inv && inv.number ? `Faktura ${inv.number}` : "Faktura";
  const rows = [];
  if (inv) {
    if (inv.issue_date) rows.push(["Datum", inv.issue_date]);
    if (inv.supplier && inv.supplier.name) rows.push(["Dobavljač", `${inv.supplier.name}${inv.supplier.pib ? " · PIB " + inv.supplier.pib : ""}`]);
    if (inv.buyer && inv.buyer.name) rows.push(["Kupac", `${inv.buyer.name}${inv.buyer.pib ? " · PIB " + inv.buyer.pib : ""}`]);
  }
  rows.push(["Klijent", data.client_id], ["Delatnost", data.client_activity]);
  $("invoice-meta").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");

  const total = data.items.length;
  const auto = total - data.needs_review_count;
  $("stats").innerHTML = `
    <div class="stat"><b>${total}</b><span>stavki</span></div>
    <div class="stat"><b>${auto}</b><span>bez provere</span></div>
    <div class="stat"><b>${data.needs_review_count}</b><span>za proveru</span></div>`;
}

function confidenceCell(confidence) {
  const pct = Math.round(confidence * 100);
  return `${pct}%<div class="meter${confidence < state.threshold ? " low" : ""}"><i style="width:${pct}%"></i></div>`;
}

function analyticInfo(a) {
  if (!a) return "";
  const label = ANALYTIC_LABELS[a.source] || a.source;
  const pct = Math.round(a.confidence * 100);
  const review = a.needs_review ? ' <span class="pill pill-warn">Proveriti</span>' : "";
  return `<div class="analytic-info small"><span class="pill src-${esc(a.source)}">${esc(label)}</span>` +
    `${a.konto ? ` ${pct}%` : ""}${review}<div class="muted">${esc(a.explanation)}</div></div>`;
}

function renderItems(data) {
  const currency = data.invoice ? data.invoice.currency : null;
  const tbody = $("items");
  tbody.innerHTML = "";
  data.items.forEach((result, index) => {
    const { item, suggestion: s } = result;
    const a = s.analytic;
    const tr = document.createElement("tr");
    if (s.needs_review || (a && a.needs_review)) tr.classList.add("review");
    const qty = item.quantity != null ? `${item.quantity} ${item.unit || ""}`.trim() : "";
    const proposal = s.konto
      ? `<span class="konto">${esc(s.konto)}${a && a.konto ? " → " + esc(a.konto) : ""}</span>` +
        `<span class="konto-name">${esc(a && a.naziv ? a.naziv : s.konto_name)}</span>`
      : '<span class="muted">nema predloga</span>';
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td><div class="item-name">${esc(item.name)}</div>${qty ? `<div class="muted small">${esc(qty)}</div>` : ""}</td>
      <td class="num">${esc(money(item.amount, currency))}</td>
      <td>${proposal}</td>
      <td><span class="pill src-${esc(s.source)}">${esc(SOURCE_LABELS[s.source] || s.source)}</span>
          ${s.needs_review ? '<div><span class="pill pill-warn" style="margin-top:6px">Proveriti</span></div>' : ""}</td>
      <td class="num">${confidenceCell(s.confidence)}</td>
      <td class="explanation">${esc(s.explanation)}</td>
      <td class="decide-cell"></td>`;

    const cell = tr.querySelector(".decide-cell");
    const usesPlan = state.plan.length > 0;
    cell.innerHTML = `<div class="decide">
        <select class="sel-konto" aria-label="Sintetički konto za stavku ${index + 1}">${accountOptions(s.konto)}</select>
        ${usesPlan ? `<select class="sel-analytic" aria-label="Analitički konto za stavku ${index + 1}"></select>` : ""}
        <button type="button" class="btn btn-sm">Potvrdi</button>
      </div>${usesPlan ? analyticInfo(a) : ""}`;
    const konto = cell.querySelector(".sel-konto");
    const analytic = cell.querySelector(".sel-analytic");
    const button = cell.querySelector("button");

    const refreshAnalytic = () => {
      if (!analytic) return;
      const preselect = konto.value === s.konto && a ? a.konto : null;
      const { html, count } = analyticOptions(konto.value, preselect);
      analytic.innerHTML = html;
      analytic.disabled = count === 0;
    };
    const refreshLabel = () => {
      if (!s.konto) {
        button.textContent = "Sačuvaj";  // nothing was suggested, so nothing can be "corrected"
        return;
      }
      const changed = konto.value !== s.konto || (analytic && !analytic.disabled && analytic.value !== ((a && a.konto) || ""));
      button.textContent = changed ? "Ispravi" : "Potvrdi";
    };
    refreshAnalytic();
    refreshLabel();
    konto.addEventListener("change", () => { refreshAnalytic(); refreshLabel(); });
    if (analytic) analytic.addEventListener("change", refreshLabel);
    button.addEventListener("click", () => confirmItem({ item, suggestion: s, konto, analytic, button, cell, tr }));
    tbody.appendChild(tr);
  });
}

async function confirmItem({ item, suggestion, konto, analytic, button, cell, tr }) {
  if (!konto.value) {
    konto.focus();
    return;
  }
  const a = suggestion.analytic;
  const analyticValue = analytic && !analytic.disabled && analytic.value ? analytic.value : null;
  button.disabled = true;
  try {
    const result = await api("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: state.clientId,
        item_name: item.name,
        konto: konto.value,
        supplier_name: item.supplier_name,
        supplier_pib: item.supplier_pib,
        suggested_konto: suggestion.konto,
        suggested_source: suggestion.source,
        analytic_konto: analyticValue,
        suggested_analytic: a ? a.konto : null,
        suggested_analytic_source: a ? a.source : null,
      }),
    });
    tr.classList.remove("review");
    tr.classList.add("done");
    const label = result.status === "corrected" ? "Ispravljeno" : "Potvrđeno";
    const r = result.record;
    cell.innerHTML = `<span class="confirmed">✓ ${label}: ${esc(r.konto)}${r.analytic_konto ? " → " + esc(r.analytic_konto) : ""}</span>`;
    loadHistory();
  } catch (err) {
    button.disabled = false;
    alert(err.message);
  }
}

async function loadHistory() {
  if (!state.clientId) return;
  const rows = await api(`/history/${encodeURIComponent(state.clientId)}`);
  $("history").hidden = false;
  $("history-rows").innerHTML = rows.length
    ? rows.map((r) => `
        <tr>
          <td class="small">${esc(new Date(r.confirmed_at).toLocaleString("sr-Latn-RS"))}</td>
          <td>${esc(r.item_name)}</td>
          <td>${esc(r.supplier_name || "—")}</td>
          <td><span class="konto">${esc(r.konto)}${r.analytic_konto ? " → " + esc(r.analytic_konto) : ""}</span>
              <span class="konto-name">${esc(r.analytic_name || r.konto_name || "")}</span></td>
          <td>${r.suggested_konto ? esc(r.suggested_konto) + (r.suggested_analytic ? " → " + esc(r.suggested_analytic) : "") + " · " + esc(SOURCE_LABELS[r.suggested_source] || "") : "—"}</td>
          <td>${r.corrected || r.analytic_corrected ? '<span class="pill pill-warn">Ispravljeno</span>' : '<span class="pill pill-ok">Potvrđeno</span>'}</td>
        </tr>`).join("")
    : '<tr><td colspan="6" class="muted">Još nema potvrđenih kontiranja za ovog klijenta.</td></tr>';
}

function setupDrop() {
  const drop = $("drop");
  const input = $("file");
  const title = $("drop-title");
  input.addEventListener("change", () => {
    title.textContent = input.files.length ? input.files[0].name : "Izaberi XML fajl";
  });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change"));
    }
  });
}

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  const form = new FormData(event.target);
  if (!form.get("client_id")) form.delete("client_id");
  const submit = $("submit");
  submit.disabled = true;
  submit.textContent = "Obrada…";
  try {
    const data = await api("/invoices/xml", { method: "POST", body: form });
    state.clientId = data.client_id;
    await loadPlan(data.client_id);
    renderMeta(data);
    renderItems(data);
    $("result").hidden = false;
    await loadHistory();
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(err.message);
  } finally {
    submit.disabled = false;
    submit.textContent = "Predloži kontiranje";
  }
});

$("refresh-history").addEventListener("click", loadHistory);
setupDrop();
init();
