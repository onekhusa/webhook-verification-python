# webhook-verification-python

A standalone FastAPI push-payment test bench with a browser UI. Use local-only simulations or opt in to actual OneKhusa sandbox token and push-initiation calls. All transaction state is held in memory; the project has no database.

## What it does

- Runs a local UI at `/` for creating simulated or sandbox mobile-money push payments.
- Supports `pushpayment.success`, `pushpayment.failed`, and `pushpayment.reversed` lifecycle callbacks.
- Signs simulator callbacks with a randomly generated, process-local HMAC-SHA512 key and verifies them through the normal webhook verification path.
- Exposes a real incoming callback endpoint at `POST /webhook/pushpayment`, verified with event-specific OneKhusa webhook secrets.
- Keeps transaction state and callback de-duplication only in process memory. No database or transaction file writes are used. State is cleared when the service restarts and is capped at 100 recent transactions.
- Masks payer information to its last four characters in simulator results.

The local simulator never contacts OneKhusa. Sandbox mode calls its access-token and Collections push-initiation endpoints and may send a test prompt to the entered phone. The integration rejects non-sandbox URLs. Simulator routes are disabled in production.

## Setup and run

Python 3.11 or newer and `uv` are recommended.

```powershell
Set-Location 'C:\path\to\webhook-verification-python'
uv sync --extra dev
Copy-Item .env.example .env
uv run uvicorn webhook_verification.main:app --reload --app-dir src
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Local simulation requires `SIMULATION_ENABLED=true`. To enable OneKhusa sandbox calls, configure `ONEKHUSA_ENABLED=true` and the credentials below. The UI requires a merchant reference and asks for confirmation before sending.

## Simulator workflow

1. Enter a sample payer number, amount, connector, description, and optional merchant reference.
2. Create the simulated payment. The new transaction appears in `pending` state.
3. Trigger the success or failure callback. After a success, you can simulate a reversal.
4. Inspect recent in-memory activity or clear the current session with **Clear session**.

The UI displays the payer number only as its last four characters. The server generates a demo signing secret at startup; it is never exposed to the browser or written to disk.

## API

- `GET /` — local simulator UI. Disabled in production.
- `GET /api/simulations` — recent in-memory simulated transactions.
- `POST /api/simulations` — create a local simulation using the existing push request shape:

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

- `POST /api/simulations/{simulation_id}/events` — simulate one of the three supported push callback events:

```json
{ "event": "pushpayment.success" }
```

- `DELETE /api/simulations` — clear all current process-memory simulations.
- `GET /api/config` — safe feature flags and configured base URL; credentials are not exposed.
- `POST /api/onekhusa/push-payments` — obtain/cache a token and initiate a push payment through the configured OneKhusa sandbox. Requires `ONEKHUSA_ENABLED=true`, all credentials, and `sourceReferenceNumber`. A sandbox call may send a test handset prompt.
- `POST /webhook/pushpayment` — accept real OneKhusa callback payloads. This route verifies the original raw body using HMAC-SHA512 and the matching event-specific secret before changing in-memory transaction status.
- `GET /api/health` — liveness check.

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

The access-token request sends `apiKey`, `apiSecret`, `organisationId`, and `merchantAccountNumber`. Tokens are cached in memory until 30 seconds before expiry. Push requests use bearer authentication, `Accept-Language: en`, and `X-Idempotency-Key`; repeat submissions with the same reference and identical request reuse the same transaction and provider idempotency key. A provider timeout is reported as an unknown outcome and must not be retried with a new reference. Do not commit real secrets or `.env`.

## Transaction lifecycle

- `pending` may transition to `succeeded` or `failed`.
- `succeeded` may transition to `reversed`.
- Terminal or unsupported transitions are rejected.
- Duplicate callback events are ignored within the in-memory receipt window.

Webhook transaction state also exists only in memory. This project is a development test bench, not a production payment service: restarts lose transactions and callbacks cannot be reconciled after state is lost.

## Tests and quality

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Tests use an in-process ASGI client, mocked OneKhusa HTTP transport, and deterministic signatures; they do not call OneKhusa or require credentials.

## Scope

This project only covers Collections push payments and their callbacks. It does not contain Request to Pay, hosted checkout, live payment initiation, provider status inquiry, or any database/persistence layer. The provider client permits only sandbox URLs.
