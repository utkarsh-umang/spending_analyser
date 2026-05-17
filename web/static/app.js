const PAGE_SIZE = 50;

let currentView = "overview";
let currentTable = "transactions";
let tableOffset = 0;
let tableTotal = 0;
let pendingCorrection = null;

const FIX_PLACEHOLDER =
  "Move the Zepto ₹464 transaction from Groceries to Quick Commerce";
const ASK_PLACEHOLDER = "What were my top expense categories in 2024?";

function $(id) {
  return document.getElementById(id);
}

function show(el) {
  el.classList.remove("hidden");
}

function hide(el) {
  el.classList.add("hidden");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function truncate(str, max = 36) {
  const s = String(str);
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function formatCell(col, val) {
  if (val == null) return "—";
  if (col === "amount" && typeof val === "number") {
    return val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (typeof val === "string" && val.length > 48) {
    return truncate(val, 48);
  }
  return String(val);
}

function renderAccounts(data) {
  const container = $("accounts");
  container.innerHTML = "";

  if (!data.accounts.length) {
    container.textContent = "No accounts configured.";
    return;
  }

  for (const account of data.accounts) {
    const card = document.createElement("div");
    card.className = "account-card";

    const title = document.createElement("h3");
    title.className = "account-card-title";
    title.textContent = account.label;
    title.title = `${account.id} · ${account.kind}`;
    card.appendChild(title);

    if (!account.files.length) {
      const empty = document.createElement("p");
      empty.className = "empty-account";
      empty.textContent = "No statement files";
      card.appendChild(empty);
    } else {
      for (const file of account.files) {
        const row = document.createElement("div");
        row.className = "file-row";
        const isDone = file.status === "processed";
        const badgeClass = isDone ? "badge-processed" : "badge-pending";
        const badgeLabel = isDone ? "Done" : "Pending";
        row.innerHTML = `
          <span class="file-name" title="${escapeHtml(file.path)}">${escapeHtml(truncate(file.name, 32))}</span>
          <span class="badge ${badgeClass}">${badgeLabel}</span>
        `;
        card.appendChild(row);
      }
    }

    container.appendChild(card);
  }
}

async function loadStatus() {
  const loading = $("accounts-loading");
  const errEl = $("accounts-error");
  hide(errEl);
  show(loading);

  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    $("stat-tx").textContent = data.transaction_count.toLocaleString();
    $("stat-processed").textContent = String(data.processed_file_count);
    $("stat-pending").textContent = String(data.pending_file_count);

    const exportBtn = $("export-btn");
    if (!data.db_exists || data.transaction_count === 0) {
      exportBtn.classList.add("btn-disabled");
      exportBtn.setAttribute("aria-disabled", "true");
      exportBtn.title = "No transactions to export yet";
    } else {
      exportBtn.classList.remove("btn-disabled");
      exportBtn.removeAttribute("aria-disabled");
      exportBtn.title = "";
    }

    renderAccounts(data);
    const lockBanner = $("db-locked-banner");
    if (data.db_locked) {
      show(lockBanner);
    } else {
      hide(lockBanner);
    }
  } catch (e) {
    errEl.textContent = `Failed to load status: ${e.message}`;
    show(errEl);
  } finally {
    hide(loading);
  }
}

function switchView(view) {
  currentView = view;
  document.querySelectorAll(".nav-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
  $("view-overview").classList.toggle("hidden", view !== "overview");
  $("view-data").classList.toggle("hidden", view !== "data");
  if (view === "data") {
    loadTableList().then(() => loadTable(currentTable));
  }
}

async function loadTableList() {
  const res = await fetch("/api/tables");
  if (!res.ok) return;
  const data = await res.json();
  const tabs = $("table-tabs");
  tabs.innerHTML = "";

  for (const t of data.tables) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "table-tab" + (t.id === currentTable ? " active" : "");
    btn.dataset.table = t.id;
    const countLabel =
      t.count != null ? ` (${Number(t.count).toLocaleString()})` : "";
    btn.textContent = `${t.label}${countLabel}`;
    btn.setAttribute("role", "tab");
    btn.addEventListener("click", () => {
      currentTable = t.id;
      tableOffset = 0;
      document.querySelectorAll(".table-tab").forEach((el) => {
        el.classList.toggle("active", el.dataset.table === t.id);
      });
      loadTable(t.id);
    });
    tabs.appendChild(btn);
  }

  if (!data.tables.some((t) => t.id === currentTable) && data.tables.length) {
    currentTable = data.tables[0].id;
  }

  const lockBanner = $("db-locked-banner");
  if (data.db_locked) {
    show(lockBanner);
  }
}

async function loadTable(tableId) {
  const loading = $("table-loading");
  const errEl = $("table-error");
  const table = $("data-table");
  const empty = $("table-empty");

  hide(errEl);
  hide(empty);
  show(loading);
  show(table);

  try {
    const res = await fetch(
      `/api/tables/${tableId}?limit=${PAGE_SIZE}&offset=${tableOffset}`
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const detail = body.detail;
      throw new Error(
        typeof detail === "string" ? detail : res.statusText
      );
    }
    const data = await res.json();
    tableTotal = data.total;
    renderDataTable(data);
    updatePager(data);
    $("table-count").textContent = `${data.total.toLocaleString()} rows total`;
  } catch (e) {
    errEl.textContent = `Failed to load table: ${e.message}`;
    show(errEl);
    $("data-thead").innerHTML = "";
    $("data-tbody").innerHTML = "";
  } finally {
    hide(loading);
  }
}

function renderDataTable(data) {
  const thead = $("data-thead");
  const tbody = $("data-tbody");
  const empty = $("table-empty");
  const table = $("data-table");

  if (!data.rows.length) {
    thead.innerHTML = "";
    tbody.innerHTML = "";
    hide(table);
    show(empty);
    return;
  }

  show(table);
  hide(empty);

  thead.innerHTML =
    "<tr>" +
    data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("") +
    "</tr>";

  tbody.innerHTML = data.rows
    .map((row) => {
      const cells = data.columns
        .map((col) => {
          const val = row[col];
          const cls = col === "amount" || col === "id" ? " num" : "";
          const title = val != null && String(val).length > 48 ? escapeHtml(String(val)) : "";
          return `<td class="${cls.trim()}"${title ? ` title="${title}"` : ""}>${escapeHtml(formatCell(col, val))}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
}

function updatePager(data) {
  const start = data.total === 0 ? 0 : data.offset + 1;
  const end = Math.min(data.offset + data.rows.length, data.total);
  $("pager-info").textContent =
    data.total === 0 ? "No rows" : `${start}–${end} of ${data.total}`;
  $("pager-prev").disabled = data.offset <= 0;
  $("pager-next").disabled = data.offset + data.rows.length >= data.total;
}

function getQueryMode() {
  const selected = document.querySelector('input[name="query-mode"]:checked');
  return selected ? selected.value : "ask";
}

function updateQueryModeUi() {
  const mode = getQueryMode();
  const btn = $("analyze-btn");
  const textarea = $("question");
  if (mode === "fix") {
    btn.textContent = "Find transaction";
    textarea.placeholder = FIX_PLACEHOLDER;
  } else {
    btn.textContent = "Ask";
    textarea.placeholder = ASK_PLACEHOLDER;
  }
  hideCorrectionConfirm();
}

function hideCorrectionConfirm() {
  pendingCorrection = null;
  hide($("correction-confirm"));
}

function formatRupee(amount) {
  return `₹${Number(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function showCorrectionPlan(plan) {
  pendingCorrection = plan;
  hide($("analyze-result"));
  hide($("analyze-error"));

  const panel = $("correction-confirm");
  const msg = $("correction-message");
  const list = $("correction-candidates");
  const change = $("correction-change");
  const applyBtn = $("correction-apply-btn");

  msg.textContent = plan.message || "";

  if (plan.status === "not_a_correction") {
    change.textContent =
      "This looks like an analytics question — switch to Analyze mode, or rephrase as a fix request.";
    list.innerHTML = "";
    applyBtn.disabled = true;
    show(panel);
    return;
  }

  if (!plan.transactions || !plan.transactions.length) {
    change.textContent = plan.errors?.length
      ? plan.errors.join(" ")
      : "No matching transactions found.";
    list.innerHTML = "";
    applyBtn.disabled = true;
    show(panel);
    return;
  }

  const newCat = plan.new_category || "?";
  change.innerHTML = `Change category → <strong>${escapeHtml(newCat)}</strong>`;
  if (plan.merchant_patterns?.length) {
    change.innerHTML += `<br /><span class="correction-candidate-meta">Future patterns: ${escapeHtml(
      plan.merchant_patterns.join(", ")
    )}</span>`;
  }

  list.innerHTML = "";
  const defaultChecked = plan.status === "ready";
  for (const tx of plan.transactions) {
    const li = document.createElement("li");
    li.className = "correction-candidate";
    li.innerHTML = `
      <input type="checkbox" class="correction-pick" data-id="${tx.id}" ${
        defaultChecked || plan.transactions.length === 1 ? "checked" : ""
      } />
      <div>
        <div><strong>${escapeHtml(String(tx.date))}</strong> · ${formatRupee(tx.amount)} · ${escapeHtml(tx.category)}</div>
        <div class="correction-candidate-meta">${escapeHtml(truncate(tx.description, 42))}</div>
      </div>
    `;
    list.appendChild(li);
  }

  applyBtn.disabled = !plan.can_apply;
  show(panel);
}

async function planCorrection(request) {
  const res = await fetch("/api/corrections/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request }),
  });
  const body = await res.json();
  if (!res.ok) {
    const detail = body.detail;
    throw new Error(
      typeof detail === "string" ? detail : res.statusText
    );
  }
  return body;
}

async function applyCorrection() {
  if (!pendingCorrection) return;

  const ids = [...document.querySelectorAll(".correction-pick:checked")].map((el) =>
    parseInt(el.dataset.id, 10)
  );
  if (!ids.length) {
    $("analyze-error").textContent = "Select at least one transaction.";
    show($("analyze-error"));
    return;
  }

  const payload = {
    transaction_ids: ids,
    new_category: pendingCorrection.new_category,
    new_type: pendingCorrection.new_type || null,
    merchant_patterns: pendingCorrection.merchant_patterns || [],
    save_payee: pendingCorrection.save_payee || null,
  };

  const applyBtn = $("correction-apply-btn");
  applyBtn.disabled = true;

  try {
    const res = await fetch("/api/corrections/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) {
      const detail = body.detail;
      throw new Error(
        typeof detail === "string" ? detail : res.statusText
      );
    }

    hideCorrectionConfirm();
    const result = $("analyze-result");
    result.textContent = `Updated ${body.updated_count} transaction(s) to "${body.new_category}".`;
    if (body.merchant_patterns_saved) {
      result.textContent += ` Saved ${body.merchant_patterns_saved} merchant pattern(s) for future runs.`;
    }
    if (body.payee_saved) {
      result.textContent += ` Remembered payee: ${body.payee_saved}.`;
    }
    show(result);
    loadStatus();
  } catch (e) {
    $("analyze-error").textContent = `Could not apply: ${e.message}`;
    show($("analyze-error"));
  } finally {
    applyBtn.disabled = false;
  }
}

async function submitQuestion(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;

  const btn = $("analyze-btn");
  const loading = $("analyze-loading");
  const errEl = $("analyze-error");
  const result = $("analyze-result");
  const mode = getQueryMode();

  hide(errEl);
  hide(result);
  hideCorrectionConfirm();
  show(loading);
  btn.disabled = true;

  try {
    if (mode === "fix") {
      const plan = await planCorrection(question);
      showCorrectionPlan(plan);
    } else {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const body = await res.json();
      if (!res.ok) {
        const detail = body.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d) => d.msg || String(d)).join("; ")
          : detail || res.statusText;
        throw new Error(msg);
      }
      result.textContent = body.answer;
      show(result);
    }
  } catch (e) {
    errEl.textContent =
      mode === "fix" ? `Could not plan fix: ${e.message}` : `Analysis failed: ${e.message}`;
    show(errEl);
  } finally {
    hide(loading);
    btn.disabled = false;
  }
}

document.querySelectorAll(".nav-tab").forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

$("refresh-btn").addEventListener("click", () => {
  loadStatus();
  if (currentView === "data") {
    loadTableList().then(() => loadTable(currentTable));
  }
});

$("pager-prev").addEventListener("click", () => {
  tableOffset = Math.max(0, tableOffset - PAGE_SIZE);
  loadTable(currentTable);
});

$("pager-next").addEventListener("click", () => {
  tableOffset += PAGE_SIZE;
  loadTable(currentTable);
});

$("analyze-form").addEventListener("submit", submitQuestion);

document.querySelectorAll('input[name="query-mode"]').forEach((el) => {
  el.addEventListener("change", updateQueryModeUi);
});

$("correction-apply-btn").addEventListener("click", applyCorrection);
$("correction-cancel-btn").addEventListener("click", hideCorrectionConfirm);

updateQueryModeUi();
loadStatus();
