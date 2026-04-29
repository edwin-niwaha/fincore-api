import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

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
def test_super_admin_can_crud_institutions():
    user = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    api = APIClient()
    api.force_authenticate(user=user)

    create_response = api.post(
        "/api/v1/institutions/",
        {
            "name": "Alpha Finance",
            "code": "ALPHA FINANCE",
            "email": "hello@alpha.test",
            "phone": "0700000000",
            "currency": "UGX",
            "status": "active",
        },
        format="json",
    )

    assert create_response.status_code == 201
    institution_id = create_response.data["id"]
    assert create_response.data["code"] == "alpha-finance"
    assert create_response.data["display_name"] == "Alpha Finance (ALPHA-FINANCE)"
    assert create_response.data["branch_count"] == 0

    update_response = api.patch(
        f"/api/v1/institutions/{institution_id}/",
        {"status": "inactive"},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["status"] == "inactive"

    delete_response = api.delete(f"/api/v1/institutions/{institution_id}/")
    assert delete_response.status_code == 204
    assert not Institution.objects.filter(pk=institution_id).exists()


@pytest.mark.django_db
def test_institution_admin_is_scoped_to_own_institution_and_cannot_create_or_delete_it():
    own_institution = Institution.objects.create(name="Own SACCO", code="own")
    other_institution = Institution.objects.create(name="Other SACCO", code="other")
    user = create_user(
        email="admin@own.test",
        username="own-admin",
        role="institution_admin",
        institution=own_institution,
    )
    api = APIClient()
    api.force_authenticate(user=user)

    list_response = api.get("/api/v1/institutions/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == str(own_institution.id)

    update_response = api.patch(
        f"/api/v1/institutions/{own_institution.id}/",
        {"phone": "0700111222"},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["phone"] == "0700111222"

    hidden_response = api.get(f"/api/v1/institutions/{other_institution.id}/")
    assert hidden_response.status_code == 404

    create_response = api.post(
        "/api/v1/institutions/",
        {"name": "New SACCO", "code": "new-sacco", "currency": "UGX", "status": "active"},
        format="json",
    )
    assert create_response.status_code == 403

    delete_response = api.delete(f"/api/v1/institutions/{own_institution.id}/")
    assert delete_response.status_code == 403


@pytest.mark.django_db
def test_institutions_support_status_filtering_and_unique_codes():
    user = create_user(
        email="super2@example.com",
        username="super2",
        role="super_admin",
    )
    active = Institution.objects.create(name="Active SACCO", code="active-sacco")
    Institution.objects.create(
        name="Inactive SACCO",
        code="inactive-sacco",
        status="inactive",
    )
    api = APIClient()
    api.force_authenticate(user=user)

    filtered = api.get("/api/v1/institutions/?status=active")
    assert filtered.status_code == 200
    assert filtered.data["count"] == 1
    assert filtered.data["results"][0]["id"] == str(active.id)

    duplicate = api.post(
        "/api/v1/institutions/",
        {"name": "Duplicate", "code": "ACTIVE SACCO", "currency": "UGX", "status": "active"},
        format="json",
    )
    assert duplicate.status_code == 400
    assert duplicate.data["errors"]["code"] == ["An institution with this code already exists."]


@pytest.mark.django_db
def test_super_admin_can_crud_branches_with_useful_display_fields():
    institution = Institution.objects.create(name="Delta SACCO", code="delta")
    user = create_user(
        email="super3@example.com",
        username="super3",
        role="super_admin",
    )
    api = APIClient()
    api.force_authenticate(user=user)

    create_response = api.post(
        "/api/v1/branches/",
        {
            "institution": str(institution.id),
            "name": "Main Branch",
            "code": "MAIN BRANCH",
            "address": "Kampala Road",
            "status": "active",
        },
        format="json",
    )

    assert create_response.status_code == 201
    branch_id = create_response.data["id"]
    assert create_response.data["code"] == "main-branch"
    assert create_response.data["institution_name"] == "Delta SACCO"
    assert create_response.data["institution_code"] == "delta"
    assert create_response.data["display_name"] == "DELTA / Main Branch"

    update_response = api.patch(
        f"/api/v1/branches/{branch_id}/",
        {"status": "inactive"},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["status"] == "inactive"

    delete_response = api.delete(f"/api/v1/branches/{branch_id}/")
    assert delete_response.status_code == 204
    assert not Branch.objects.filter(pk=branch_id).exists()


@pytest.mark.django_db
def test_institution_admin_branch_access_is_scoped_to_own_institution():
    own_institution = Institution.objects.create(name="Own Coop", code="own-coop")
    own_branch = Branch.objects.create(
        institution=own_institution,
        name="Own Branch",
        code="own-branch",
    )
    other_institution = Institution.objects.create(name="Other Coop", code="other-coop")
    other_branch = Branch.objects.create(
        institution=other_institution,
        name="Other Branch",
        code="other-branch",
    )
    user = create_user(
        email="inst-admin@example.com",
        username="inst-admin",
        role="institution_admin",
        institution=own_institution,
    )
    api = APIClient()
    api.force_authenticate(user=user)

    list_response = api.get("/api/v1/branches/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
    assert list_response.data["results"][0]["id"] == str(own_branch.id)

    create_response = api.post(
        "/api/v1/branches/",
        {
            "institution": str(other_institution.id),
            "name": "Blocked Branch",
            "code": "blocked",
            "address": "",
            "status": "active",
        },
        format="json",
    )
    assert create_response.status_code == 403

    hidden_response = api.get(f"/api/v1/branches/{other_branch.id}/")
    assert hidden_response.status_code == 404

    update_response = api.patch(
        f"/api/v1/branches/{own_branch.id}/",
        {"address": "New address"},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["address"] == "New address"


@pytest.mark.django_db
def test_branches_support_status_filtering_and_unique_codes_per_institution():
    institution = Institution.objects.create(name="Scoped SACCO", code="scoped")
    other_institution = Institution.objects.create(name="Open SACCO", code="open")
    Branch.objects.create(
        institution=institution,
        name="Active Branch",
        code="branch-a",
        status="active",
    )
    Branch.objects.create(
        institution=institution,
        name="Inactive Branch",
        code="branch-b",
        status="inactive",
    )
    user = create_user(
        email="super4@example.com",
        username="super4",
        role="super_admin",
    )
    api = APIClient()
    api.force_authenticate(user=user)

    filtered = api.get(f"/api/v1/branches/?institution={institution.id}&status=active")
    assert filtered.status_code == 200
    assert filtered.data["count"] == 1
    assert filtered.data["results"][0]["name"] == "Active Branch"

    duplicate = api.post(
        "/api/v1/branches/",
        {
            "institution": str(institution.id),
            "name": "Duplicate Branch",
            "code": "BRANCH-A",
            "address": "",
            "status": "active",
        },
        format="json",
    )
    assert duplicate.status_code == 400
    assert duplicate.data["errors"]["code"] == [
        "A branch with this code already exists for that institution."
    ]

    allowed_other_institution = api.post(
        "/api/v1/branches/",
        {
            "institution": str(other_institution.id),
            "name": "Duplicate Code Elsewhere",
            "code": "BRANCH-A",
            "address": "",
            "status": "active",
        },
        format="json",
    )
    assert allowed_other_institution.status_code == 201


@pytest.mark.django_db
def test_non_admin_users_cannot_manage_institutions_or_branches():
    institution = Institution.objects.create(name="Denied SACCO", code="denied")
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
    api = APIClient()
    api.force_authenticate(user=user)

    institution_response = api.get("/api/v1/institutions/")
    branch_response = api.get("/api/v1/branches/")

    assert institution_response.status_code == 403
    assert branch_response.status_code == 403
