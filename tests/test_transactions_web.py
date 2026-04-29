import pytest
from django.test import Client as DjangoClient
from django.urls import reverse

from apps.transactions.models import Transaction
from tests.test_transactions_api import build_transaction_fixture


@pytest.mark.django_db
def test_transactions_web_renders_export_ready_table_and_scope_safe_rows():
    fixture = build_transaction_fixture()

    browser = DjangoClient()
    browser.force_login(fixture["institution_admin"])

    response = browser.get(reverse("transactions_web:ledger"))
    assert response.status_code == 200
    assert b"Transaction ledger with export-ready detail" in response.content
    assert b"Print / PDF ready" in response.content
    assert b"TX-SAV-DEP-1" in response.content
    assert b"TX-SAV-DEP-3" not in response.content


@pytest.mark.django_db
def test_transactions_web_filters_and_detail_drawer_work():
    fixture = build_transaction_fixture()
    selected_transaction = Transaction.objects.get(reference="TX-LOAN-REP-1")

    browser = DjangoClient()
    browser.force_login(fixture["institution_admin"])

    response = browser.get(
        reverse("transactions_web:ledger"),
        {
            "category": "loan_repayment",
            "direction": "credit",
            "date_from": "2026-04-13",
            "date_to": "2026-04-13",
            "selected": str(selected_transaction.id),
        },
    )
    assert response.status_code == 200
    assert b"Detail Drawer" in response.content
    assert b"TX-LOAN-REP-1" in response.content
    assert b"Loan repayment for MAIN-000001" in response.content
    assert b"TX-SAV-DEP-2" not in response.content
