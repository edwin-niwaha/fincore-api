import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient

from apps.institutions.models import Branch, Institution

User = get_user_model()


def create_user(
    *,
    email,
    username,
    role,
    institution=None,
    branch=None,
    password="Password123!",
    **extra_fields,
):
    return User.objects.create_user(
        email=email,
        username=username,
        password=password,
        role=role,
        institution=institution,
        branch=branch,
        **extra_fields,
    )


def extract_code():
    assert mail.outbox
    match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
    assert match
    return match.group(1)


def auth_client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.mark.django_db
def test_register_refresh_logout_and_email_verification_flow():
    api = APIClient()

    register_response = api.post(
        "/api/v1/auth/register/",
        {
            "email": "client@example.com",
            "username": "client1",
            "password": "Password123!",
            "password_confirm": "Password123!",
        },
        format="json",
    )

    assert register_response.status_code == 201
    assert register_response.data["user"]["role"] == "client"
    assert register_response.data["user"]["is_email_verified"] is False
    assert len(mail.outbox) == 1

    access = register_response.data["tokens"]["access"]
    refresh = register_response.data["tokens"]["refresh"]

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    me_response = api.get("/api/v1/auth/me/")
    assert me_response.status_code == 200
    assert me_response.data["email"] == "client@example.com"

    refresh_response = api.post(
        "/api/v1/auth/refresh/",
        {"refresh": refresh},
        format="json",
    )
    assert refresh_response.status_code == 200
    assert refresh_response.data["access"]
    latest_refresh = refresh_response.data.get("refresh", refresh)

    verify_response = api.post(
        "/api/v1/auth/verify-email/",
        {"code": extract_code()},
        format="json",
    )
    assert verify_response.status_code == 200
    assert verify_response.data["user"]["is_email_verified"] is True

    logout_response = api.post(
        "/api/v1/auth/logout/",
        {"refresh": latest_refresh},
        format="json",
    )
    assert logout_response.status_code == 200


@pytest.mark.django_db
def test_profile_update_and_change_password_flow():
    user = create_user(
        email="member@example.com",
        username="member1",
        role="client",
    )
    api = APIClient()

    login_response = api.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "Password123!"},
        format="json",
    )
    assert login_response.status_code == 200

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['tokens']['access']}")

    profile_response = api.patch(
        "/api/v1/auth/me/",
        {
            "username": "member2",
            "first_name": "Grace",
            "last_name": "Hopper",
            "phone": "0700111222",
        },
        format="json",
    )
    assert profile_response.status_code == 200
    assert profile_response.data["username"] == "member2"
    assert profile_response.data["full_name"] == "Grace Hopper"
    assert profile_response.data["phone"] == "0700111222"

    change_password_response = api.post(
        "/api/v1/auth/change-password/",
        {
            "current_password": "Password123!",
            "new_password": "NewPassword123!",
            "new_password_confirm": "NewPassword123!",
        },
        format="json",
    )
    assert change_password_response.status_code == 200

    failed_login = api.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "Password123!"},
        format="json",
    )
    assert failed_login.status_code == 401

    successful_login = api.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "NewPassword123!"},
        format="json",
    )
    assert successful_login.status_code == 200


@pytest.mark.django_db
def test_send_email_verification_and_reset_password_flow():
    user = create_user(
        email="verifyme@example.com",
        username="verifyme",
        role="client",
    )
    api = auth_client(user)

    send_verification_response = api.post("/api/v1/auth/send-email-verification/")
    assert send_verification_response.status_code == 200
    assert extract_code()

    verify_response = api.post(
        "/api/v1/auth/verify-email/",
        {"code": extract_code()},
        format="json",
    )
    assert verify_response.status_code == 200
    assert verify_response.data["user"]["is_email_verified"] is True

    forgot_password_response = APIClient().post(
        "/api/v1/auth/forgot-password/",
        {"email": user.email},
        format="json",
    )
    assert forgot_password_response.status_code == 200

    reset_password_response = APIClient().post(
        "/api/v1/auth/reset-password/",
        {
            "email": user.email,
            "code": extract_code(),
            "password": "AnotherPassword123!",
            "password_confirm": "AnotherPassword123!",
        },
        format="json",
    )
    assert reset_password_response.status_code == 200

    login_response = APIClient().post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "AnotherPassword123!"},
        format="json",
    )
    assert login_response.status_code == 200


