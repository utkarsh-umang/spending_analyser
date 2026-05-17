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
  div.textContent = text;
  return div.innerHTML;
}

function renderAccounts(data) {
  const container = $("accounts");
  container.innerHTML = "";

  if (!data.accounts.length) {
    container.textContent = "No accounts configured.";
    return;
  }

  for (const account of data.accounts) {
    const block = document.createElement("section");
    block.className = "account-block";

    const header = document.createElement("div");
    header.className = "account-header";
    header.innerHTML = `
      <h3>${escapeHtml(account.label)}</h3>
      <span class="account-meta">${escapeHtml(account.id)} · ${escapeHtml(account.kind)} · ${account.file_count} file(s)</span>
    `;
    block.appendChild(header);

    if (!account.files.length) {
      const empty = document.createElement("p");
      empty.className = "empty-account";
      empty.textContent = "No PDF or CSV files in this folder.";
      block.appendChild(empty);
    } else {
      const table = document.createElement("table");
      table.className = "file-table";
      table.innerHTML = `
        <thead>
          <tr>
            <th>File</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody></tbody>
      `;
      const tbody = table.querySelector("tbody");
      for (const file of account.files) {
        const tr = document.createElement("tr");
        const badgeClass =
          file.status === "processed" ? "badge-processed" : "badge-pending";
        const label = file.status === "processed" ? "Processed" : "Pending";
        tr.innerHTML = `
          <td title="${escapeHtml(file.path)}">${escapeHtml(file.name)}</td>
          <td><span class="badge ${badgeClass}">${label}</span></td>
        `;
        tbody.appendChild(tr);
      }
      block.appendChild(table);
    }

    container.appendChild(block);
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
    $("stat-db").textContent = data.db_path;

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
  } catch (e) {
    errEl.textContent = `Failed to load status: ${e.message}`;
    show(errEl);
  } finally {
    hide(loading);
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

  hide(errEl);
  hide(result);
  show(loading);
  btn.disabled = true;

  try {
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
  } catch (e) {
    errEl.textContent = `Analysis failed: ${e.message}`;
    show(errEl);
  } finally {
    hide(loading);
    btn.disabled = false;
  }
}

$("refresh-btn").addEventListener("click", loadStatus);
$("analyze-form").addEventListener("submit", submitQuestion);

loadStatus();
