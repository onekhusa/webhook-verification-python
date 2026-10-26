# webhook-verification-python

A standalone FastAPI push-payment test bench with a browser dashboard. It initiates push payments through the OneKhusa sandbox and verifies the signed callbacks OneKhusa sends back. All payment state is held in memory; the project has no database.

## Shared walkthrough

1. Install Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
2. From this directory, install the project and dev tools: `uv sync --extra dev`.
3. Copy the example environment file: `Copy-Item .env.example .env`.
4. Fill in the OneKhusa sandbox credentials and set `ONEKHUSA_ENABLED=true`.
5. Configure `ONEKHUSA_WEBHOOK_SECRETS` with the secret for every push event you subscribe to.
6. Start the app: `uv run uvicorn webhook_verification.main:app --reload --app-dir src`.
7. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).
8. Submit a push payment. It starts in `pending` and appears under **Recent payments**.
9. OneKhusa posts a signed callback to `POST /webhook/pushpayment`; the status moves to `succeeded`, `failed`, or later `reversed`.
10. Inspect the lifecycle in the dashboard and clear the in-memory session with **Clear session** when you are done.

A sandbox submission is a real request to OneKhusa and may send a test payment prompt to the payer's phone. Do not submit real customer data.

## What it does

- Runs a local dashboard at `/` for submitting OneKhusa sandbox push payments and watching their lifecycle.
- Calls the OneKhusa access-token and Collections push-initiation endpoints; only sandbox base URLs are accepted.
- Supports `pushpayment.success`, `pushpayment.failed`, and `pushpayment.reversed` lifecycle callbacks.
- Exposes a real incoming callback endpoint at `POST /webhook/pushpayment`, verified with event-specific OneKhusa webhook secrets.
- Reconciles a callback that arrives before the initiation response has stored the provider transaction reference.
- Keeps payment state and callback de-duplication only in process memory. No database or transaction file writes are used. State is cleared when the service restarts and is capped at 100 recent payments.
- Masks payer information to its last four characters.
- Serves browser assets only from the whitelisted paths `/assets/app.css`, `/assets/app.js`, and `/assets/logo.svg`.

The dashboard is hidden in production (`APP_ENV=production` returns `404`). The push-payment API requires `ONEKHUSA_ENABLED=true` and complete credentials; otherwise it returns `503`.

## Project layout

```text
src/webhook_verification/
  main.py                 FastAPI composition root
  container.py            dependency container shared by feature routers
  onekhusa/               provider adapter
    client/               token, connector validation, push initiation, HTTP setup
    webhook/              events, payload schema, HMAC-SHA512 signing
  features/
    initiate_push_payment/ OneKhusa sandbox submission and idempotency
    receive_webhook/       signature check, matching, transitions, de-duplication
    payments/              payment listing and session clearing
    configuration/         settings and client configuration
  shared/payments/        payment model, state machine, in-memory store
  ui/                     Jinja2 layout and dashboard, app.css, app.js, logo.svg
fixtures/                 shared payloads and HMAC-SHA512 signature vectors
tests/                    mirrors onekhusa/ and features/, reads fixtures/
```

Tests and helpers mirror the source tree. Shared payloads and signature vectors live in `fixtures/` so the same vectors can be used by equivalent implementations in other languages:

- `initiate-push-payment.json` — push-payment request body.
- `pushpayment.{success,failed,reversed}.json` — canonical callback bodies.
- `webhook-signature-vectors.json` — HMAC-SHA512 lowercase-hex digests over the exact bytes of each fixture body. The `secret` value is for tests only; do not use it in an environment. Tampered and malformed vectors must fail verification.

## Workflow

1. Enter a sample payer number, amount, connector, description, captured-by value, and merchant reference.
2. Submit the request. It is sent to the OneKhusa sandbox and recorded in `pending` state.
3. Wait for OneKhusa to post `pushpayment.success` or `pushpayment.failed` to `/webhook/pushpayment`.
4. A later `pushpayment.reversed` callback moves a successful payment to `reversed`.
5. Inspect recent in-memory activity or clear the current session with **Clear session**.