@pytest.mark.django_db
def test_super_admin_can_crud_and_filter_users():
    institution = Institution.objects.create(name="North SACCO", code="north")
    branch = Branch.objects.create(
        institution=institution,
        name="North Branch",
        code="north-branch",
    )
    user = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    api = auth_client(user)

    create_response = api.post(
        "/api/v1/users/",
        {
            "email": "teller@example.com",
            "username": "teller1",
            "first_name": "Teller",
            "last_name": "One",
            "phone": "0700999000",
            "role": "teller",
            "institution": str(institution.id),
            "branch": str(branch.id),
            "password": "Password123!",
        },
        format="json",
    )
    assert create_response.status_code == 201
    created_user_id = create_response.data["id"]
    assert create_response.data["institution_name"] == "North SACCO"
    assert create_response.data["branch_name"] == "North Branch"
    assert create_response.data["role_display"] == "Teller/Cashier"

    deactivate_response = api.patch(
        f"/api/v1/users/{created_user_id}/",
        {"is_active": False},
        format="json",
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.data["is_active"] is False

    filtered_response = api.get("/api/v1/users/?role=teller&is_active=false")
    assert filtered_response.status_code == 200
    assert filtered_response.data["count"] == 1
    assert filtered_response.data["results"][0]["id"] == created_user_id

    delete_response = api.delete(f"/api/v1/users/{created_user_id}/")
    assert delete_response.status_code == 204


@pytest.mark.django_db
def test_institution_admin_user_scope_and_role_limits():
    own_institution = Institution.objects.create(name="Own SACCO", code="own-sacco")
    own_branch = Branch.objects.create(
        institution=own_institution,
        name="Own Branch",
        code="own-branch",
    )
    other_institution = Institution.objects.create(name="Other SACCO", code="other-sacco")
    other_branch = Branch.objects.create(
        institution=other_institution,
        name="Other Branch",
        code="other-branch",
    )
    actor = create_user(
        email="inst-admin@example.com",
        username="inst-admin",
        role="institution_admin",
        institution=own_institution,
    )
    own_staff = create_user(
        email="own-officer@example.com",
        username="own-officer",
        role="loan_officer",
        institution=own_institution,
        branch=own_branch,
    )
    other_staff = create_user(
        email="other-officer@example.com",
        username="other-officer",
        role="loan_officer",
        institution=other_institution,
        branch=other_branch,
    )
    api = auth_client(actor)

    list_response = api.get("/api/v1/users/")
    assert list_response.status_code == 200
    listed_ids = {row["id"] for row in list_response.data["results"]}
    assert actor.id in listed_ids
    assert own_staff.id in listed_ids
    assert other_staff.id not in listed_ids

    create_response = api.post(
        "/api/v1/users/",
        {
            "email": "branch-manager@example.com",
            "username": "branch-manager",
            "role": "branch_manager",
            "branch": str(own_branch.id),
            "password": "Password123!",
        },
        format="json",
    )
    assert create_response.status_code == 201
    assert str(create_response.data["institution"]) == str(own_institution.id)
    assert str(create_response.data["branch"]) == str(own_branch.id)

    forbidden_role_response = api.post(
        "/api/v1/users/",
        {
            "email": "forbidden@example.com",
            "username": "forbidden",
            "role": "super_admin",
            "password": "Password123!",
        },
        format="json",
    )
    assert forbidden_role_response.status_code == 403

    forbidden_branch_response = api.post(
        "/api/v1/users/",
        {
            "email": "outside@example.com",
            "username": "outside",
            "role": "teller",
            "institution": str(other_institution.id),
            "branch": str(other_branch.id),
            "password": "Password123!",
        },
        format="json",
    )
    assert forbidden_branch_response.status_code == 403

    self_deactivate_response = api.patch(
        f"/api/v1/users/{actor.id}/",
        {"is_active": False},
        format="json",
    )
    assert self_deactivate_response.status_code == 400

    hidden_response = api.get(f"/api/v1/users/{other_staff.id}/")
    assert hidden_response.status_code == 404


@pytest.mark.django_db
def test_branch_manager_user_scope_and_role_limits():
    institution = Institution.objects.create(name="Scoped SACCO", code="scoped-sacco")
    own_branch = Branch.objects.create(
        institution=institution,
        name="Scoped Branch",
        code="scoped-branch",
    )
    other_branch = Branch.objects.create(
        institution=institution,
        name="Other Branch",
        code="other-branch",
    )
    actor = create_user(
        email="branch-manager@example.com",
        username="branch-manager",
        role="branch_manager",
        institution=institution,
        branch=own_branch,
    )
    own_teller = create_user(
        email="own-teller@example.com",
        username="own-teller",
        role="teller",
        institution=institution,
        branch=own_branch,
    )
    create_user(
        email="other-teller@example.com",
        username="other-teller",
        role="teller",
        institution=institution,
        branch=other_branch,
    )
    api = auth_client(actor)

    list_response = api.get("/api/v1/users/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == own_teller.id

    create_response = api.post(
        "/api/v1/users/",
        {
            "email": "loan-officer@example.com",
            "username": "loan-officer",
            "role": "loan_officer",
            "password": "Password123!",
        },
        format="json",
    )
    assert create_response.status_code == 201
    assert str(create_response.data["institution"]) == str(institution.id)
    assert str(create_response.data["branch"]) == str(own_branch.id)

    forbidden_role_response = api.post(
        "/api/v1/users/",
        {
            "email": "new-manager@example.com",
            "username": "new-manager",
            "role": "branch_manager",
            "password": "Password123!",
        },
        format="json",
    )
    assert forbidden_role_response.status_code == 403

    forbidden_branch_response = api.patch(
        f"/api/v1/users/{own_teller.id}/",
        {"branch": str(other_branch.id)},
        format="json",
    )
    assert forbidden_branch_response.status_code == 403


@pytest.mark.django_db
def test_non_manager_roles_cannot_access_user_management():
    institution = Institution.objects.create(name="Denied SACCO", code="denied-sacco")
    branch = Branch.objects.create(
        institution=institution,
        name="Denied Branch",
        code="denied-branch",
    )
    user = create_user(
        email="teller@example.com",
        username="teller",
        role="teller",
        institution=institution,
        branch=branch,
    )
    api = auth_client(user)

    response = api.get("/api/v1/users/")
    assert response.status_code == 403
