# webhook-verification-python

A teaching reference that splits a copyable OneKhusa integration kit from a FastAPI demo application. It initiates push payments through the OneKhusa Collections sandbox and verifies signed callbacks with the raw request body before parsing.

All payment state lives in memory. This is not production-ready.

## Quick start

1. Install Python 3.11+ and uv
2. uv sync --extra dev
3. Copy .env.example to .env
4. Fill in OneKhusa sandbox credentials and set ONEKHUSA_ENABLED=true
5. Configure ONEKHUSA_WEBHOOK_SECRETS for the events you subscribe to
6. uv run uvicorn webhook_verification.main:app --reload --app-dir src
7. Open http://127.0.0.1:8000

## Architecture

- src/webhook_verification/onekhusa/ - Copyable integration kit (self-contained)
- src/webhook_verification/payments/ - Domain and use cases (framework/provider agnostic)
- src/webhook_verification/web/ - HTTP layer, adapters, composition root

## Webhook security

POST /webhook/pushpayment verifies HMAC-SHA512 over raw body before parsing. Correlation prefers merchant reference; falls back to provider reference. Duplicates are deduplicated by event+identity. Unmatched callbacks are not cached.

## Testing

uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src tests
uv build
