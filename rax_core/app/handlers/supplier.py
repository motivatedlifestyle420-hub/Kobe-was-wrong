"""Supplier ordering handlers – six-stage automated ordering pipeline.

Bidfood / Bidvest integration notes
------------------------------------
Bidfood (UK/AU/ZA) does **not** publish a public self-serve REST API.
Integration options in priority order:

1. **Managed connector** (BIDFOOD_API_URL set)
   - Crossfire EDI-as-API  https://crossfireintegration.com/
   - Buy-Force-Live direct  https://www.tbfg.com.au/integration/bidfood/
   - Apicbase (NL)          https://get.apicbase.com/integrations/bidfood-nl/
   POST /orders with JSON; auth via X-Api-Key header.

2. **Email ordering** (default fallback)
   Plain-text or structured-email order sent to the depot address
   (e.g. orders@bidfood.co.uk).  Order confirmation arrives by reply email,
   polled via IMAP.

3. **EDI** (EDIFACT ORDERS / AS2 or X12 850)
   For large-volume partners – set up via Bidfood's supplier portal:
   https://www.bidfoodsuppliers.co.uk/

Pipeline stages
---------------
supplier.parse_invoice      – email/PDF → structured line items
supplier.detect_low_stock   – compute reorder list vs. threshold
supplier.build_order_draft  – convert needs → supplier SKU / order body
supplier.place_order        – send email or API order (idempotent via effect ledger)
supplier.confirm_order      – check reply / reconcile confirmation
supplier.notify             – SMS/email "Order placed" notification
"""
import email.mime.multipart
import email.mime.text
import imaplib
import json
import logging
import smtplib
import time
import urllib.request
from typing import Any

from rax_core.app import config, jobs
from rax_core.app.router import registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage 1 – parse_invoice
# ---------------------------------------------------------------------------

def _parse_invoice(job: dict) -> dict:
    """Parse an email / PDF invoice into structured line items.

    Expected payload keys (all optional – use what you have):
        raw_text   str  – plain-text body of the supplier invoice email
        pdf_path   str  – local path to a PDF invoice (future: OCR)
        source     str  – "email" | "pdf" | "manual"

    Returns a list of line items:
        [{"sku": "BF-12345", "description": "...", "qty": 10, "unit": "case",
          "unit_price": 4.50}, ...]
    """
    payload = job["payload"]
    raw_text: str = payload.get("raw_text", "")
    items: list[dict] = payload.get("items", [])

    if not items and raw_text:
        # Minimal line-by-line parser for plain-text invoices.
        # A real implementation would use a dedicated PDF/OCR library.
        for line in raw_text.splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 3:
                try:
                    items.append(
                        {
                            "sku": parts[0].strip(),
                            "description": parts[1].strip(),
                            "qty": float(parts[2].strip()),
                            "unit": parts[3].strip() if len(parts) > 3 else "unit",
                            "unit_price": float(parts[4].strip()) if len(parts) > 4 else 0.0,
                        }
                    )
                except (ValueError, IndexError):
                    continue

    logger.info(
        "parse_invoice job_id=%s  items_parsed=%d", job["id"], len(items)
    )
    return {"items": items, "source": payload.get("source", "unknown")}


# ---------------------------------------------------------------------------
# Stage 2 – detect_low_stock
# ---------------------------------------------------------------------------

def _detect_low_stock(job: dict) -> dict:
    """Compute which items need reordering.

    Expected payload keys:
        inventory  list[dict]  – [{"sku": ..., "on_hand": int, "reorder_qty": int}, ...]
        threshold  int         – override LOW_STOCK_THRESHOLD (optional)

    Returns:
        {"reorder_list": [{"sku": ..., "on_hand": int, "reorder_qty": int}, ...]}
    """
    payload = job["payload"]
    threshold = int(payload.get("threshold", config.LOW_STOCK_THRESHOLD))
    inventory: list[dict] = payload.get("inventory", [])

    reorder_list = [
        item
        for item in inventory
        if int(item.get("on_hand", 0)) <= threshold
    ]

    logger.info(
        "detect_low_stock job_id=%s  threshold=%d  items_below=%d",
        job["id"],
        threshold,
        len(reorder_list),
    )
    return {"reorder_list": reorder_list}


