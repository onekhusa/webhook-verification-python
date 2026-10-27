const form = document.querySelector("#payment-form");
const createButton = document.querySelector("#create-button");
const emptyState = document.querySelector("#empty-state");
const transactionView = document.querySelector("#transaction-view");
const activityList = document.querySelector("#activity-list");
const toast = document.querySelector("#toast");
let currentTransaction = null;
let clientConfig = null;
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.error;
    const error = new Error(detail?.message || `Request failed (${response.status})`);
    error.payload = detail;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("hidden"), 3400);
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function formatAmount(value) {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
}

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

function renderTransaction(transaction) {
  currentTransaction = transaction;
  emptyState.classList.add("hidden");
  transactionView.classList.remove("hidden");
  setText("transaction-reference", transaction.merchantReferenceNumber);
  setText("transaction-description", transaction.transactionDescription);
  setText("transaction-amount", `MWK ${formatAmount(transaction.transactionAmount)}`);
  setText("transaction-payer", `•••• ${transaction.payerAccountLastFour}`);
  setText(
    "transaction-id",
    transaction.providerTransactionReference || "Awaiting callback",
  );
  const badge = document.getElementById("transaction-status");
  badge.textContent = transaction.status;
  badge.className = `status ${transaction.status}`;
  const accepted =
    transaction.submissionHttpStatus >= 200 && transaction.submissionHttpStatus < 300;
  document.querySelector("#provider-waiting").classList.toggle(
    "hidden",
    !(accepted && transaction.status === "pending"),
  );
  document.querySelector("#provider-result").classList.toggle(
    "hidden",
    !transaction.submissionMessage,
  );
  if (transaction.submissionMessage) {
    setText(
      "provider-result",
      `${transaction.submissionMessage}${transaction.submissionHttpStatus ? ` (HTTP ${transaction.submissionHttpStatus})` : ""}`,
    );
  }
}

function renderActivity(transactions) {
  activityList.replaceChildren();
  if (!transactions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.style.padding = "28px 10px";
    const text = document.createElement("p");
    text.textContent = "No payment activity yet.";
    empty.append(text);
    activityList.append(empty);
    return;
  }

  transactions.forEach((transaction) => {
    const item = document.createElement("div");
    item.className = "activity-item";
    const marker = document.createElement("span");
    marker.className = `activity-marker ${transaction.status}`;
    marker.textContent = transaction.status === "succeeded" ? "✓" : transaction.status === "failed" ? "×" : transaction.status === "reversed" ? "↶" : "·";
    const detail = document.createElement("div");
    const name = document.createElement("p");
    name.className = "activity-name";
    name.textContent = transaction.merchantReferenceNumber;
    const meta = document.createElement("p");
    meta.className = "activity-meta";
    meta.textContent = `MWK ${formatAmount(transaction.transactionAmount)} · ${transaction.status}`;
    detail.append(name, meta);
    const time = document.createElement("time");
    time.className = "activity-time";
    time.dateTime = transaction.updatedAt;
    time.textContent = formatTime(transaction.updatedAt);
    item.append(marker, detail, time);
    item.addEventListener("click", () => renderTransaction(transaction));
    item.style.cursor = "pointer";
    activityList.append(item);
  });
}

async function refreshActivity() {
  const transactions = await api("/api/payments");
  renderActivity(transactions);
}

function applyConfiguration() {
  const available = Boolean(clientConfig?.onekhusaEnabled && clientConfig?.onekhusaSandbox);
  const notice = document.querySelector("#provider-notice");
  notice.classList.toggle("warning", !available);
  notice.textContent = available
    ? `Sandbox connection configured: ${clientConfig.onekhusaBaseUrl}. Submitting may send a test prompt to the payer phone.`
    : "OneKhusa sandbox is not enabled or credentials are incomplete. Configure ONEKHUSA_ENABLED and the ONEKHUSA_* credentials in the server .env.";
  createButton.disabled = !available;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!window.confirm(
    "Send a real request to the OneKhusa SANDBOX? The sandbox may send a test push prompt to the payer phone.",
  )) return;
  createButton.disabled = true;
  try {
    const formData = new FormData(form);
    const payload = {
      connectorId: Number(formData.get("connector")),
      payerAccountNumber: String(formData.get("payer")).trim(),
      transactionAmount: String(formData.get("amount")),
      transactionDescription: String(formData.get("description")).trim(),
      capturedBy: String(formData.get("capturedBy")).trim(),
      merchantReferenceNumber: String(formData.get("reference")).trim(),
    };
    const transaction = await api("/api/onekhusa/push-payments", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderTransaction(transaction);
    await refreshActivity();
    showToast("Request sent to OneKhusa sandbox. Waiting for its callback.");
  } catch (error) {
    if (error.payload?.payment) {
      renderTransaction(error.payload.payment);
      await refreshActivity();
    }
    showToast(error.message, true);
  } finally {
    createButton.disabled = !clientConfig?.onekhusaEnabled || !clientConfig?.onekhusaSandbox;
  }
});

document.querySelector("#clear-button").addEventListener("click", async () => {
  try {
    await api("/api/payments", { method: "DELETE" });
    currentTransaction = null;
    transactionView.classList.add("hidden");
    emptyState.classList.remove("hidden");
    await refreshActivity();
    showToast("The in-memory payment session was cleared.");
  } catch (error) {
    showToast(error.message, true);
  }
});

async function initialize() {
  clientConfig = await api("/api/config");
  applyConfiguration();
  await refreshActivity();
  window.setInterval(async () => {
    try {
      await refreshActivity();
      if (currentTransaction) {
        const latest = (await api("/api/payments")).find(
          (item) => item.paymentId === currentTransaction.paymentId,
        );
        if (latest && latest.updatedAt !== currentTransaction.updatedAt) {
          renderTransaction(latest);
        }
      }
    } catch (error) {
      showToast(error.message, true);
    }
  }, 5000);
}

initialize().catch((error) => showToast(error.message, true));
