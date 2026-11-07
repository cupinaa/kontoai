"use strict";

const SOURCE_LABELS = { history: "Istorija", rule: "Pravilo", llm: "LLM", none: "—" };
const $ = (id) => document.getElementById(id);

const state = { accounts: [], clientId: null, threshold: 0.75 };

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

function accountOptions(selected) {
  const placeholder = selected ? "" : '<option value="" selected disabled>Izaberi konto…</option>';
  return placeholder + state.accounts
    .map((a) => `<option value="${esc(a.konto)}"${a.konto === selected ? " selected" : ""}>${esc(a.konto)} — ${esc(a.naziv)}</option>`)
    .join("");
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
  const auto = data.items.filter((r) => !r.suggestion.needs_review).length;
  $("stats").innerHTML = `
    <div class="stat"><b>${total}</b><span>stavki</span></div>
    <div class="stat"><b>${auto}</b><span>bez provere</span></div>
    <div class="stat"><b>${data.needs_review_count}</b><span>za proveru</span></div>`;
}

function renderItems(data) {
  const currency = data.invoice ? data.invoice.currency : null;
  const tbody = $("items");
  tbody.innerHTML = "";
  data.items.forEach((result, index) => {
    const { item, suggestion: s } = result;
    const pct = Math.round(s.confidence * 100);
    const tr = document.createElement("tr");
    if (s.needs_review) tr.classList.add("review");
    const qty = item.quantity != null ? `${item.quantity} ${item.unit || ""}`.trim() : "";
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td><div class="item-name">${esc(item.name)}</div>${qty ? `<div class="muted small">${esc(qty)}</div>` : ""}</td>
      <td class="num">${esc(money(item.amount, currency))}</td>
      <td>${s.konto ? `<span class="konto">${esc(s.konto)}</span><span class="konto-name">${esc(s.konto_name)}</span>` : '<span class="muted">nema predloga</span>'}</td>
      <td><span class="pill src-${esc(s.source)}">${esc(SOURCE_LABELS[s.source] || s.source)}</span>
          ${s.needs_review ? '<div><span class="pill pill-warn" style="margin-top:6px">Proveriti</span></div>' : ""}</td>
      <td class="num">${pct}%<div class="meter${s.confidence < state.threshold ? " low" : ""}"><i style="width:${pct}%"></i></div></td>
      <td class="explanation">${esc(s.explanation)}</td>
      <td class="decide-cell"></td>`;

    const cell = tr.querySelector(".decide-cell");
    cell.innerHTML = `<div class="decide">
        <select aria-label="Konto za stavku ${index + 1}">${accountOptions(s.konto)}</select>
        <button type="button" class="btn btn-sm">${s.konto ? "Potvrdi" : "Sačuvaj"}</button>
      </div>`;
    const select = cell.querySelector("select");
    const button = cell.querySelector("button");
    select.addEventListener("change", () => {
      button.textContent = select.value === s.konto ? "Potvrdi" : "Ispravi";
    });
    button.addEventListener("click", () => confirmItem({ item, suggestion: s, select, button, cell, tr }));
    tbody.appendChild(tr);
  });
}

async function confirmItem({ item, suggestion, select, button, cell, tr }) {
  if (!select.value) {
    select.focus();
    return;
  }
  button.disabled = true;
  try {
    const result = await api("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: state.clientId,
        item_name: item.name,
        konto: select.value,
        supplier_name: item.supplier_name,
        supplier_pib: item.supplier_pib,
        suggested_konto: suggestion.konto,
        suggested_source: suggestion.source,
      }),
    });
    tr.classList.remove("review");
    tr.classList.add("done");
    const label = result.status === "corrected" ? "Ispravljeno" : "Potvrđeno";
    cell.innerHTML = `<span class="confirmed">✓ ${label}: ${esc(result.record.konto)}</span>`;
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
          <td><span class="konto">${esc(r.konto)}</span><span class="konto-name">${esc(r.konto_name || "")}</span></td>
          <td>${r.suggested_konto ? esc(r.suggested_konto) + " · " + esc(SOURCE_LABELS[r.suggested_source] || "") : "—"}</td>
          <td>${r.corrected ? '<span class="pill pill-warn">Ispravljeno</span>' : '<span class="pill pill-ok">Potvrđeno</span>'}</td>
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
