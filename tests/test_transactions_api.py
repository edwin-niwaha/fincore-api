from datetime import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanProduct
from apps.loans.services import LoanService
from apps.savings.models import SavingsAccount
from apps.savings.services import SavingsService
from apps.transactions.models import Transaction


def create_user(
    *,
    email,
    username,
    role,
    institution=None,
    branch=None,
    password="Password123!",
):
    return get_user_model().objects.create_user(
        email=email,
        username=username,
        password=password,
        role=role,
        institution=institution,
        branch=branch,
    )


def create_client(*, institution, branch, user=None, **overrides):
    payload = {
        "user": user,
        "institution": institution,
        "branch": branch,
        "first_name": "Grace",
        "last_name": "Ledger",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


def stamp_transaction(reference, year, month, day, hour=10):
    stamped_at = timezone.make_aware(datetime(year, month, day, hour, 0, 0))
    Transaction.objects.filter(reference=reference).update(
        created_at=stamped_at,
        updated_at=stamped_at,
    )


def build_transaction_fixture():
    institution_a = Institution.objects.create(name="Alpha SACCO", code="alpha-tx")
    institution_b = Institution.objects.create(name="Beta SACCO", code="beta-tx")
    branch_a1 = Branch.objects.create(institution=institution_a, name="Main", code="main")
    branch_a2 = Branch.objects.create(institution=institution_a, name="North", code="north")
    branch_b1 = Branch.objects.create(institution=institution_b, name="South", code="south")

    super_admin = create_user(
        email="super@tx.test",
        username="tx-super",
        role="super_admin",
    )
    institution_admin = create_user(
        email="admin@tx.test",
        username="tx-admin",
        role="institution_admin",
        institution=institution_a,
    )
    teller_a1 = create_user(
        email="teller-a1@tx.test",
        username="tx-teller-a1",
        role="teller",
        institution=institution_a,
        branch=branch_a1,
    )
    teller_b1 = create_user(
        email="teller-b1@tx.test",
        username="tx-teller-b1",
        role="teller",
        institution=institution_b,
        branch=branch_b1,
    )
    officer_a1 = create_user(
        email="officer-a1@tx.test",
        username="tx-officer-a1",
        role="loan_officer",
        institution=institution_a,
        branch=branch_a1,
    )
    manager_a1 = create_user(
        email="manager-a1@tx.test",
        username="tx-manager-a1",
        role="branch_manager",
        institution=institution_a,
        branch=branch_a1,
    )
    client_user = create_user(
        email="client@tx.test",
        username="tx-client",
        role="client",
        institution=institution_a,
        branch=branch_a1,
    )

    client_a1 = create_client(
        institution=institution_a,
        branch=branch_a1,
        user=client_user,
        first_name="Amina",
        last_name="Okuya",
    )
    client_a2 = create_client(
        institution=institution_a,
        branch=branch_a2,
        first_name="Brian",
        last_name="Branch",
    )
    client_b1 = create_client(
        institution=institution_b,
        branch=branch_b1,
        first_name="Clara",
        last_name="External",
    )

    savings_a1 = SavingsAccount.objects.create(client=client_a1)
    savings_a2 = SavingsAccount.objects.create(client=client_a2)
    savings_b1 = SavingsAccount.objects.create(client=client_b1)

    SavingsService.deposit(
        account=savings_a1,
        amount=Decimal("300.00"),
        performed_by=teller_a1,
        reference="TX-SAV-DEP-1",
        notes="Cash in",
    )
    SavingsService.withdraw(
        account=savings_a1,
        amount=Decimal("80.00"),
        performed_by=teller_a1,
        reference="TX-SAV-WIT-1",
        notes="Cash out",
    )

    product_a = LoanProduct.objects.create(
        institution=institution_a,
        name="Business Loan",
        code="business-loan",
        min_amount=Decimal("100.00"),
        max_amount=Decimal("5000.00"),
        annual_interest_rate=Decimal("12.00"),
        min_term_months=3,
        max_term_months=24,
    )
    loan_a1 = LoanApplication.objects.create(
        client=client_a1,
        product=product_a,
        amount=Decimal("600.00"),
        term_months=6,
        purpose="Inventory",
    )
    LoanService.initialize_new_application(loan=loan_a1, created_by=officer_a1, submit=True)
    LoanService.recommend(loan=loan_a1, user=officer_a1)
    LoanService.approve(loan=loan_a1, user=manager_a1)
    LoanService.disburse(loan=loan_a1, user=teller_a1, reference="TX-LOAN-DISB-1")
    LoanService.repay(
        loan=loan_a1,
        amount=Decimal("100.00"),
        reference="TX-LOAN-REP-1",
        received_by=teller_a1,
    )

    SavingsService.deposit(
        account=savings_a2,
        amount=Decimal("150.00"),
        performed_by=teller_a1,
        reference="TX-SAV-DEP-2",
        notes="North branch cash in",
    )
    SavingsService.deposit(
        account=savings_b1,
        amount=Decimal("200.00"),
        performed_by=teller_b1,
        reference="TX-SAV-DEP-3",
        notes="External cash in",
    )

    stamp_transaction("TX-SAV-DEP-1", 2026, 4, 10)
    stamp_transaction("TX-SAV-WIT-1", 2026, 4, 11)
    stamp_transaction("TX-LOAN-DISB-1", 2026, 4, 12)
    stamp_transaction("TX-LOAN-REP-1", 2026, 4, 13)
    stamp_transaction("TX-SAV-DEP-2", 2026, 4, 14)
    stamp_transaction("TX-SAV-DEP-3", 2026, 4, 15)

    return {
        "super_admin": super_admin,
        "institution_admin": institution_admin,
        "teller_a1": teller_a1,
        "client_user": client_user,
        "branch_a1": branch_a1,
        "branch_a2": branch_a2,
        "institution_a": institution_a,
        "client_a1": client_a1,
        "client_a2": client_a2,
        "client_b1": client_b1,
    }


@pytest.mark.django_db
def test_transactions_ledger_is_read_only_and_scoped_by_user():
    fixture = build_transaction_fixture()

    super_api = APIClient()
    super_api.force_authenticate(user=fixture["super_admin"])
    all_rows = super_api.get("/api/v1/transactions/")
    assert all_rows.status_code == 200
    assert all_rows.data["count"] == 6
    assert super_api.post(
        "/api/v1/transactions/",
        {
            "category": "manual_adjustment",
            "direction": "credit",
            "amount": "10.00",
            "reference": "BLOCKED-TXN",
        },
        format="json",
    ).status_code == 405

    institution_api = APIClient()
    institution_api.force_authenticate(user=fixture["institution_admin"])
    institution_rows = institution_api.get("/api/v1/transactions/")
    assert institution_rows.status_code == 200
    assert institution_rows.data["count"] == 5
    assert {
        row["branch_name"] for row in institution_rows.data["results"]
    } == {"Main", "North"}

    branch_api = APIClient()
    branch_api.force_authenticate(user=fixture["teller_a1"])
    branch_rows = branch_api.get("/api/v1/transactions/")
    assert branch_rows.status_code == 200
    assert branch_rows.data["count"] == 4
    assert all(
        str(row["branch"]) == str(fixture["branch_a1"].id)
        for row in branch_rows.data["results"]
    )

    client_api = APIClient()
    client_api.force_authenticate(user=fixture["client_user"])
    client_rows = client_api.get("/api/v1/transactions/")
    assert client_rows.status_code == 200
    assert client_rows.data["count"] == 4
    assert {
        str(row["client"]) for row in client_rows.data["results"]
    } == {str(fixture["client_a1"].id)}


@pytest.mark.django_db
def test_transactions_support_scope_safe_filters_and_consistent_savings_loan_categories():
    fixture = build_transaction_fixture()

    api = APIClient()
    api.force_authenticate(user=fixture["institution_admin"])

    filtered = api.get(
        "/api/v1/transactions/"
        f"?client={fixture['client_a1'].id}"
        "&category=savings_deposit"
        "&direction=credit"
        "&date_from=2026-04-10"
        "&date_to=2026-04-10"
    )
    assert filtered.status_code == 200
    assert filtered.data["count"] == 1
    row = filtered.data["results"][0]
    assert row["reference"] == "TX-SAV-DEP-1"
    assert row["category"] == "savings_deposit"
    assert row["direction"] == "credit"
    assert row["client_name"] == "Amina Okuya"
    assert row["description"] == "Savings deposit to SAV-MAIN-000001-001"

    date_range = api.get("/api/v1/transactions/?date_from=2026-04-12&date_to=2026-04-14")
    assert date_range.status_code == 200
    assert date_range.data["count"] == 3
    assert [row["reference"] for row in date_range.data["results"]] == [
        "TX-SAV-DEP-2",
        "TX-LOAN-REP-1",
        "TX-LOAN-DISB-1",
    ]

    branch_filter = api.get(f"/api/v1/transactions/?branch={fixture['branch_a2'].id}")
    assert branch_filter.status_code == 200
    assert branch_filter.data["count"] == 1
    assert branch_filter.data["results"][0]["reference"] == "TX-SAV-DEP-2"

    ledger_rows = Transaction.objects.filter(client=fixture["client_a1"]).order_by("created_at")
    assert list(ledger_rows.values_list("category", flat=True)) == [
        "savings_deposit",
        "savings_withdrawal",
        "loan_disbursement",
        "loan_repayment",
    ]
    assert list(ledger_rows.values_list("direction", flat=True)) == [
        "credit",
        "debit",
        "debit",
        "credit",
    ]
    assert all(row.description for row in ledger_rows)
