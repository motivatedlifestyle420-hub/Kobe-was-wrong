"""Configuration – reads environment variables at import time."""
import os

# Database
DB_PATH: str = os.environ.get(
    "RAX_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "rax_core.db"),
)

# HTTP API authentication
API_KEY: str = os.environ.get("RAX_API_KEY", "dev-secret")

# Worker settings
WORKER_POLL_INTERVAL: float = float(os.environ.get("RAX_POLL_INTERVAL", "2"))
WORKER_HEARTBEAT_INTERVAL: float = float(
    os.environ.get("RAX_HEARTBEAT_INTERVAL", "10")
)
WORKER_LEASE_SECONDS: float = float(os.environ.get("RAX_LEASE_SECONDS", "30"))

# Supplier / Bidfood integration
#
# Bidfood does not publish a public REST API.  Orders are placed by email
# (to orders@bidfood.co.uk or the regional depot address) or, for approved
# partners, via EDI (EDIFACT/AS2) or the Buy-Force-Live / Crossfire managed
# connector.  The settings below cover all three approaches; only the ones
# that are populated will be used.

# --- email-based ordering (fallback / default) ---
SMTP_HOST: str = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "25"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASS: str = os.environ.get("SMTP_PASS", "")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "orders@yourbusiness.com")

BIDFOOD_ORDER_EMAIL: str = os.environ.get(
    "BIDFOOD_ORDER_EMAIL", "orders@bidfood.co.uk"
)

# --- EDI / managed-connector (optional) ---
# Set BIDFOOD_API_URL to the base URL of your Crossfire / Buy-Force-Live
# connector.  If blank, the email fallback is used instead.
BIDFOOD_API_URL: str = os.environ.get("BIDFOOD_API_URL", "")
BIDFOOD_API_KEY: str = os.environ.get("BIDFOOD_API_KEY", "")

# --- IMAP inbox polling (for confirm_order) ---
IMAP_HOST: str = os.environ.get("IMAP_HOST", "")
IMAP_USER: str = os.environ.get("IMAP_USER", "")
IMAP_PASS: str = os.environ.get("IMAP_PASS", "")

# Low-stock threshold (units on hand ≤ this triggers a reorder)
LOW_STOCK_THRESHOLD: int = int(os.environ.get("LOW_STOCK_THRESHOLD", "5"))
