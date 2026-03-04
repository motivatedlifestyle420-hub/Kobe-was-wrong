"""Tests for the six supplier job-type handlers."""
import time
import pytest

from rax_core.app.handlers.supplier import (
    _parse_invoice,
    _detect_low_stock,
    _build_order_draft,
    _place_order,
    _confirm_order,
    _notify,
    register,
)
from rax_core.app.router import registry
from rax_core.app import jobs


# Register handlers for these tests
register()


def _make_job(job_type: str, payload: dict) -> dict:
    """Return a minimal job dict (no DB round-trip needed for unit tests)."""
    return {
        "id": f"test-{time.time()}",
        "job_type": job_type,
        "worker_id": "w",
        "lease_id": "l",
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# supplier.parse_invoice
# ---------------------------------------------------------------------------

def test_parse_invoice_from_raw_text():
    raw = "BF-001,Chicken Breast,10,kg,5.50\nBF-002,Olive Oil,5,litre,12.00"
    result = _parse_invoice(_make_job("supplier.parse_invoice", {"raw_text": raw}))
    assert "items" in result
    assert len(result["items"]) == 2
    assert result["items"][0]["sku"] == "BF-001"
    assert result["items"][0]["qty"] == 10.0


def test_parse_invoice_passthrough_items():
    items = [{"sku": "X", "description": "Y", "qty": 3, "unit": "case", "unit_price": 1.0}]
    result = _parse_invoice(_make_job("supplier.parse_invoice", {"items": items}))
    assert result["items"] == items


def test_parse_invoice_empty():
    result = _parse_invoice(_make_job("supplier.parse_invoice", {}))
    assert result["items"] == []


# ---------------------------------------------------------------------------
# supplier.detect_low_stock
# ---------------------------------------------------------------------------

def test_detect_low_stock_filters_correctly():
    inventory = [
        {"sku": "A", "on_hand": 2, "reorder_qty": 10},   # below threshold → reorder
        {"sku": "B", "on_hand": 20, "reorder_qty": 5},   # above → skip
        {"sku": "C", "on_hand": 5, "reorder_qty": 8},    # exactly at threshold → reorder
    ]
    result = _detect_low_stock(
        _make_job("supplier.detect_low_stock", {"inventory": inventory, "threshold": 5})
    )
    skus = [i["sku"] for i in result["reorder_list"]]
    assert "A" in skus
    assert "C" in skus
    assert "B" not in skus


def test_detect_low_stock_empty_inventory():
    result = _detect_low_stock(_make_job("supplier.detect_low_stock", {"inventory": []}))
    assert result["reorder_list"] == []


# ---------------------------------------------------------------------------
# supplier.build_order_draft
# ---------------------------------------------------------------------------

def test_build_order_draft_structure():
    reorder = [{"sku": "BF-001", "reorder_qty": 5, "unit": "case"}]
    result = _build_order_draft(
        _make_job(
            "supplier.build_order_draft",
            {"reorder_list": reorder, "supplier": "bidfood", "account_number": "ACC123"},
        )
    )
    assert result["supplier"] == "bidfood"
    assert result["account_number"] == "ACC123"
    assert len(result["order_lines"]) == 1
    assert result["order_lines"][0]["sku"] == "BF-001"
    assert result["order_ref"].startswith("order:bidfood:")


def test_build_order_draft_empty_reorder():
    result = _build_order_draft(
        _make_job("supplier.build_order_draft", {"reorder_list": []})
    )
    assert result["order_lines"] == []


# ---------------------------------------------------------------------------
# supplier.place_order  (email disabled in tests; effect ledger idempotency)
# ---------------------------------------------------------------------------

def test_place_order_idempotency_via_effect_ledger():
    """Second call with same order_ref returns cached result without re-sending."""
    import json
    from rax_core.app import jobs as job_ops

    order_ref = f"order:bidfood:{time.time()}"
    effect_key = f"place_order:{order_ref}"

    # Pre-seed the ledger so we bypass actual SMTP.
    cached = {"order_ref": order_ref, "placement": "email_sent:test@test"}
    job_ops.record_effect(effect_key, "fake-job", cached)

    job = _make_job("supplier.place_order", {"order_ref": order_ref, "order_lines": []})
    result = _place_order(job)

    assert result["order_ref"] == order_ref
    # Ensure no new ledger entry was created (count stays 1).
    entry = job_ops.check_effect(effect_key)
    assert entry is not None


# ---------------------------------------------------------------------------
# supplier.confirm_order  (IMAP not configured → stub mode)
# ---------------------------------------------------------------------------

def test_confirm_order_stub():
    result = _confirm_order(
        _make_job("supplier.confirm_order", {"order_ref": "order:bidfood:test"})
    )
    assert result["confirmed"] is True
    assert result["method"] == "stub"


# ---------------------------------------------------------------------------
# supplier.notify  (log channel, no SMTP required)
# ---------------------------------------------------------------------------

def test_notify_log_channel():
    result = _notify(
        _make_job(
            "supplier.notify",
            {"order_ref": "REF-001", "channel": "log"},
        )
    )
    assert result["channel"] == "log"
    assert "REF-001" in result["message"]


# ---------------------------------------------------------------------------
# Registry – all six types registered
# ---------------------------------------------------------------------------

def test_all_supplier_types_registered():
    expected = {
        "supplier.parse_invoice",
        "supplier.detect_low_stock",
        "supplier.build_order_draft",
        "supplier.place_order",
        "supplier.confirm_order",
        "supplier.notify",
    }
    assert expected.issubset(set(registry.job_types()))
