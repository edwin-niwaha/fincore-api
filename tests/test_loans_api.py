from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanApplicationAction, LoanProduct, LoanRepayment, RepaymentSchedule
from apps.notifications.models import Notification
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
        "first_name": "John",
        "last_name": "Borrower",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


@pytest.mark.django_db
def test_loan_product_crud_is_scoped_and_client_only_sees_active_products():
    alpha = Institution.objects.create(name="Alpha SACCO", code="alpha")
    beta = Institution.objects.create(name="Beta SACCO", code="beta")
    alpha_branch = Branch.objects.create(institution=alpha, name="Main", code="main")
    admin = create_user(
        email="admin@alpha.test",
        username="alpha-admin",
        role="institution_admin",
        institution=alpha,
        branch=alpha_branch,
    )
    client_user = create_user(
        email="client@alpha.test",
        username="alpha-client",
        role="client",
        institution=alpha,
        branch=alpha_branch,
    )

    api = APIClient()
    api.force_authenticate(user=admin)

    create_response = api.post(
        "/api/v1/loans/products/",
        {
            "institution": str(alpha.id),
            "name": "Business Booster",
            "code": "biz-boost",
            "min_amount": "200.00",
            "max_amount": "5000.00",
            "annual_interest_rate": "12.00",
            "interest_method": "flat",
            "repayment_frequency": "monthly",
            "min_term_months": 3,
            "max_term_months": 24,
            "default_term_months": 12,
            "penalty_rate": "2.50",
            "penalty_flat_amount": "500.00",
            "penalty_grace_days": 5,
            "is_active": True,
        },
        format="json",
    )
    assert create_response.status_code == 201
    product_id = create_response.data["id"]
    assert create_response.data["interest_method"] == "flat"
    assert create_response.data["repayment_frequency"] == "monthly"

    blocked_create = api.post(
        "/api/v1/loans/products/",
        {
            "institution": str(beta.id),
            "name": "Blocked Product",
            "code": "blocked",
            "min_amount": "100.00",
            "max_amount": "1000.00",
            "annual_interest_rate": "10.00",
            "interest_method": "flat",
            "repayment_frequency": "monthly",
            "min_term_months": 1,
            "max_term_months": 12,
            "is_active": True,
        },
        format="json",
    )
    assert blocked_create.status_code == 403

    patch_response = api.patch(
        f"/api/v1/loans/products/{product_id}/",
        {"annual_interest_rate": "14.50", "is_active": False},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["annual_interest_rate"] == "14.50"
    assert patch_response.data["is_active"] is False

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)
    client_list = client_api.get("/api/v1/loans/products/")
    assert client_list.status_code == 200
    assert client_list.data["count"] == 0

    api.patch(
        f"/api/v1/loans/products/{product_id}/",
        {"is_active": True},
        format="json",
    )
    client_list = client_api.get("/api/v1/loans/products/")
    assert client_list.status_code == 200
    assert client_list.data["count"] == 1


