from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanProduct
from apps.loans.services import LoanService
from apps.notifications.models import Notification
from apps.savings.models import SavingsAccount, SavingsTransaction
from apps.savings.services import SavingsService

User = get_user_model()


def create_user(
    *,
    email,
    username,
    role,
    institution=None,
    branch=None,
    password="Password123!",
):
    return User.objects.create_user(
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
        "first_name": "Client",
        "last_name": "Member",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


def auth_client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def build_self_service_fixture():
    institution = Institution.objects.create(name="Portal SACCO", code="portal")
    branch_main = Branch.objects.create(institution=institution, name="Main", code="main")
    branch_north = Branch.objects.create(institution=institution, name="North", code="north")

    client_user = create_user(
        email="client@portal.test",
        username="portal-client",
        role="client",
        institution=institution,
        branch=branch_main,
    )
    other_client_user = create_user(
        email="other@portal.test",
        username="portal-other-client",
        role="client",
        institution=institution,
        branch=branch_north,
    )
    teller = create_user(
        email="teller@portal.test",
        username="portal-teller",
        role="teller",
        institution=institution,
        branch=branch_main,
    )
    officer = create_user(
        email="officer@portal.test",
        username="portal-officer",
        role="loan_officer",
        institution=institution,
        branch=branch_main,
    )
    manager = create_user(
        email="manager@portal.test",
        username="portal-manager",
        role="branch_manager",
        institution=institution,
        branch=branch_main,
    )

    own_client = create_client(
        institution=institution,
        branch=branch_main,
        user=client_user,
        first_name="Amina",
        last_name="Okuya",
        phone="0700111000",
        email="amina@portal.test",
        occupation="Retailer",
        next_of_kin_name="Sarah Okuya",
        next_of_kin_phone="0700999000",
        address="Kampala Road",
    )
    other_client = create_client(
        institution=institution,
        branch=branch_north,
        user=other_client_user,
        first_name="Brian",
        last_name="North",
        phone="0700222000",
        email="brian@portal.test",
    )

    own_savings = SavingsAccount.objects.create(client=own_client)
    other_savings = SavingsAccount.objects.create(client=other_client)

    SavingsService.deposit(
        account=own_savings,
        amount=Decimal("200.00"),
        performed_by=teller,
        reference="SELF-SAV-DEP-1",
        transaction_date=timezone.localdate() - timedelta(days=14),
        notes="Initial deposit",
    )
    SavingsService.withdraw(
        account=own_savings,
        amount=Decimal("50.00"),
        performed_by=teller,
        reference="SELF-SAV-WIT-1",
        notes="Withdrawal",
    )
    SavingsService.deposit(
        account=other_savings,
        amount=Decimal("80.00"),
        performed_by=teller,
        reference="SELF-SAV-DEP-OTHER",
        notes="Other client deposit",
    )

    active_product = LoanProduct.objects.create(
        institution=institution,
        name="Business Growth",
        code="business-growth",
        min_amount=Decimal("100.00"),
        max_amount=Decimal("5000.00"),
        annual_interest_rate=Decimal("12.00"),
        interest_method="flat",
        repayment_frequency="monthly",
        min_term_months=3,
        max_term_months=24,
        default_term_months=6,
    )
    inactive_product = LoanProduct.objects.create(
        institution=institution,
        name="Dormant Product",
        code="dormant-product",
        min_amount=Decimal("100.00"),
        max_amount=Decimal("2000.00"),
        annual_interest_rate=Decimal("10.00"),
        interest_method="flat",
        repayment_frequency="monthly",
        min_term_months=1,
        max_term_months=12,
        is_active=False,
    )

    pending_loan = LoanApplication.objects.create(
        client=own_client,
        product=active_product,
        amount=Decimal("400.00"),
        term_months=4,
        purpose="Pending stock",
    )
    LoanService.initialize_new_application(
        loan=pending_loan,
        created_by=client_user,
        submit=True,
    )

    active_loan = LoanApplication.objects.create(
        client=own_client,
        product=active_product,
        amount=Decimal("600.00"),
        term_months=6,
        purpose="Working capital",
    )
    LoanService.initialize_new_application(
        loan=active_loan,
        created_by=client_user,
        submit=True,
    )
    LoanService.recommend(loan=active_loan, user=officer, comment="Recommended")
    LoanService.approve(loan=active_loan, user=manager, comment="Approved")
    LoanService.disburse(
        loan=active_loan,
        user=teller,
        reference="SELF-LOAN-DISB-1",
        disbursement_method="cash",
    )
    LoanService.repay(
        loan=active_loan,
        amount=Decimal("100.00"),
        reference="SELF-LOAN-REP-1",
        received_by=teller,
        payment_method="cash",
    )

    other_loan = LoanApplication.objects.create(
        client=other_client,
        product=active_product,
        amount=Decimal("300.00"),
        term_months=3,
        purpose="Other client loan",
    )
    LoanService.initialize_new_application(
        loan=other_loan,
        created_by=other_client_user,
        submit=True,
    )

    return {
        "institution": institution,
        "branch_main": branch_main,
        "client_user": client_user,
        "other_client_user": other_client_user,
        "teller": teller,
        "own_client": own_client,
        "other_client": other_client,
        "own_savings": own_savings,
        "other_savings": other_savings,
        "active_product": active_product,
        "inactive_product": inactive_product,
        "pending_loan": pending_loan,
        "active_loan": active_loan,
        "other_loan": other_loan,
    }


@pytest.mark.django_db
def test_self_service_profile_dashboard_and_safe_update_flow():
    fixture = build_self_service_fixture()
    api = auth_client(fixture["client_user"])

    me_response = api.get("/api/v1/me/")
    assert me_response.status_code == 200
    assert me_response.data["role"] == "client"
    assert me_response.data["linked_client_id"] == str(fixture["own_client"].id)
    assert me_response.data["branch_name"] == "Main"

    profile_response = api.get("/api/v1/self-service/profile/")
    assert profile_response.status_code == 200
    assert profile_response.data["id"] == str(fixture["own_client"].id)
    assert profile_response.data["client_number"] == fixture["own_client"].member_number
    assert profile_response.data["occupation"] == "Retailer"
    assert profile_response.data["next_of_kin_name"] == "Sarah Okuya"

    safe_update = api.patch(
        "/api/v1/self-service/profile/",
        {
            "phone": "0700555000",
            "email": "updated@portal.test",
            "address": "Ntinda",
        },
        format="json",
    )
    assert safe_update.status_code == 200
    assert safe_update.data["phone"] == "0700555000"
    assert safe_update.data["email"] == "updated@portal.test"
    assert safe_update.data["address"] == "Ntinda"

    blocked_update = api.patch(
        "/api/v1/self-service/profile/",
        {"occupation": "Changed by client"},
        format="json",
    )
    assert blocked_update.status_code == 400

    dashboard_response = api.get("/api/v1/self-service/dashboard/")
    assert dashboard_response.status_code == 200
    assert dashboard_response.data["profile_summary"]["id"] == str(fixture["own_client"].id)
    assert dashboard_response.data["total_savings_balance"] == "150.00"
    assert dashboard_response.data["active_savings_accounts_count"] == 1
    assert dashboard_response.data["active_loans_count"] == 1
    assert dashboard_response.data["pending_loan_applications_count"] == 1
    assert dashboard_response.data["outstanding_loan_balance"] == "536.00"
    assert dashboard_response.data["total_repayments_made"] == "100.00"
    assert dashboard_response.data["unread_notifications_count"] >= 1
    assert len(dashboard_response.data["recent_savings_transactions"]) == 2
    assert len(dashboard_response.data["recent_loan_applications"]) >= 2
    assert len(dashboard_response.data["recent_repayments"]) == 1


@pytest.mark.django_db
def test_self_service_savings_and_unified_transactions_are_scoped():
    fixture = build_self_service_fixture()
    api = auth_client(fixture["client_user"])

    savings_response = api.get("/api/v1/self-service/savings/")
    assert savings_response.status_code == 200
    assert savings_response.data["count"] == 1
    assert savings_response.data["results"][0]["id"] == str(fixture["own_savings"].id)

    savings_transactions = api.get("/api/v1/self-service/savings/transactions/")
    assert savings_transactions.status_code == 200
    assert savings_transactions.data["count"] == 2
    assert {
        row["reference"] for row in savings_transactions.data["results"]
    } == {"SELF-SAV-DEP-1", "SELF-SAV-WIT-1"}

    savings_summary = api.get("/api/v1/self-service/savings/summary/")
    assert savings_summary.status_code == 200
    assert savings_summary.data["client_name"] == "Amina Okuya"
    assert savings_summary.data["currency"] == "UGX"
    assert savings_summary.data["total_balance"] == "150.00"
    assert savings_summary.data["account_count"] == 1
    assert len(savings_summary.data["recent_activity"]) == 2

    savings_statement = api.get("/api/v1/self-service/savings/statement/")
    assert savings_statement.status_code == 200
    assert len(savings_statement.data["transactions"]) == 2
    assert {
        row["reference"] for row in savings_statement.data["transactions"]
    } == {"SELF-SAV-DEP-1", "SELF-SAV-WIT-1"}

    filtered_statement = api.get(
        "/api/v1/self-service/savings/statement/",
        {"date_from": (timezone.localdate() - timedelta(days=7)).isoformat()},
    )
    assert filtered_statement.status_code == 200
    assert [row["reference"] for row in filtered_statement.data["transactions"]] == [
        "SELF-SAV-WIT-1"
    ]

    blocked_other_account = api.get(
        "/api/v1/self-service/savings/transactions/",
        {"account": str(fixture["other_savings"].id)},
    )
    assert blocked_other_account.status_code == 200
    assert blocked_other_account.data["count"] == 0

    blocked_statement_account = api.get(
        "/api/v1/self-service/savings/statement/",
        {"account": str(fixture["other_savings"].id)},
    )
    assert blocked_statement_account.status_code == 200
    assert blocked_statement_account.data["transactions"] == []

    transactions_response = api.get("/api/v1/self-service/transactions/")
    assert transactions_response.status_code == 200
    assert transactions_response.data["count"] == 4
    references = {row["reference"] for row in transactions_response.data["results"]}
    assert "SELF-SAV-DEP-OTHER" not in references
    assert references == {
        "SELF-SAV-DEP-1",
        "SELF-SAV-WIT-1",
        "SELF-LOAN-DISB-1",
        "SELF-LOAN-REP-1",
    }
    first_row = transactions_response.data["results"][0]
    assert first_row["source"] in {"savings", "loans"}
    assert first_row["status"] == "posted"


@pytest.mark.django_db
def test_self_service_loan_products_applications_loans_and_repayments_are_scoped():
    fixture = build_self_service_fixture()
    api = auth_client(fixture["client_user"])

    loan_products = api.get("/api/v1/self-service/loan-products/")
    assert loan_products.status_code == 200
    assert loan_products.data["count"] == 1
    assert loan_products.data["results"][0]["id"] == str(fixture["active_product"].id)

    application_create = api.post(
        "/api/v1/self-service/loan-applications/",
        {
            "product": str(fixture["active_product"].id),
            "amount": "250.00",
            "term_months": 5,
            "purpose": "School fees",
        },
        format="json",
    )
    assert application_create.status_code == 201
    assert application_create.data["status"] == "submitted"
    assert str(application_create.data["client"]) == str(fixture["own_client"].id)

    blocked_other_client = api.post(
        "/api/v1/self-service/loan-applications/",
        {
            "client": str(fixture["other_client"].id),
            "product": str(fixture["active_product"].id),
            "amount": "250.00",
            "term_months": 5,
            "purpose": "Blocked",
        },
        format="json",
    )
    assert blocked_other_client.status_code == 400

    blocked_inactive_product = api.post(
        "/api/v1/self-service/loan-applications/",
        {
            "product": str(fixture["inactive_product"].id),
            "amount": "250.00",
            "term_months": 5,
            "purpose": "Blocked inactive product",
        },
        format="json",
    )
    assert blocked_inactive_product.status_code == 400

    own_applications = api.get("/api/v1/self-service/loan-applications/")
    assert own_applications.status_code == 200
    assert own_applications.data["count"] == 3

    own_application_detail = api.get(
        f"/api/v1/self-service/loan-applications/{fixture['pending_loan'].id}/"
    )
    assert own_application_detail.status_code == 200
    assert own_application_detail.data["product_name"] == "Business Growth"

    hidden_other_application = api.get(
        f"/api/v1/self-service/loan-applications/{fixture['other_loan'].id}/"
    )
    assert hidden_other_application.status_code == 404

    loans_response = api.get("/api/v1/self-service/loans/")
    assert loans_response.status_code == 200
    assert loans_response.data["count"] == 1
    assert loans_response.data["results"][0]["id"] == str(fixture["active_loan"].id)
    assert loans_response.data["results"][0]["repayment_frequency"] == "monthly"
    assert loans_response.data["results"][0]["next_due_date"] is not None

    loan_detail = api.get(f"/api/v1/self-service/loans/{fixture['active_loan'].id}/")
    assert loan_detail.status_code == 200
    assert len(loan_detail.data["schedule"]) == 6
    assert len(loan_detail.data["repayments"]) == 1
    assert loan_detail.data["next_due_date"] is not None

    loan_statement = api.get("/api/v1/self-service/loans/statement/")
    assert loan_statement.status_code == 200
    assert loan_statement.data["selected_loan_id"] == str(fixture["active_loan"].id)
    assert loan_statement.data["loan_summary"]["status"] == "disbursed"
    assert loan_statement.data["balances"]["outstanding_balance"] == "536.00"
    assert loan_statement.data["balances"]["total_repaid"] == "100.00"
    assert len(loan_statement.data["available_loans"]) == 1
    assert len(loan_statement.data["repayments"]) == 1
    assert len(loan_statement.data["repayment_schedule"]) == 6

    hidden_other_statement = api.get(
        "/api/v1/self-service/loans/statement/",
        {"loan": str(fixture["other_loan"].id)},
    )
    assert hidden_other_statement.status_code == 404

    repayments_response = api.get("/api/v1/self-service/repayments/")
    assert repayments_response.status_code == 200
    assert repayments_response.data["count"] == 1
    assert repayments_response.data["results"][0]["reference"] == "SELF-LOAN-REP-1"


@pytest.mark.django_db
def test_self_service_notifications_and_staff_only_boundaries():
    fixture = build_self_service_fixture()
    api = auth_client(fixture["client_user"])

    notifications_response = api.get("/api/v1/self-service/notifications/")
    assert notifications_response.status_code == 200
    assert notifications_response.data["count"] >= 1
    notification_id = notifications_response.data["results"][0]["id"]
    assert Notification.objects.filter(user=fixture["client_user"]).count() == notifications_response.data["count"]

    mark_read_response = api.post(
        f"/api/v1/self-service/notifications/{notification_id}/mark-read/"
    )
    assert mark_read_response.status_code == 200
    assert mark_read_response.data["is_read"] is True

    mark_read_patch_response = api.patch(
        f"/api/v1/self-service/notifications/{notification_id}/mark-read/"
    )
    assert mark_read_patch_response.status_code == 200
    assert mark_read_patch_response.data["is_read"] is True

    mark_all_response = api.post("/api/v1/self-service/notifications/mark-all-read/")
    assert mark_all_response.status_code == 200
    assert Notification.objects.filter(user=fixture["client_user"], is_read=False).count() == 0

    blocked_cash_action = api.post(
        f"/api/v1/savings/accounts/{fixture['own_savings'].id}/deposit/",
        {"amount": "25.00", "reference": "BLOCKED-CLIENT-DEP"},
        format="json",
    )
    assert blocked_cash_action.status_code == 403

    blocked_approval = api.post(
        f"/api/v1/loans/applications/{fixture['active_loan'].id}/approve/",
        format="json",
    )
    assert blocked_approval.status_code == 403

    blocked_report = api.get("/api/v1/reports/trial-balance/")
    assert blocked_report.status_code == 403
