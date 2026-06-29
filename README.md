# Invoice Automation

Automatically processes invoice emails from two Microsoft 365 mailboxes using Microsoft Graph API, extracts invoice data with LLM assistance, validates against breakdown files, and writes results into a master Excel register.

---

## Architecture

```
main.py
└── LangGraph Workflow
    ├── fetch_emails       (both mailboxes in parallel via asyncio)
    ├── download_attachments
    ├── classify_documents  (LLM: GPT-4o-mini)
    ├── extract_invoice     (LLM: GPT-4o + PDF native/OCR)
    ├── extract_breakdown   (pandas: Excel/CSV)
    ├── match_files         (invoice ↔ breakdown matching)
    ├── validate            (total comparison with tolerance)
    ├── write_excel         (invoice_register.xlsx)
    └── move_emails         (→ "Processed Invoices" folder, mark read)
```

---

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) package manager
- Two Azure AD App Registrations (one per mailbox)
- OpenAI API key

---

## Azure App Registration Setup

Each mailbox requires its own App Registration in the respective Azure AD tenant.

### Steps (repeat for both mailboxes)

1. Sign in to [portal.azure.com](https://portal.azure.com) with the tenant's admin account.

2. Navigate to **Azure Active Directory → App registrations → New registration**.

3. Give it a name (e.g. `Invoice Automation - Org1`), choose **Accounts in this organizational directory only**, and register.

4. Note the **Application (client) ID** and **Directory (tenant) ID** — these are your `CLIENT_ID` and `TENANT_ID`.

5. Go to **Certificates & secrets → New client secret**. Copy the value immediately — this is your `CLIENT_SECRET`.

6. Go to **API permissions → Add a permission → Microsoft Graph → Application permissions**. Add:
   - `Mail.Read`
   - `Mail.ReadWrite`
   - `Mail.Send` *(optional)*

7. Click **Grant admin consent** for your organisation.

8. For **Mailbox 1 (shared mailbox)**: set `MAILBOX1_USER` to the shared mailbox email address (e.g. `invoices@yourcompany.com`). The app must have `Mail.Read` / `Mail.ReadWrite` access to that mailbox — grant this via Exchange admin if needed.

9. For **Mailbox 2 (separate tenant)**: repeat all steps within that tenant's Azure portal. Set `MAILBOX2_USER` to the target user's UPN.

---

## Installation

```bash
# Install uv
pip install uv

# Clone / enter project directory
cd "Invoice Automation"

# Install all dependencies
uv sync

# Optional: install dev dependencies for tests
uv sync --extra dev
```

---

## Configuration

```bash
cp .env.example .env
```

Edit `.env` and fill in all values:

```env
MAILBOX1_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MAILBOX1_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MAILBOX1_CLIENT_SECRET=your-secret-here
MAILBOX1_USER=invoices@yourcompany.com

MAILBOX2_TENANT_ID=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
MAILBOX2_CLIENT_ID=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
MAILBOX2_CLIENT_SECRET=your-secret-here
MAILBOX2_USER=finance@othercompany.com

OPENAI_API_KEY=sk-...

PROCESSED_FOLDER_NAME=Processed Invoices
```

---

## Running

```bash
uv run python main.py
```

The system will:
1. Fetch today's unread emails from both mailboxes
2. Download and classify all attachments
3. Extract invoice data and breakdown line items
4. Validate totals
5. Write results to `app/output/invoice_register.xlsx`
6. Move processed emails to the `Processed Invoices` folder

---

## Output

### `app/output/invoice_register.xlsx`

**Sheet: Invoice Register**

| Column | Description |
|---|---|
| Processing Date | UTC timestamp of when the email was processed |
| Mailbox Source | `mailbox1` or `mailbox2` |
| Email Subject | Original email subject line |
| Sender | Sender email address |
| Invoice Number | Extracted from PDF |
| Invoice Date | Extracted date (YYYY-MM-DD) |
| Vendor | Vendor name |
| GST Number | Vendor GST/VAT number |
| Currency | ISO 4217 currency code |
| Subtotal | Pre-tax subtotal |
| Tax | Tax amount |
| Total | Invoice total |
| Breakdown Total | Sum of breakdown line items |
| Variance | `abs(Total - Breakdown Total)` |
| Status | `VALIDATED` / `REVIEW_REQUIRED` / `NO_BREAKDOWN` / `ERROR` |
| Attachment Names | Comma-separated list of all attachment filenames |
| Message ID | Microsoft Graph message ID |

**Sheet: Audit Log** — timestamped action log for every step.

---

## Logs

Daily rotating logs written to `app/logs/app.log`. Retained for 30 days, compressed.

---

## Running Tests

```bash
uv run pytest tests/ -v
```

---

## Project Structure

```
Invoice Automation/
├── app/
│   ├── config/
│   │   ├── settings.py         # Pydantic settings (env-driven)
│   │   └── logging.py          # Loguru configuration
│   ├── graph/
│   │   ├── auth.py             # Azure credential + Graph client factory
│   │   └── mail_client.py      # Per-mailbox Graph operations
│   ├── models/
│   │   ├── email_models.py
│   │   ├── document_models.py
│   │   ├── invoice_models.py
│   │   └── processing_models.py
│   ├── services/
│   │   ├── attachment_downloader.py
│   │   ├── classifier.py       # LLM document classification
│   │   ├── pdf_extractor.py    # Native PDF + OCR fallback
│   │   ├── invoice_extractor.py # LLM invoice data extraction
│   │   ├── breakdown_extractor.py # Excel/CSV line item extraction
│   │   ├── matcher.py          # Invoice ↔ breakdown matching
│   │   ├── validator.py        # Total validation
│   │   └── excel_writer.py     # Master register writer
│   ├── workflows/
│   │   ├── state.py            # Typed LangGraph state
│   │   ├── nodes.py            # Graph node implementations
│   │   └── graph.py            # Graph builder
│   ├── storage/                # Downloaded attachments (gitignored)
│   ├── output/                 # invoice_register.xlsx
│   └── logs/                   # Rotating log files
├── tests/
│   ├── test_matcher.py
│   ├── test_validator.py
│   ├── test_excel_writer.py
│   ├── test_classifier.py
│   ├── test_auth.py
│   └── test_breakdown_extractor.py
├── main.py
├── pyproject.toml
└── .env.example
```

---

## Security Notes

- All secrets are loaded from `.env` via `pydantic-settings` — never hardcoded.
- `SecretStr` wraps sensitive values to prevent accidental logging.
- Add `.env` and `app/storage/` to `.gitignore`.

---

## Adding a Third Mailbox

1. Add `MAILBOX3_*` variables to `.env.example` and `Settings`.
2. Add a third `MailboxClient` to `_build_clients()` in `app/workflows/nodes.py`.
3. No other changes required.
