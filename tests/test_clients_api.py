from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.clients.models import Client, ClientMemberSequence
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanProduct
from apps.savings.models import SavingsAccount, SavingsTransaction
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


@pytest.mark.django_db
def test_super_admin_can_crud_clients_with_filters_search_and_ordering():
    institution = Institution.objects.create(name="Alpha SACCO", code="alpha")
    main_branch = Branch.objects.create(
        institution=institution,
        name="Main Branch",
        code="main",
    )
    north_branch = Branch.objects.create(
        institution=institution,
        name="North Branch",
        code="north",
    )
    user = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    api = APIClient()
    api.force_authenticate(user=user)

    create_response = api.post(
        "/api/v1/clients/",
        {
            "institution": str(institution.id),
            "branch": str(main_branch.id),
            "first_name": "Jane",
            "last_name": "Ayo",
            "phone": "0700000001",
            "email": "JANE@EXAMPLE.COM",
            "status": "active",
        },
        format="json",
    )
    assert create_response.status_code == 201
    first_client_id = create_response.data["id"]
    assert create_response.data["member_number"] == "MAIN-000001"
    assert create_response.data["full_name"] == "Jane Ayo"
    assert create_response.data["institution_name"] == "Alpha SACCO"
    assert create_response.data["branch_name"] == "Main Branch"
    assert create_response.data["email"] == "jane@example.com"

    second_response = api.post(
        "/api/v1/clients/",
        {
            "institution": str(institution.id),
            "branch": str(main_branch.id),
            "first_name": "John",
            "last_name": "Zulu",
            "phone": "0700000002",
            "status": "inactive",
        },
        format="json",
    )
    assert second_response.status_code == 201
    assert second_response.data["member_number"] == "MAIN-000002"

    third_response = api.post(
        "/api/v1/clients/",
        {
            "institution": str(institution.id),
            "branch": str(north_branch.id),
            "first_name": "Martha",
            "last_name": "Bena",
            "phone": "0700000003",
            "status": "active",
        },
        format="json",
    )
    assert third_response.status_code == 201
    assert third_response.data["member_number"] == "NORT-000001"

    filtered_response = api.get(
        f"/api/v1/clients/?branch={main_branch.id}&status=active&search=jane&ordering=member_number"
    )
    assert filtered_response.status_code == 200
    assert filtered_response.data["count"] == 1
    assert filtered_response.data["results"][0]["id"] == first_client_id

    ordered_response = api.get(
        f"/api/v1/clients/?branch={main_branch.id}&ordering=-member_number"
    )
    assert ordered_response.status_code == 200
    assert ordered_response.data["results"][0]["member_number"] == "MAIN-000002"

    update_response = api.patch(
        f"/api/v1/clients/{first_client_id}/",
        {
            "phone": "0709999999",
            "status": "inactive",
        },
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["phone"] == "0709999999"
    assert update_response.data["status"] == "inactive"

    delete_response = api.delete(f"/api/v1/clients/{first_client_id}/")
    assert delete_response.status_code == 204
    assert not Client.objects.filter(pk=first_client_id).exists()


@pytest.mark.django_db
def test_staff_scope_blocks_client_changes_outside_allowed_institution_or_branch():
    own_institution = Institution.objects.create(name="Own SACCO", code="own")
    other_institution = Institution.objects.create(name="Other SACCO", code="other")
    own_branch = Branch.objects.create(
        institution=own_institution,
        name="Main Branch",
        code="main",
    )
    sister_branch = Branch.objects.create(
        institution=own_institution,
        name="Sister Branch",
        code="sister",
    )
    other_branch = Branch.objects.create(
        institution=other_institution,
        name="Other Branch",
        code="other-branch",
    )
    institution_admin = create_user(
        email="admin@own.test",
        username="inst-admin",
        role="institution_admin",
        institution=own_institution,
    )
    branch_manager = create_user(
        email="manager@own.test",
        username="branch-manager",
        role="branch_manager",
        institution=own_institution,
        branch=own_branch,
    )

    admin_api = APIClient()
    admin_api.force_authenticate(user=institution_admin)
    blocked_institution_response = admin_api.post(
        "/api/v1/clients/",
        {
            "institution": str(other_institution.id),
            "branch": str(other_branch.id),
            "first_name": "Blocked",
            "last_name": "Institution",
            "phone": "0700000010",
            "status": "active",
        },
        format="json",
    )
    assert blocked_institution_response.status_code == 403

    scoped_client = create_client(
        institution=own_institution,
        branch=own_branch,
        first_name="Own",
        last_name="Client",
    )
    hidden_client = create_client(
        institution=other_institution,
        branch=other_branch,
        first_name="Other",
        last_name="Client",
    )

    list_response = admin_api.get("/api/v1/clients/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == str(scoped_client.id)

    hidden_response = admin_api.get(f"/api/v1/clients/{hidden_client.id}/")
    assert hidden_response.status_code == 404

    branch_api = APIClient()
    branch_api.force_authenticate(user=branch_manager)
    blocked_branch_response = branch_api.post(
        "/api/v1/clients/",
        {
            "institution": str(own_institution.id),
            "branch": str(sister_branch.id),
            "first_name": "Blocked",
            "last_name": "Branch",
            "phone": "0700000011",
            "status": "active",
        },
        format="json",
    )
    assert blocked_branch_response.status_code == 403


@pytest.mark.django_db
def test_client_access_is_scoped_to_self_and_me_returns_financial_summary():
    institution = Institution.objects.create(name="Detail SACCO", code="detail")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    client_user = create_user(
        email="client@example.com",
        username="client-user",
        role="client",
        institution=institution,
        branch=branch,
    )
    other_user = create_user(
        email="other@example.com",
        username="other-user",
        role="client",
        institution=institution,
        branch=branch,
    )

    client = create_client(
        institution=institution,
        branch=branch,
        user=client_user,
        first_name="Amina",
        last_name="Nabirye",
        phone="0700001000",
    )
    other_client = create_client(
        institution=institution,
        branch=branch,
        user=other_user,
        first_name="Other",
        last_name="Person",
        phone="0700001001",
    )

    savings_account = SavingsAccount.objects.create(
        client=client,
        balance=Decimal("1200.00"),
    )
    SavingsTransaction.objects.create(
        account=savings_account,
        type="deposit",
        amount=Decimal("1200.00"),
        balance_after=Decimal("1200.00"),
        reference="SAV-1",
    )
    product = LoanProduct.objects.create(
        institution=institution,
        name="Business Loan",
        code="business",
        min_amount=100,
        max_amount=5000,
        annual_interest_rate=12,
        min_term_months=1,
        max_term_months=24,
    )
    LoanApplication.objects.create(
        client=client,
        product=product,
        amount=Decimal("1500.00"),
        term_months=12,
        status=LoanApplication.Status.DISBURSED,
        principal_balance=Decimal("700.00"),
        interest_balance=Decimal("50.00"),
    )
    Transaction.objects.create(
        institution=institution,
        branch=branch,
        client=client,
        category="savings_deposit",
        direction="credit",
        amount=Decimal("500.00"),
        reference="TX-1",
        description="Savings deposit",
    )
    Transaction.objects.create(
        institution=institution,
        branch=branch,
        client=client,
        category="loan_fee",
        direction="debit",
        amount=Decimal("200.00"),
        reference="TX-2",
        description="Loan processing fee",
    )

    api = APIClient()
    api.force_authenticate(user=client_user)

    list_response = api.get("/api/v1/clients/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == str(client.id)

    detail_response = api.get(f"/api/v1/clients/{client.id}/")
    assert detail_response.status_code == 200
    assert detail_response.data["savings_summary"]["account_count"] == 1
    assert detail_response.data["savings_summary"]["total_balance"] == "1200.00"
    assert detail_response.data["loans_summary"]["application_count"] == 1
    assert (
        detail_response.data["loans_summary"]["outstanding_principal_balance"]
        == "700.00"
    )
    assert detail_response.data["transactions_summary"]["net_flow"] == "300.00"
    assert len(detail_response.data["recent_savings_transactions"]) == 1
    assert len(detail_response.data["recent_loans"]) == 1
    assert len(detail_response.data["recent_transactions"]) == 2

    me_response = api.get("/api/v1/clients/me/")
    assert me_response.status_code == 200
    assert me_response.data["id"] == str(client.id)
    assert me_response.data["member_number"] == client.member_number

    me_update_response = api.patch(
        "/api/v1/clients/me/",
        {
            "phone": "0709991111",
            "address": "Kampala",
            "occupation": "Trader",
        },
        format="json",
    )
    assert me_update_response.status_code == 200
    client.refresh_from_db()
    assert client.phone == "0709991111"
    assert client.address == "Kampala"
    assert client.occupation == "Trader"

    hidden_response = api.get(f"/api/v1/clients/{other_client.id}/")
    assert hidden_response.status_code == 404

    blocked_create_response = api.post(
        "/api/v1/clients/",
        {
            "institution": str(institution.id),
            "branch": str(branch.id),
            "first_name": "Blocked",
            "last_name": "Create",
            "phone": "0700001111",
            "status": "active",
        },
        format="json",
    )
    assert blocked_create_response.status_code == 403

    blocked_update_response = api.patch(
        f"/api/v1/clients/{client.id}/",
        {"phone": "0700002222"},
        format="json",
    )
    assert blocked_update_response.status_code == 403


@pytest.mark.django_db
def test_member_number_sequence_is_branch_specific_and_monotonic():
    institution = Institution.objects.create(name="Sequence SACCO", code="sequence")
    main_branch = Branch.objects.create(
        institution=institution,
        name="Main Branch",
        code="main",
    )
    east_branch = Branch.objects.create(
        institution=institution,
        name="East Branch",
        code="east",
    )

    first_client = create_client(
        institution=institution,
        branch=main_branch,
        first_name="First",
        last_name="Main",
    )
    second_client = create_client(
        institution=institution,
        branch=main_branch,
        first_name="Second",
        last_name="Main",
    )
    east_client = create_client(
        institution=institution,
        branch=east_branch,
        first_name="East",
        last_name="Client",
    )

    assert first_client.member_number == "MAIN-000001"
    assert second_client.member_number == "MAIN-000002"
    assert east_client.member_number == "EAST-000001"
    assert ClientMemberSequence.objects.get(branch=main_branch).last_value == 2
    assert ClientMemberSequence.objects.get(branch=east_branch).last_value == 1