@pytest.mark.django_db
def test_full_loan_lifecycle_generates_schedule_history_notifications_and_closure():
    institution = Institution.objects.create(name="Lifecycle SACCO", code="lifecycle")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    officer = create_user(
        email="officer@life.test",
        username="life-officer",
        role="loan_officer",
        institution=institution,
        branch=branch,
    )
    manager = create_user(
        email="manager@life.test",
        username="life-manager",
        role="branch_manager",
        institution=institution,
        branch=branch,
    )
    teller = create_user(
        email="teller@life.test",
        username="life-teller",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client_user = create_user(
        email="client@life.test",
        username="life-client",
        role="client",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch, user=client_user)
    product = LoanProduct.objects.create(
        institution=institution,
        name="Working Capital",
        code="working-capital",
        min_amount=Decimal("200.00"),
        max_amount=Decimal("5000.00"),
        annual_interest_rate=Decimal("12.00"),
        interest_method="flat",
        repayment_frequency="monthly",
        min_term_months=3,
        max_term_months=24,
        default_term_months=6,
    )

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)
    create_response = client_api.post(
        "/api/v1/loans/applications/",
        {
            "product": str(product.id),
            "amount": "1200.00",
            "term_months": 6,
            "purpose": "Stock financing",
        },
        format="json",
    )
    assert create_response.status_code == 201
    loan_id = create_response.data["id"]
    assert create_response.data["status"] == "submitted"

    officer_api = APIClient()
    officer_api.force_authenticate(user=officer)
    review_response = officer_api.post(
        f"/api/v1/loans/applications/{loan_id}/start-review/",
        {"comment": "Starting appraisal"},
        format="json",
    )
    assert review_response.status_code == 200
    assert review_response.data["status"] == "under_review"

    recommend_response = officer_api.post(
        f"/api/v1/loans/applications/{loan_id}/recommend/",
        {"comment": "Cash flow and guarantors are acceptable."},
        format="json",
    )
    assert recommend_response.status_code == 200
    assert recommend_response.data["status"] == "recommended"

    manager_api = APIClient()
    manager_api.force_authenticate(user=manager)
    approve_response = manager_api.post(
        f"/api/v1/loans/applications/{loan_id}/approve/",
        {"comment": "Approved by branch manager."},
        format="json",
    )
    assert approve_response.status_code == 200
    assert approve_response.data["status"] == "approved"

    teller_api = APIClient()
    teller_api.force_authenticate(user=teller)
    disburse_response = teller_api.post(
        f"/api/v1/loans/applications/{loan_id}/disburse/",
        {"reference": "DISB-LIFE-1", "disbursement_method": "cash"},
        format="json",
    )
    assert disburse_response.status_code == 200
    assert disburse_response.data["status"] == "disbursed"
    assert disburse_response.data["principal_balance"] == "1200.00"
    assert disburse_response.data["interest_balance"] == "72.00"
    assert disburse_response.data["disbursement_reference"] == "DISB-LIFE-1"
    assert disburse_response.data["disbursement_method"] == "cash"

    loan = LoanApplication.objects.get(pk=loan_id)
    schedule_rows = list(loan.schedule.order_by("due_date", "created_at"))
    assert len(schedule_rows) == 6
    assert sum((row.principal_due for row in schedule_rows), Decimal("0.00")) == Decimal("1200.00")
    assert sum((row.interest_due for row in schedule_rows), Decimal("0.00")) == Decimal("72.00")

    detail_response = client_api.get(f"/api/v1/loans/applications/{loan_id}/")
    assert detail_response.status_code == 200
    assert len(detail_response.data["schedule"]) == 6
    assert detail_response.data["outstanding_balance"] == "1272.00"
    assert [row["action"] for row in detail_response.data["action_history"]] == [
        "create",
        "submit",
        "start_review",
        "recommend",
        "approve",
        "disburse",
    ]

    first_repayment = teller_api.post(
        f"/api/v1/loans/applications/{loan_id}/repay/",
        {"amount": "300.00", "reference": "REP-LIFE-1", "payment_method": "cash"},
        format="json",
    )
    assert first_repayment.status_code == 201
    assert first_repayment.data["interest_component"] == "72.00"
    assert first_repayment.data["principal_component"] == "228.00"
    assert first_repayment.data["remaining_balance_after"] == "972.00"
    assert first_repayment.data["payment_method"] == "cash"

    final_repayment = teller_api.post(
        f"/api/v1/loans/applications/{loan_id}/repay/",
        {"amount": "972.00", "reference": "REP-LIFE-2", "payment_method": "cash"},
        format="json",
    )
    assert final_repayment.status_code == 201
    assert final_repayment.data["remaining_balance_after"] == "0.00"

    loan.refresh_from_db()
    assert loan.status == LoanApplication.Status.CLOSED
    assert loan.principal_balance == Decimal("0.00")
    assert loan.interest_balance == Decimal("0.00")
    assert LoanRepayment.objects.filter(loan=loan).count() == 2
    assert RepaymentSchedule.objects.filter(loan=loan, is_paid=False).count() == 0
    assert LoanApplicationAction.objects.filter(application=loan).count() == 8

    categories = list(
        Transaction.objects.filter(client=client)
        .order_by("created_at")
        .values_list("category", flat=True)
    )
    assert categories == ["loan_disbursement", "loan_repayment", "loan_repayment"]

    client_notifications = list(
        Notification.objects.filter(user=client_user).values_list("category", flat=True)
    )
    assert "loan_application_submitted" in client_notifications
    assert "loan_recommended" in client_notifications
    assert "loan_approved" in client_notifications
    assert "loan_disbursed" in client_notifications
    assert "loan_repayment_recorded" in client_notifications

    audit_actions = list(
        AuditLog.objects.filter(target=str(loan.id))
        .order_by("created_at")
        .values_list("action", flat=True)
    )
    assert audit_actions == [
        "loan.application.create",
        "loan.submit",
        "loan.start_review",
        "loan.recommend",
        "loan.approve",
        "loan.disburse",
        "loan.repay",
        "loan.repay",
    ]


