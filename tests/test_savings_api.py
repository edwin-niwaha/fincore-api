from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.savings.models import SavingsAccount, SavingsPolicy, SavingsTransaction
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
        "first_name": "Jane",
        "last_name": "Doe",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


@pytest.mark.django_db
def test_cash_staff_can_crud_savings_accounts_and_fetch_transaction_history():
    institution = Institution.objects.create(name="Alpha SACCO", code="alpha")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@alpha.test",
        username="teller-alpha",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)

    api = APIClient()
    api.force_authenticate(user=teller)

    first_account = api.post(
        "/api/v1/savings/accounts/",
        {"client": str(client.id), "status": "active"},
        format="json",
    )
    assert first_account.status_code == 201
    first_account_id = first_account.data["id"]
    assert first_account.data["client_member_number"] == client.member_number
    assert first_account.data["account_number"].startswith(f"SAV-{client.member_number}-")
    assert first_account.data["account_number"].endswith("001")
    assert first_account.data["transaction_count"] == 0

    second_account = api.post(
        "/api/v1/savings/accounts/",
        {"client": str(client.id), "status": "active"},
        format="json",
    )
    assert second_account.status_code == 201
    second_account_id = second_account.data["id"]
    assert second_account.data["account_number"].endswith("002")

    update_response = api.patch(
        f"/api/v1/savings/accounts/{second_account_id}/",
        {"status": "inactive"},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["status"] == "inactive"

    delete_response = api.delete(f"/api/v1/savings/accounts/{second_account_id}/")
    assert delete_response.status_code == 204
    assert not SavingsAccount.objects.filter(pk=second_account_id).exists()

    deposit_response = api.post(
        f"/api/v1/savings/accounts/{first_account_id}/deposit/",
        {"amount": "150.00", "reference": "DEP-101", "notes": "Opening deposit"},
        format="json",
    )
    assert deposit_response.status_code == 201

    detail_response = api.get(f"/api/v1/savings/accounts/{first_account_id}/")
    assert detail_response.status_code == 200
    assert detail_response.data["transaction_count"] == 1
    assert len(detail_response.data["recent_transactions"]) == 1
    assert detail_response.data["recent_transactions"][0]["reference"] == "DEP-101"

    history_response = api.get(f"/api/v1/savings/accounts/{first_account_id}/transactions/")
    assert history_response.status_code == 200
    assert history_response.data["count"] == 1
    assert history_response.data["results"][0]["reference"] == "DEP-101"


@pytest.mark.django_db
def test_deposits_and_withdrawals_create_transactions_and_audit_logs():
    institution = Institution.objects.create(name="Ledger SACCO", code="ledger")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@ledger.test",
        username="teller-ledger",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    account = SavingsAccount.objects.create(client=client)

    api = APIClient()
    api.force_authenticate(user=teller)

    deposit_response = api.post(
        f"/api/v1/savings/accounts/{account.id}/deposit/",
        {"amount": "300.00", "reference": "DEP-300", "notes": "Cash received"},
        format="json",
    )
    assert deposit_response.status_code == 201

    withdrawal_response = api.post(
        f"/api/v1/savings/accounts/{account.id}/withdraw/",
        {"amount": "120.00", "reference": "WIT-120", "notes": "Client withdrawal"},
        format="json",
    )
    assert withdrawal_response.status_code == 201

    account.refresh_from_db()
    assert account.balance == Decimal("180.00")

    savings_rows = list(account.transactions.order_by("created_at"))
    assert [row.type for row in savings_rows] == ["deposit", "withdrawal"]

    cash_transactions = list(
        Transaction.objects.filter(client=client)
        .order_by("created_at")
        .values_list("category", flat=True)
    )
    assert cash_transactions == ["savings_deposit", "savings_withdrawal"]

    audit_actions = list(
        AuditLog.objects.filter(target=str(account.id))
        .order_by("created_at")
        .values_list("action", flat=True)
    )
    assert "savings.deposit" in audit_actions
    assert "savings.withdraw" in audit_actions


@pytest.mark.django_db
def test_account_transaction_history_supports_type_and_reference_filters():
    institution = Institution.objects.create(name="Filter SACCO", code="filter")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@filter.test",
        username="teller-filter",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    account = SavingsAccount.objects.create(client=client)

    SavingsService.deposit(
        account=account,
        amount=Decimal("200.00"),
        performed_by=teller,
        reference="FILTER-DEP-1",
        notes="First deposit",
    )
    SavingsService.withdraw(
        account=account,
        amount=Decimal("50.00"),
        performed_by=teller,
        reference="FILTER-WIT-1",
        notes="First withdrawal",
    )

    api = APIClient()
    api.force_authenticate(user=teller)

    deposit_history = api.get(
        f"/api/v1/savings/accounts/{account.id}/transactions/",
        {"type": "deposit"},
    )
    assert deposit_history.status_code == 200
    assert deposit_history.data["count"] == 1
    assert deposit_history.data["results"][0]["reference"] == "FILTER-DEP-1"
    assert deposit_history.data["results"][0]["status"] == "posted"

    search_history = api.get(
        f"/api/v1/savings/accounts/{account.id}/transactions/",
        {"search": "WIT-1"},
    )
    assert search_history.status_code == 200
    assert search_history.data["count"] == 1
    assert search_history.data["results"][0]["reference"] == "FILTER-WIT-1"


@pytest.mark.django_db
def test_withdrawal_prevents_negative_balances_and_preserves_existing_balance():
    institution = Institution.objects.create(name="Guard SACCO", code="guard")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@guard.test",
        username="teller-guard",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    account = SavingsAccount.objects.create(client=client, balance=Decimal("100.00"))

    api = APIClient()
    api.force_authenticate(user=teller)

    response = api.post(
        f"/api/v1/savings/accounts/{account.id}/withdraw/",
        {"amount": "150.00", "reference": "WIT-OVER"},
        format="json",
    )
    assert response.status_code == 400
    assert "insufficient savings balance" in response.data["message"].lower()

    account.refresh_from_db()
    assert account.balance == Decimal("100.00")
    assert SavingsTransaction.objects.filter(account=account).count() == 0
    assert Transaction.objects.filter(client=client).count() == 0


@pytest.mark.django_db
def test_account_creation_requires_active_client_and_non_closed_status():
    institution = Institution.objects.create(name="Validation SACCO", code="validation")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@validation.test",
        username="teller-validation",
        role="teller",
        institution=institution,
        branch=branch,
    )
    inactive_client = create_client(
        institution=institution,
        branch=branch,
        first_name="Inactive",
        last_name="Client",
        status="inactive",
    )
    active_client = create_client(
        institution=institution,
        branch=branch,
        first_name="Active",
        last_name="Client",
    )

    api = APIClient()
    api.force_authenticate(user=teller)

    inactive_response = api.post(
        "/api/v1/savings/accounts/",
        {"client": str(inactive_client.id), "status": "active"},
        format="json",
    )
    assert inactive_response.status_code == 400
    assert "Only active clients can open savings accounts." in inactive_response.data["errors"]["client"]

    closed_response = api.post(
        "/api/v1/savings/accounts/",
        {"client": str(active_client.id), "status": "closed"},
        format="json",
    )
    assert closed_response.status_code == 400
    assert "Savings accounts cannot be created in a closed status." in closed_response.data["errors"]["status"]


