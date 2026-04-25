# esvig

Telegram bot for channel catalog and order processing.

## Environment
Set these variables before running:

- `BOT_TOKEN` (optional; legacy default token is used if omitted)
- `ADMIN_IDS` (optional, comma-separated Telegram user IDs; legacy defaults are used if omitted)
- `CRYPTO_BOT_TOKEN` (optional)
- `XROCKET_API_KEY` (optional)
- `PAID_BTN_URL` (optional)
- `WEBHOOK_URL` (optional)
- `DATABASE_URL` (required by `database.py`)

## Quick check
```bash
python -m py_compile app.py database.py
```