# ---------------------------------------------------------------------------
# Stage 3 – build_order_draft
# ---------------------------------------------------------------------------

def _build_order_draft(job: dict) -> dict:
    """Convert a reorder list into a supplier-formatted order body.

    Expected payload keys:
        reorder_list   list[dict]  – output of detect_low_stock
        supplier       str         – e.g. "bidfood"
        account_number str         – your customer account with the supplier

    Returns:
        {"order_lines": [...], "supplier": "bidfood", "account_number": "...",
         "order_ref": "..."}
    """
    payload = job["payload"]
    reorder_list: list[dict] = payload.get("reorder_list", [])
    supplier: str = payload.get("supplier", "bidfood")
    account_number: str = payload.get("account_number", "")

    order_lines = []
    for item in reorder_list:
        order_lines.append(
            {
                "sku": item.get("sku", ""),
                "qty": item.get("reorder_qty", 1),
                "unit": item.get("unit", "case"),
            }
        )

    order_ref = f"order:{supplier}:{time.strftime('%Y-%m-%d')}:{job['id'][:8]}"

    logger.info(
        "build_order_draft job_id=%s  supplier=%s  lines=%d  ref=%s",
        job["id"],
        supplier,
        len(order_lines),
        order_ref,
    )
    return {
        "order_lines": order_lines,
        "supplier": supplier,
        "account_number": account_number,
        "order_ref": order_ref,
    }


# ---------------------------------------------------------------------------
# Stage 4 – place_order  (idempotent via effect ledger)
# ---------------------------------------------------------------------------

