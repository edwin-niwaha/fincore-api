from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounting.models import JournalEntry, LedgerAccount
from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanProduct
from apps.loans.services import LoanService
from apps.savings.models import SavingsAccount
from apps.savings.services import SavingsService


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


def create_client(*, institution, branch, **overrides):
    payload = {
        "institution": institution,
        "branch": branch,
        "first_name": "Jane",
        "last_name": "Doe",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


def account_by_code(institution, code):
    return LedgerAccount.objects.get(institution=institution, code=code)


def as_amount(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


@pytest.mark.django_db
def test_chart_of_accounts_bootstraps_defaults_and_supports_manual_accounts():
    institution = Institution.objects.create(name="Alpha SACCO", code="alpha")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    user = create_user(
        email="accountant@example.com",
        username="accountant",
        role="accountant",
        institution=institution,
        branch=branch,
    )
    api = APIClient()
    api.force_authenticate(user=user)

    list_response = api.get("/api/v1/accounting/accounts/")
    assert list_response.status_code == 200
    codes = {row["code"] for row in list_response.data["results"]}
    assert {"1000", "1300", "2000", "4000"}.issubset(codes)

    create_response = api.post(
        "/api/v1/accounting/accounts/",
        {
            "institution": str(institution.id),
            "code": "5100",
            "name": "Office Supplies",
            "type": "expense",
            "description": "Stationery and branch consumables",
            "is_active": True,
            "allow_manual_entries": True,
        },
        format="json",
    )
    assert create_response.status_code == 201
    assert create_response.data["code"] == "5100"
    assert create_response.data["normal_balance"] == "debit"
    assert create_response.data["is_system"] is False


@pytest.mark.django_db
def test_journal_entries_cannot_post_when_unbalanced():
    institution = Institution.objects.create(name="Journal SACCO", code="journal")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    user = create_user(
        email="accountant2@example.com",
        username="accountant2",
        role="accountant",
        institution=institution,
        branch=branch,
    )
    cash = account_by_code(institution, "1000")
    savings_control = account_by_code(institution, "2000")
    api = APIClient()
    api.force_authenticate(user=user)

    create_response = api.post(
        "/api/v1/accounting/journal-entries/",
        {
            "institution": str(institution.id),
            "branch": str(branch.id),
            "reference": "MAN-001",
            "description": "Draft mismatch entry",
            "entry_date": "2026-04-29",
            "status": "draft",
            "lines": [
                {"account": str(cash.id), "debit": "100.00", "credit": "0.00"},
                {
                    "account": str(savings_control.id),
                    "debit": "0.00",
                    "credit": "90.00",
                },
            ],
        },
        format="json",
    )
    assert create_response.status_code == 201
    entry_id = create_response.data["id"]
    assert create_response.data["status"] == "draft"
    assert create_response.data["is_balanced"] is False

    post_response = api.post(f"/api/v1/accounting/journal-entries/{entry_id}/post/")
    assert post_response.status_code == 400
    assert "cannot be posted" in post_response.data["message"].lower()

    update_response = api.patch(
        f"/api/v1/accounting/journal-entries/{entry_id}/",
        {
            "lines": [
                {"account": str(cash.id), "debit": "100.00", "credit": "0.00"},
                {
                    "account": str(savings_control.id),
                    "debit": "0.00",
                    "credit": "100.00",
                },
            ]
        },
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["is_balanced"] is True

    successful_post = api.post(f"/api/v1/accounting/journal-entries/{entry_id}/post/")
    assert successful_post.status_code == 200
    assert successful_post.data["status"] == "posted"
    assert successful_post.data["posted_at"] is not None

    delete_response = api.delete(f"/api/v1/accounting/journal-entries/{entry_id}/")
    assert delete_response.status_code == 403


@pytest.mark.django_db
def test_operational_flows_generate_expected_double_entry_journals():
    institution = Institution.objects.create(name="Ops SACCO", code="ops")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@example.com",
        username="teller",
        role="teller",
        institution=institution,
        branch=branch,
    )
    officer = create_user(
        email="officer@example.com",
        username="officer",
        role="loan_officer",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    savings_account = SavingsAccount.objects.create(client=client)
    product = LoanProduct.objects.create(
        institution=institution,
        name="Small Loan",
        code="small",
        min_amount=100,
        max_amount=5000,
        annual_interest_rate=12,
        min_term_months=1,
        max_term_months=24,
    )
    loan = LoanApplication.objects.create(
        client=client,
        product=product,
        amount=Decimal("600.00"),
        term_months=6,
    )

    SavingsService.deposit(
        account=savings_account,
        amount=Decimal("300.00"),
        performed_by=teller,
        reference="DEP-100",
    )
    SavingsService.withdraw(
        account=savings_account,
        amount=Decimal("50.00"),
        performed_by=teller,
        reference="WIT-100",
    )
    LoanService.approve(loan=loan, user=officer)
    LoanService.disburse(loan=loan, user=officer, reference="DISB-100")
    repayment = LoanService.repay(
        loan=loan,
        amount=Decimal("100.00"),
        reference="REP-100",
        received_by=teller,
    )

    entries = {
        entry.source: entry
        for entry in JournalEntry.objects.filter(institution=institution).prefetch_related(
            "lines__account"
        )
    }

    assert set(entries) == {
        JournalEntry.Source.SAVINGS_DEPOSIT,
        JournalEntry.Source.SAVINGS_WITHDRAWAL,
        JournalEntry.Source.LOAN_DISBURSEMENT,
        JournalEntry.Source.LOAN_REPAYMENT,
    }

    for entry in entries.values():
        debit = sum((line.debit for line in entry.lines.all()), Decimal("0.00"))
        credit = sum((line.credit for line in entry.lines.all()), Decimal("0.00"))
        assert entry.status == JournalEntry.Status.POSTED
        assert debit == credit
        assert debit > 0

    deposit_lines = {
        line.account.code: line
        for line in entries[JournalEntry.Source.SAVINGS_DEPOSIT].lines.all()
    }
    assert deposit_lines["1000"].debit == Decimal("300.00")
    assert deposit_lines["2000"].credit == Decimal("300.00")

    withdrawal_lines = {
        line.account.code: line
        for line in entries[JournalEntry.Source.SAVINGS_WITHDRAWAL].lines.all()
    }
    assert withdrawal_lines["2000"].debit == Decimal("50.00")
    assert withdrawal_lines["1000"].credit == Decimal("50.00")

    disbursement_lines = {
        line.account.code: line
        for line in entries[JournalEntry.Source.LOAN_DISBURSEMENT].lines.all()
    }
    assert disbursement_lines["1300"].debit == Decimal("600.00")
    assert disbursement_lines["1000"].credit == Decimal("600.00")

    repayment_lines = {
        line.account.code: line for line in entries[JournalEntry.Source.LOAN_REPAYMENT].lines.all()
    }
    assert repayment.amount == Decimal("100.00")
    assert repayment_lines["1000"].debit == Decimal("100.00")
    assert repayment_lines["1300"].credit == Decimal("64.00")
    assert repayment_lines["4000"].credit == Decimal("36.00")


@pytest.mark.django_db
def test_trial_balance_endpoint_returns_balanced_totals_and_rows():
    institution = Institution.objects.create(name="Reports SACCO", code="reports")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    accountant = create_user(
        email="accountant3@example.com",
        username="accountant3",
        role="accountant",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    savings_account = SavingsAccount.objects.create(client=client)
    SavingsService.deposit(
        account=savings_account,
        amount=Decimal("250.00"),
        performed_by=accountant,
        reference="DEP-250",
    )

    api = APIClient()
    api.force_authenticate(user=accountant)
    response = api.get(
        f"/api/v1/reports/trial-balance/?institution={institution.id}&branch={branch.id}&as_of=2026-04-29"
    )

    assert response.status_code == 200
    totals = response.data["totals"]
    assert as_amount(totals["debit"]) == Decimal("250.00")
    assert as_amount(totals["credit"]) == Decimal("250.00")
    assert as_amount(totals["difference"]) == Decimal("0.00")

    rows = {row["code"]: row for row in response.data["rows"]}
    assert as_amount(rows["1000"]["total_debit"]) == Decimal("250.00")
    assert as_amount(rows["2000"]["total_credit"]) == Decimal("250.00")