@pytest.mark.django_db
def test_inactive_accounts_reject_cash_operations():
    institution = Institution.objects.create(name="Dormant SACCO", code="dormant")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@dormant.test",
        username="teller-dormant",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    account = SavingsAccount.objects.create(
        client=client,
        status="inactive",
        balance=Decimal("100.00"),
    )

    api = APIClient()
    api.force_authenticate(user=teller)

    deposit_response = api.post(
        f"/api/v1/savings/accounts/{account.id}/deposit/",
        {"amount": "25.00", "reference": "DEP-INACTIVE"},
        format="json",
    )
    assert deposit_response.status_code == 400
    assert "only active savings accounts can process transactions" in deposit_response.data[
        "message"
    ].lower()

    withdrawal_response = api.post(
        f"/api/v1/savings/accounts/{account.id}/withdraw/",
        {"amount": "25.00", "reference": "WIT-INACTIVE"},
        format="json",
    )
    assert withdrawal_response.status_code == 400
    assert "only active savings accounts can process transactions" in withdrawal_response.data[
        "message"
    ].lower()

    account.refresh_from_db()
    assert account.balance == Decimal("100.00")
    assert SavingsTransaction.objects.filter(account=account).count() == 0


@pytest.mark.django_db
def test_permissions_and_scope_limit_savings_access_and_cash_operations():
    institution = Institution.objects.create(name="Scope SACCO", code="scope")
    branch_a = Branch.objects.create(institution=institution, name="Main", code="main")
    branch_b = Branch.objects.create(institution=institution, name="North", code="north")
    teller_a = create_user(
        email="teller-a@scope.test",
        username="teller-a",
        role="teller",
        institution=institution,
        branch=branch_a,
    )
    client_user = create_user(
        email="client@scope.test",
        username="scope-client",
        role="client",
        institution=institution,
        branch=branch_a,
    )
    own_client = create_client(institution=institution, branch=branch_a, user=client_user)
    other_client = create_client(
        institution=institution,
        branch=branch_b,
        first_name="Other",
        last_name="Member",
    )
    own_account = SavingsAccount.objects.create(client=own_client)
    other_account = SavingsAccount.objects.create(client=other_client)

    staff_api = APIClient()
    staff_api.force_authenticate(user=teller_a)

    blocked_create = staff_api.post(
        "/api/v1/savings/accounts/",
        {"client": str(other_client.id), "status": "active"},
        format="json",
    )
    assert blocked_create.status_code == 403

    hidden_detail = staff_api.get(f"/api/v1/savings/accounts/{other_account.id}/")
    assert hidden_detail.status_code == 404

    hidden_deposit = staff_api.post(
        f"/api/v1/savings/accounts/{other_account.id}/deposit/",
        {"amount": "10.00", "reference": "DEP-HIDDEN"},
        format="json",
    )
    assert hidden_deposit.status_code == 404

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)

    list_response = client_api.get("/api/v1/savings/accounts/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == str(own_account.id)

    blocked_client_deposit = client_api.post(
        f"/api/v1/savings/accounts/{own_account.id}/deposit/",
        {"amount": "25.00", "reference": "DEP-CLIENT"},
        format="json",
    )
    assert blocked_client_deposit.status_code == 403


@pytest.mark.django_db
def test_savings_policy_updates_are_admin_only_and_institution_scoped():
    institution_a = Institution.objects.create(name="Alpha Policy SACCO", code="alpha-policy")
    institution_b = Institution.objects.create(name="Beta Policy SACCO", code="beta-policy")
    branch_a = Branch.objects.create(institution=institution_a, name="Main", code="main")
    branch_b = Branch.objects.create(institution=institution_b, name="Main", code="beta")
    institution_admin_a = create_user(
        email="admin@alpha-policy.test",
        username="alpha-policy-admin",
        role="institution_admin",
        institution=institution_a,
    )
    teller_a = create_user(
        email="teller@alpha-policy.test",
        username="alpha-policy-teller",
        role="teller",
        institution=institution_a,
        branch=branch_a,
    )
    teller_b = create_user(
        email="teller@beta-policy.test",
        username="beta-policy-teller",
        role="teller",
        institution=institution_b,
        branch=branch_b,
    )
    client_a = create_client(institution=institution_a, branch=branch_a)
    client_b = create_client(institution=institution_b, branch=branch_b)
    account_a = SavingsAccount.objects.create(client=client_a)
    account_b = SavingsAccount.objects.create(client=client_b)

    admin_api = APIClient()
    admin_api.force_authenticate(user=institution_admin_a)
    teller_a_api = APIClient()
    teller_a_api.force_authenticate(user=teller_a)
    teller_b_api = APIClient()
    teller_b_api.force_authenticate(user=teller_b)

    default_policy_response = teller_a_api.get("/api/v1/savings/accounts/policy/")
    assert default_policy_response.status_code == 200
    assert default_policy_response.data["institution"] == str(institution_a.id)
    assert default_policy_response.data["minimum_balance"] == "0.00"
    assert default_policy_response.data["withdrawal_charge"] == "0.00"

    blocked_policy_update = teller_a_api.patch(
        "/api/v1/savings/accounts/policy/",
        {"minimum_balance": "50.00", "withdrawal_charge": "10.00"},
        format="json",
    )
    assert blocked_policy_update.status_code == 403

    policy_update = admin_api.patch(
        "/api/v1/savings/accounts/policy/",
        {"minimum_balance": "50.00", "withdrawal_charge": "10.00"},
        format="json",
    )
    assert policy_update.status_code == 200
    assert policy_update.data["institution"] == str(institution_a.id)
    assert policy_update.data["minimum_balance"] == "50.00"
    assert policy_update.data["withdrawal_charge"] == "10.00"

    institution_a_policy = SavingsPolicy.current(institution_a)
    institution_b_policy = SavingsPolicy.current(institution_b)
    assert institution_a_policy.minimum_balance == Decimal("50.00")
    assert institution_a_policy.withdrawal_charge == Decimal("10.00")
    assert institution_b_policy.minimum_balance == Decimal("0.00")
    assert institution_b_policy.withdrawal_charge == Decimal("0.00")

    teller_a_api.post(
        f"/api/v1/savings/accounts/{account_a.id}/deposit/",
        {"amount": "100.00", "reference": "POL-DEP-A"},
        format="json",
    )
    teller_b_api.post(
        f"/api/v1/savings/accounts/{account_b.id}/deposit/",
        {"amount": "100.00", "reference": "POL-DEP-B"},
        format="json",
    )

    blocked_withdrawal = teller_a_api.post(
        f"/api/v1/savings/accounts/{account_a.id}/withdraw/",
        {"amount": "45.00", "reference": "POL-WIT-A"},
        format="json",
    )
    assert blocked_withdrawal.status_code == 400
    assert "minimum balance of 50.00" in blocked_withdrawal.data["message"].lower()

    successful_withdrawal = teller_b_api.post(
        f"/api/v1/savings/accounts/{account_b.id}/withdraw/",
        {"amount": "45.00", "reference": "POL-WIT-B"},
        format="json",
    )
    assert successful_withdrawal.status_code == 201


@pytest.mark.django_db
def test_duplicate_references_return_400_and_keep_balance_unchanged():
    institution = Institution.objects.create(name="Dup SACCO", code="dup")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@dup.test",
        username="teller-dup",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    account = SavingsAccount.objects.create(client=client)
    Transaction.objects.create(
        institution=institution,
        branch=branch,
        client=client,
        category="manual_adjustment",
        direction="credit",
        amount=Decimal("10.00"),
        reference="SHARED-001",
        description="Existing reference",
        created_by=teller,
    )

    api = APIClient()
    api.force_authenticate(user=teller)

    duplicate_response = api.post(
        f"/api/v1/savings/accounts/{account.id}/deposit/",
        {"amount": "50.00", "reference": "SHARED-001"},
        format="json",
    )
    assert duplicate_response.status_code == 400
    assert "reference" in duplicate_response.data["errors"]

    account.refresh_from_db()
    assert account.balance == Decimal("0.00")
    assert SavingsTransaction.objects.filter(account=account).count() == 0
    assert AuditLog.objects.filter(action="savings.deposit", target=str(account.id)).count() == 0