@pytest.mark.django_db
def test_invalid_loan_actions_and_permissions_are_enforced_for_client_officer_and_manager():
    institution = Institution.objects.create(name="Guard SACCO", code="guard-loan")
    branch_a = Branch.objects.create(institution=institution, name="Main", code="main")
    branch_b = Branch.objects.create(institution=institution, name="North", code="north")
    officer_a = create_user(
        email="officer-a@guard.test",
        username="guard-officer-a",
        role="loan_officer",
        institution=institution,
        branch=branch_a,
    )
    manager_a = create_user(
        email="manager-a@guard.test",
        username="guard-manager-a",
        role="branch_manager",
        institution=institution,
        branch=branch_a,
    )
    teller_a = create_user(
        email="teller-a@guard.test",
        username="guard-teller-a",
        role="teller",
        institution=institution,
        branch=branch_a,
    )
    client_user = create_user(
        email="client@guard.test",
        username="guard-client",
        role="client",
        institution=institution,
        branch=branch_a,
    )
    own_client = create_client(institution=institution, branch=branch_a, user=client_user)
    other_client = create_client(
        institution=institution,
        branch=branch_b,
        first_name="Other",
        last_name="Branch",
    )
    inactive_product = LoanProduct.objects.create(
        institution=institution,
        name="Inactive Loan",
        code="inactive-loan",
        min_amount=Decimal("100.00"),
        max_amount=Decimal("2000.00"),
        annual_interest_rate=Decimal("10.00"),
        interest_method="flat",
        repayment_frequency="monthly",
        min_term_months=1,
        max_term_months=12,
        is_active=False,
    )
    active_product = LoanProduct.objects.create(
        institution=institution,
        name="Active Loan",
        code="active-loan",
        min_amount=Decimal("100.00"),
        max_amount=Decimal("2000.00"),
        annual_interest_rate=Decimal("10.00"),
        interest_method="flat",
        repayment_frequency="monthly",
        min_term_months=1,
        max_term_months=12,
    )

    officer_api = APIClient()
    officer_api.force_authenticate(user=officer_a)

    blocked_scope_create = officer_api.post(
        "/api/v1/loans/applications/",
        {
            "client": str(other_client.id),
            "product": str(active_product.id),
            "amount": "500.00",
            "term_months": 6,
            "purpose": "Out of scope",
        },
        format="json",
    )
    assert blocked_scope_create.status_code == 403

    blocked_inactive_product = officer_api.post(
        "/api/v1/loans/applications/",
        {
            "client": str(own_client.id),
            "product": str(inactive_product.id),
            "amount": "500.00",
            "term_months": 6,
            "purpose": "Inactive product",
        },
        format="json",
    )
    assert blocked_inactive_product.status_code == 400

    teller_api = APIClient()
    teller_api.force_authenticate(user=teller_a)
    teller_create = teller_api.post(
        "/api/v1/loans/applications/",
        {
            "client": str(own_client.id),
            "product": str(active_product.id),
            "amount": "500.00",
            "term_months": 6,
            "purpose": "Blocked teller create",
        },
        format="json",
    )
    assert teller_create.status_code == 403

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)
    client_create = client_api.post(
        "/api/v1/loans/applications/",
        {
            "client": str(other_client.id),
            "product": str(active_product.id),
            "amount": "300.00",
            "term_months": 3,
            "purpose": "Blocked self-creation for another client",
        },
        format="json",
    )
    assert client_create.status_code == 400

    create_response = officer_api.post(
        "/api/v1/loans/applications/",
        {
            "client": str(own_client.id),
            "product": str(active_product.id),
            "amount": "500.00",
            "term_months": 6,
            "purpose": "Working capital",
            "submit": True,
        },
        format="json",
    )
    assert create_response.status_code == 201
    loan_id = create_response.data["id"]
    assert create_response.data["status"] == "submitted"

    repay_before_disbursement = teller_api.post(
        f"/api/v1/loans/applications/{loan_id}/repay/",
        {"amount": "50.00", "reference": "EARLY-REP"},
        format="json",
    )
    assert repay_before_disbursement.status_code == 400

    officer_approve = officer_api.post(f"/api/v1/loans/applications/{loan_id}/approve/")
    assert officer_approve.status_code == 403

    manager_api = APIClient()
    manager_api.force_authenticate(user=manager_a)
    approve_before_recommend = manager_api.post(
        f"/api/v1/loans/applications/{loan_id}/approve/",
        format="json",
    )
    assert approve_before_recommend.status_code == 400

    reject_response = officer_api.post(
        f"/api/v1/loans/applications/{loan_id}/reject/",
        {"reason": "Incomplete documentation"},
        format="json",
    )
    assert reject_response.status_code == 200
    assert reject_response.data["status"] == "rejected"

    approve_rejected = manager_api.post(f"/api/v1/loans/applications/{loan_id}/approve/")
    assert approve_rejected.status_code == 400

    disburse_rejected = teller_api.post(
        f"/api/v1/loans/applications/{loan_id}/disburse/",
        {"reference": "DISB-REJECTED"},
        format="json",
    )
    assert disburse_rejected.status_code == 400

    delete_rejected = officer_api.delete(f"/api/v1/loans/applications/{loan_id}/")
    assert delete_rejected.status_code == 400

    approved_response = officer_api.post(
        "/api/v1/loans/applications/",
        {
            "client": str(own_client.id),
            "product": str(active_product.id),
            "amount": "600.00",
            "term_months": 6,
            "purpose": "Approved path",
            "submit": True,
        },
        format="json",
    )
    assert approved_response.status_code == 201
    disbursable_loan_id = approved_response.data["id"]
    assert officer_api.post(
        f"/api/v1/loans/applications/{disbursable_loan_id}/recommend/",
        {"comment": "Recommend for approval"},
        format="json",
    ).status_code == 200
    assert manager_api.post(
        f"/api/v1/loans/applications/{disbursable_loan_id}/approve/",
        format="json",
    ).status_code == 200
    assert teller_api.post(
        f"/api/v1/loans/applications/{disbursable_loan_id}/disburse/",
        {"reference": "DISB-VALID"},
        format="json",
    ).status_code == 200

    overpayment = teller_api.post(
        f"/api/v1/loans/applications/{disbursable_loan_id}/repay/",
        {"amount": "10000.00", "reference": "OVERPAY"},
        format="json",
    )
    assert overpayment.status_code == 400

    blocked_client_approve = client_api.post(
        f"/api/v1/loans/applications/{disbursable_loan_id}/approve/",
        format="json",
    )
    assert blocked_client_approve.status_code == 403