def _send_order_email(draft: dict) -> str:
    """Send the order as a plain-text email to the Bidfood depot."""
    lines_text = "\n".join(
        f"  {i+1}. SKU {ln['sku']}  qty={ln['qty']}  unit={ln['unit']}"
        for i, ln in enumerate(draft.get("order_lines", []))
    )
    body = (
        f"Order Reference: {draft['order_ref']}\n"
        f"Account Number:  {draft.get('account_number', 'N/A')}\n\n"
        f"Order Lines:\n{lines_text}\n\n"
        f"Please confirm receipt of this order.\n"
    )
    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = config.SMTP_FROM
    msg["To"] = config.BIDFOOD_ORDER_EMAIL
    msg["Subject"] = f"Purchase Order – {draft['order_ref']}"
    msg.attach(email.mime.text.MIMEText(body, "plain"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        if config.SMTP_USER:
            smtp.starttls()
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
        smtp.sendmail(config.SMTP_FROM, config.BIDFOOD_ORDER_EMAIL, msg.as_string())

    return f"email_sent:{config.BIDFOOD_ORDER_EMAIL}"


def _send_order_api(draft: dict) -> str:
    """POST the order to the configured managed connector (Crossfire / BFL)."""
    body = json.dumps(draft).encode()
    req = urllib.request.Request(
        f"{config.BIDFOOD_API_URL.rstrip('/')}/orders",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": config.BIDFOOD_API_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        response_body = resp.read().decode()
    return f"api_placed:{response_body[:200]}"


def _place_order(job: dict) -> dict:
    """Place a Bidfood order (email or API), idempotent via effect ledger.

    Expected payload keys:
        order_ref      str        – unique reference (used as effect key)
        order_lines    list[dict]
        supplier       str
        account_number str

    The effect ledger prevents double-ordering even if the job is retried.
    """
    payload = job["payload"]
    order_ref: str = payload.get("order_ref", job["id"])
    effect_key = f"place_order:{order_ref}"

    # Layer 2 idempotency – if we already sent this order, return cached result.
    existing = jobs.check_effect(effect_key)
    if existing:
        logger.info(
            "place_order SKIPPED (already placed)  job_id=%s  ref=%s",
            job["id"],
            order_ref,
        )
        return json.loads(existing["result"]) if existing.get("result") else {}

    if config.BIDFOOD_API_URL:
        placement_result = _send_order_api(payload)
    else:
        placement_result = _send_order_email(payload)

    result = {"order_ref": order_ref, "placement": placement_result}
    jobs.record_effect(effect_key, job["id"], result)

    logger.info(
        "place_order SENT  job_id=%s  ref=%s  via=%s",
        job["id"],
        order_ref,
        "api" if config.BIDFOOD_API_URL else "email",
    )
    return result


# ---------------------------------------------------------------------------
# Stage 5 – confirm_order
# ---------------------------------------------------------------------------

def _confirm_order(job: dict) -> dict:
    """Check for a supplier confirmation reply.

    Polls IMAP inbox for a reply that matches order_ref.  If IMAP is not
    configured, marks as confirmed (manual / stub mode).

    Expected payload keys:
        order_ref  str
    """
    payload = job["payload"]
    order_ref: str = payload.get("order_ref", "")

    if not config.IMAP_HOST:
        logger.info(
            "confirm_order STUB (no IMAP configured)  job_id=%s  ref=%s",
            job["id"],
            order_ref,
        )
        return {"order_ref": order_ref, "confirmed": True, "method": "stub"}

    # Real IMAP search for a subject containing the order reference.
    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST) as imap:
            imap.login(config.IMAP_USER, config.IMAP_PASS)
            imap.select("INBOX")
            _, data = imap.search(None, f'SUBJECT "{order_ref}"')
            found = bool(data and data[0])
    except Exception as exc:
        raise RuntimeError(f"IMAP search failed: {exc}") from exc

    logger.info(
        "confirm_order  job_id=%s  ref=%s  found=%s",
        job["id"],
        order_ref,
        found,
    )
    return {"order_ref": order_ref, "confirmed": found, "method": "imap"}


# ---------------------------------------------------------------------------
# Stage 6 – notify
# ---------------------------------------------------------------------------

def _notify(job: dict) -> dict:
    """Send an internal notification that the order was placed.

    Expected payload keys:
        order_ref   str
        recipient   str   – email address
        channel     str   – "email" (default) | "log"
        message     str   – optional override
    """
    payload = job["payload"]
    order_ref: str = payload.get("order_ref", "")
    recipient: str = payload.get("recipient", config.SMTP_FROM)
    channel: str = payload.get("channel", "email")
    message: str = payload.get(
        "message",
        f"Your Bidfood order {order_ref} has been placed successfully.",
    )

    if channel == "email" and config.SMTP_HOST:
        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = config.SMTP_FROM
        msg["To"] = recipient
        msg["Subject"] = f"Order Placed – {order_ref}"
        msg.attach(email.mime.text.MIMEText(message, "plain"))
        try:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
                if config.SMTP_USER:
                    smtp.starttls()
                    smtp.login(config.SMTP_USER, config.SMTP_PASS)
                smtp.sendmail(config.SMTP_FROM, recipient, msg.as_string())
        except Exception as exc:
            logger.warning("notify email failed: %s – falling back to log", exc)
            channel = "log"

    logger.info("notify  job_id=%s  ref=%s  channel=%s  msg=%s",
                job["id"], order_ref, channel, message)
    return {"order_ref": order_ref, "channel": channel, "message": message}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register() -> None:
    """Register all supplier job-type handlers with the global registry."""
    registry.register("supplier.parse_invoice",    _parse_invoice)
    registry.register("supplier.detect_low_stock", _detect_low_stock)
    registry.register("supplier.build_order_draft", _build_order_draft)
    registry.register("supplier.place_order",      _place_order)
    registry.register("supplier.confirm_order",    _confirm_order)
    registry.register("supplier.notify",           _notify)
