import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.audit.services import AuditService
from apps.institutions.models import Branch, Institution


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


@pytest.mark.django_db
def test_audit_logs_are_scoped_filterable_and_summarized():
    alpha = Institution.objects.create(name="Alpha SACCO", code="alpha")
    beta = Institution.objects.create(name="Beta SACCO", code="beta")
    alpha_branch = Branch.objects.create(institution=alpha, name="Main", code="main")
    beta_branch = Branch.objects.create(institution=beta, name="Town", code="town")

    super_admin = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    alpha_admin = create_user(
        email="admin@alpha.test",
        username="alpha-admin",
        role="institution_admin",
        institution=alpha,
        branch=alpha_branch,
    )
    alpha_teller = create_user(
        email="teller@alpha.test",
        username="alpha-teller",
        role="teller",
        institution=alpha,
        branch=alpha_branch,
    )
    beta_teller = create_user(
        email="teller@beta.test",
        username="beta-teller",
        role="teller",
        institution=beta,
        branch=beta_branch,
    )

    AuditService.log(
        user=alpha_admin,
        action="users.account.create",
        target="user-1",
        metadata={"email": "new-user@alpha.test"},
        request_path="/api/v1/users/",
    )
    AuditService.log(
        user=alpha_teller,
        action="savings.account.create",
        target="SAV-001",
        metadata={"account_number": "SAV-001"},
        request_path="/api/v1/savings/accounts/",
    )
    AuditService.log(
        action="reports.export.completed",
        institution=alpha,
        branch=alpha_branch,
        metadata={"report": "loan-portfolio"},
        request_path="/api/v1/reports/loan-portfolio/",
    )
    AuditService.log(
        user=beta_teller,
        action="loans.application.approve",
        target="loan-001",
        metadata={"reference": "loan-001"},
        request_path="/api/v1/loans/applications/loan-001/approve/",
    )

    alpha_api = APIClient()
    alpha_api.force_authenticate(user=alpha_admin)

    list_response = alpha_api.get("/api/v1/audit-logs/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 3
    assert {row["institution_name"] for row in list_response.data["results"]} == {
        "Alpha SACCO"
    }

    savings_response = alpha_api.get("/api/v1/audit-logs/?module=savings")
    assert savings_response.status_code == 200
    assert savings_response.data["count"] == 1
    assert savings_response.data["results"][0]["resource"] == "account"
    assert savings_response.data["results"][0]["event"] == "create"

    search_response = alpha_api.get(
        "/api/v1/audit-logs/?search=/api/v1/reports/loan-portfolio/"
    )
    assert search_response.status_code == 200
    assert search_response.data["count"] == 1
    assert search_response.data["results"][0]["module"] == "reports"

    summary_response = alpha_api.get("/api/v1/audit-logs/summary/")
    assert summary_response.status_code == 200
    assert summary_response.data["total_logs"] == 3
    assert summary_response.data["today_logs"] == 3
    assert summary_response.data["actors"] == 2
    assert summary_response.data["modules"] == 3

    super_api = APIClient()
    super_api.force_authenticate(user=super_admin)

    beta_response = super_api.get(f"/api/v1/audit-logs/?institution={beta.id}")
    assert beta_response.status_code == 200
    assert beta_response.data["count"] == 1
    assert beta_response.data["results"][0]["institution_name"] == "Beta SACCO"


@pytest.mark.django_db
def test_non_admin_users_cannot_access_audit_logs():
    institution = Institution.objects.create(name="Denied SACCO", code="denied")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@denied.test",
        username="denied-teller",
        role="teller",
        institution=institution,
        branch=branch,
    )

    api = APIClient()
    api.force_authenticate(user=teller)

    response = api.get("/api/v1/audit-logs/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_and_auth_actions_write_audit_logs():
    super_admin = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    api = APIClient()
    api.force_authenticate(user=super_admin)

    institution_response = api.post(
        "/api/v1/institutions/",
        {
            "name": "Gamma SACCO",
            "code": "gamma",
            "currency": "UGX",
            "status": "active",
        },
        format="json",
    )
    assert institution_response.status_code == 201
    institution_id = institution_response.data["id"]

    branch_response = api.post(
        "/api/v1/branches/",
        {
            "institution": institution_id,
            "name": "Gamma Main",
            "code": "gamma-main",
            "address": "Kampala",
            "status": "active",
        },
        format="json",
    )
    assert branch_response.status_code == 201
    branch_id = branch_response.data["id"]

    user_response = api.post(
        "/api/v1/users/",
        {
            "email": "staff@gamma.test",
            "username": "gamma-staff",
            "first_name": "Gamma",
            "last_name": "Staff",
            "role": "teller",
            "institution": institution_id,
            "branch": branch_id,
            "password": "Password123!",
            "is_active": True,
        },
        format="json",
    )
    assert user_response.status_code == 201

    password_response = api.post(
        "/api/v1/auth/change-password/",
        {
            "current_password": "Password123!",
            "new_password": "NewPassword123!",
            "new_password_confirm": "NewPassword123!",
        },
        format="json",
    )
    assert password_response.status_code == 200

    assert AuditLog.objects.filter(action="institutions.record.create").exists()
    assert AuditLog.objects.filter(action="branches.record.create").exists()
    assert AuditLog.objects.filter(action="users.account.create").exists()
    assert AuditLog.objects.filter(action="auth.password.change").exists()
