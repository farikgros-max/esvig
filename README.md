# esvig

Telegram bot for channel catalog and order processing.

## Environment
Set these variables before running:

- `BOT_TOKEN` (optional; falls back to legacy built-in token if omitted)
- `ADMIN_IDS` (optional, comma-separated Telegram user IDs; if omitted, built-in legacy admin list is used)
- `CRYPTO_BOT_TOKEN` (optional)
- `XROCKET_API_KEY` (optional)
- `PAID_BTN_URL` (optional)
- `WEBHOOK_URL` (optional)
- `DATABASE_URL` (required by `database.py`)

## Quick check
```bash
python -m py_compile app.py database.py
```