The UI displays the payer number only as its last four characters. Each callback is verified against the raw request body before any status changes. Browser assets are served only from the whitelisted paths listed above.

## API

- `GET /` — dashboard UI. Disabled in production.
- `GET /api/payments` — recent in-memory payments.
- `DELETE /api/payments` — clear all current process-memory payments.
- `GET /api/config` — safe client configuration: `onekhusaEnabled`, `onekhusaSandbox`, and the sandbox `onekhusaBaseUrl`; credentials are never exposed.
- `POST /api/onekhusa/push-payments` — obtain/cache a token and initiate a push payment through the configured OneKhusa sandbox. Requires `ONEKHUSA_ENABLED=true`, all credentials, and `sourceReferenceNumber`. Returns `202` with the pending payment, `409` when the source reference is reused with a different request, `422` when the reference is missing, `502` when the provider rejects or times out, and `503` when OneKhusa is not configured.
- `POST /webhook/pushpayment` — accept real OneKhusa callback payloads. This route verifies the original raw body using HMAC-SHA512 and the matching event-specific secret before changing in-memory payment status.
- `GET /api/health` — liveness check.

Example request:

```json
{
  "connectorId": 892353,
  "payerAccountNumber": "2659912345678",
  "transactionAmount": "12500.00",
  "transactionDescription": "Invoice INV-1042",
  "capturedBy": "demo-merchant",
  "sourceReferenceNumber": "ORDER-1042"
}
```

A successful response is a payment record whose `paymentId` is the local record identifier and whose `transactionReferenceNumber` is the provider reference. Before the initiation response is stored, the record uses a `PENDING-TXN-` placeholder that a matching callback can reconcile.

The incoming webhook expects `X-OneKhusa-Webhook-Event` and `X-OneKhusa-Webhook-Signature`. Configure the appropriate secret for every push event you subscribe to:

```dotenv
ONEKHUSA_WEBHOOK_SECRETS={"pushpayment.success":"replace-me","pushpayment.failed":"replace-me","pushpayment.reversed":"replace-me"}
```

The webhook secrets are only for authenticating incoming callbacks. Configure access-token credentials separately:

```dotenv
ONEKHUSA_ENABLED=true
ONEKHUSA_BASE_URL=https://api.onekhusa.com/sandbox/v1
ONEKHUSA_API_KEY=your-sandbox-api-key
ONEKHUSA_API_SECRET=your-45-character-sandbox-secret
ONEKHUSA_ORGANISATION_ID=your-organisation-id
ONEKHUSA_MERCHANT_ACCOUNT_NUMBER=12345678
ONEKHUSA_CONNECT_TIMEOUT_SECONDS=5
ONEKHUSA_READ_TIMEOUT_SECONDS=20
```

The access-token request sends `apiKey`, `apiSecret`, `organisationId`, and `merchantAccountNumber`. Tokens are cached in memory until 30 seconds before expiry. Push requests use bearer authentication, `Accept-Language: en`, and `X-Idempotency-Key`; repeat submissions with the same reference and identical request reuse the same payment and provider idempotency key. A provider timeout is reported as an unknown outcome and must not be retried with a new reference. Provider error bodies are not echoed to clients. Do not commit real secrets or `.env`.

## Transaction lifecycle

- `pending` may transition to `succeeded` or `failed`.
- `succeeded` may transition to `reversed`.
- Terminal or unsupported transitions are rejected with `409`.
- Duplicate callback events are ignored within the in-memory receipt window.
- Callbacks that match no stored payment are acknowledged without changing state.

Payment state exists only in memory. This project is a development test bench, not a production payment service: restarts lose payments and callbacks cannot be reconciled after state is lost.

## Tests and quality

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

Tests use an in-process ASGI client, mocked OneKhusa HTTP transport, and the signature vectors in `fixtures/`; they do not call OneKhusa or require credentials. Settings used by tests disable `.env` loading and default to a sandbox configuration so results are reproducible.

## Scope

This project only covers Collections push payments and their callbacks. It does not contain Request to Pay, hosted checkout, live payment initiation, provider status inquiry, or any database/persistence layer. The provider client permits only sandbox URLs.
