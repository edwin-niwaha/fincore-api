from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.clients.models import Client, ClientMemberSequence
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
):
    return User.objects.create_user(
        email=email,
        username=username,
        password=password,
        role=role,
        institution=institution,
        branch=branch,
    )


def auth_client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def jwt_client(user, *, password="Password123!"):
    api = APIClient()
    login_response = api.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": password},
        format="json",
    )
    assert login_response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['tokens']['access']}")
    return api


def client_payload(*, institution, branch, **overrides):
    payload = {
        "institution": str(institution.id),
        "branch": str(branch.id),
        "first_name": "Jane",
        "last_name": "Doe",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return payload


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
def test_clients_crud_requires_jwt_and_accepts_bearer_tokens():
    institution = Institution.objects.create(name="Alpha SACCO", code="alpha")
    branch = Branch.objects.create(institution=institution, name="Main Branch", code="main")
    staff_user = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )

    unauthenticated_api = APIClient()
    list_response = unauthenticated_api.get("/api/v1/clients/")
    assert list_response.status_code == 401

    create_response = unauthenticated_api.post(
        "/api/v1/clients/",
        client_payload(institution=institution, branch=branch),
        format="json",
    )
    assert create_response.status_code == 401

    authenticated_api = jwt_client(staff_user)
    authenticated_response = authenticated_api.get("/api/v1/clients/")
    assert authenticated_response.status_code == 200
    assert authenticated_response.data["count"] == 0


@pytest.mark.django_db
def test_staff_can_create_list_filter_update_and_delete_clients():
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
    staff_user = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    api = jwt_client(staff_user)

    create_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=institution,
            branch=main_branch,
            first_name="Jane",
            last_name="Ayo",
            phone="0700000001",
            email="JANE@EXAMPLE.COM",
            national_id="CF-001",
            gender="female",
        ),
        format="json",
    )
    assert create_response.status_code == 201
    created_client_id = create_response.data["id"]
    assert create_response.data["member_number"] == "MAIN-000001"
    assert create_response.data["email"] == "jane@example.com"
    assert create_response.data["gender"] == "female"

    second_client = create_client(
        institution=institution,
        branch=main_branch,
        first_name="John",
        last_name="Zulu",
        phone="0700000002",
        status="inactive",
    )
    third_client = create_client(
        institution=institution,
        branch=north_branch,
        first_name="Martha",
        last_name="Bena",
        phone="0700000003",
        status="active",
    )

    list_response = api.get("/api/v1/clients/?page=1&page_size=2&ordering=member_number")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 3
    assert len(list_response.data["results"]) == 2
    assert list_response.data["results"][0]["id"] == created_client_id

    retrieve_response = api.get(f"/api/v1/clients/{created_client_id}/")
    assert retrieve_response.status_code == 200
    assert retrieve_response.data["full_name"] == "Jane Ayo"

    filtered_response = api.get("/api/v1/clients/?status=inactive")
    assert filtered_response.status_code == 200
    assert filtered_response.data["count"] == 1
    assert filtered_response.data["results"][0]["id"] == str(second_client.id)

    update_response = api.patch(
        f"/api/v1/clients/{created_client_id}/",
        {
            "status": "blacklisted",
            "gender": "other",
            "address": "Kampala Road",
        },
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["status"] == "blacklisted"
    assert update_response.data["gender"] == "other"
    assert update_response.data["address"] == "Kampala Road"

    blacklisted_response = api.get("/api/v1/clients/?status=blacklisted")
    assert blacklisted_response.status_code == 200
    assert blacklisted_response.data["count"] == 1
    assert blacklisted_response.data["results"][0]["id"] == created_client_id

    delete_response = api.delete(f"/api/v1/clients/{third_client.id}/")
    assert delete_response.status_code == 204
    assert not Client.objects.filter(pk=third_client.id).exists()


@pytest.mark.django_db
def test_clients_search_matches_name_phone_email_and_national_id():
    institution = Institution.objects.create(name="Search SACCO", code="search")
    branch = Branch.objects.create(institution=institution, name="Main Branch", code="main")
    staff_user = create_user(
        email="manager@example.com",
        username="manager",
        role="branch_manager",
        institution=institution,
        branch=branch,
    )
    api = auth_client(staff_user)

    target_client = create_client(
        institution=institution,
        branch=branch,
        first_name="Amina",
        last_name="Nabirye",
        phone="0700123456",
        email="amina@example.com",
        national_id="CF-12345",
    )
    create_client(
        institution=institution,
        branch=branch,
        first_name="Ruth",
        last_name="Kato",
        phone="0700999000",
        email="ruth@example.com",
        national_id="CF-99999",
    )

    for search_term in (
        "Amina Nabirye",
        "0700123456",
        "AMINA@EXAMPLE.COM",
        "cf-12345",
    ):
        response = api.get("/api/v1/clients/", {"search": search_term})
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(target_client.id)


@pytest.mark.django_db
def test_client_validation_rejects_invalid_scope_and_future_date_of_birth():
    own_institution = Institution.objects.create(name="Own SACCO", code="own")
    other_institution = Institution.objects.create(name="Other SACCO", code="other")
    own_branch = Branch.objects.create(
        institution=own_institution,
        name="Own Branch",
        code="own-branch",
    )
    other_branch = Branch.objects.create(
        institution=other_institution,
        name="Other Branch",
        code="other-branch",
    )
    staff_user = create_user(
        email="super@example.com",
        username="super",
        role="super_admin",
    )
    api = auth_client(staff_user)

    mismatched_branch_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=own_institution,
            branch=other_branch,
            first_name="Mismatch",
            phone="0700000100",
        ),
        format="json",
    )
    assert mismatched_branch_response.status_code == 400
    assert "branch" in mismatched_branch_response.data["errors"]

    future_dob_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=own_institution,
            branch=own_branch,
            first_name="Future",
            phone="0700000101",
            date_of_birth=(date.today() + timedelta(days=1)).isoformat(),
        ),
        format="json",
    )
    assert future_dob_response.status_code == 400
    assert "date_of_birth" in future_dob_response.data["errors"]

    blank_phone_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=own_institution,
            branch=own_branch,
            first_name="Blank",
            phone="   ",
        ),
        format="json",
    )
    assert blank_phone_response.status_code == 400
    assert "phone" in blank_phone_response.data["errors"]


@pytest.mark.django_db
def test_staff_scope_is_limited_to_allowed_institution_and_branch_clients():
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

    own_client = create_client(
        institution=own_institution,
        branch=own_branch,
        first_name="Own",
        last_name="Client",
        phone="0700000200",
    )
    sister_client = create_client(
        institution=own_institution,
        branch=sister_branch,
        first_name="Sister",
        last_name="Client",
        phone="0700000201",
    )
    other_client = create_client(
        institution=other_institution,
        branch=other_branch,
        first_name="Other",
        last_name="Client",
        phone="0700000202",
    )

    admin_api = auth_client(institution_admin)
    admin_list_response = admin_api.get("/api/v1/clients/")
    assert admin_list_response.status_code == 200
    admin_ids = {row["id"] for row in admin_list_response.data["results"]}
    assert str(own_client.id) in admin_ids
    assert str(sister_client.id) in admin_ids
    assert str(other_client.id) not in admin_ids

    admin_hidden_response = admin_api.get(f"/api/v1/clients/{other_client.id}/")
    assert admin_hidden_response.status_code == 404

    admin_blocked_create_response = admin_api.post(
        "/api/v1/clients/",
        client_payload(
            institution=other_institution,
            branch=other_branch,
            first_name="Blocked",
            phone="0700000203",
        ),
        format="json",
    )
    assert admin_blocked_create_response.status_code == 403

    branch_api = auth_client(branch_manager)
    branch_list_response = branch_api.get("/api/v1/clients/")
    assert branch_list_response.status_code == 200
    assert branch_list_response.data["count"] == 1
    assert branch_list_response.data["results"][0]["id"] == str(own_client.id)

    branch_hidden_response = branch_api.get(f"/api/v1/clients/{sister_client.id}/")
    assert branch_hidden_response.status_code == 404

    branch_blocked_create_response = branch_api.post(
        "/api/v1/clients/",
        client_payload(
            institution=own_institution,
            branch=sister_branch,
            first_name="Blocked",
            phone="0700000204",
        ),
        format="json",
    )
    assert branch_blocked_create_response.status_code == 403


@pytest.mark.django_db
def test_non_staff_roles_cannot_manage_client_endpoints():
    institution = Institution.objects.create(name="Denied SACCO", code="denied")
    branch = Branch.objects.create(institution=institution, name="Denied Branch", code="branch")
    client_user = create_user(
        email="client@example.com",
        username="client",
        role="client",
        institution=institution,
        branch=branch,
    )
    managed_client = create_client(
        institution=institution,
        branch=branch,
        first_name="Managed",
        last_name="Client",
        phone="0700000300",
    )
    api = auth_client(client_user)

    list_response = api.get("/api/v1/clients/")
    assert list_response.status_code == 403

    create_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=institution,
            branch=branch,
            first_name="Blocked",
            phone="0700000301",
        ),
        format="json",
    )
    assert create_response.status_code == 403

    retrieve_response = api.get(f"/api/v1/clients/{managed_client.id}/")
    assert retrieve_response.status_code == 403

    update_response = api.patch(
        f"/api/v1/clients/{managed_client.id}/",
        {"status": "inactive"},
        format="json",
    )
    assert update_response.status_code == 403

    delete_response = api.delete(f"/api/v1/clients/{managed_client.id}/")
    assert delete_response.status_code == 403


@pytest.mark.django_db
def test_staff_can_discover_linkable_client_users_with_scope_controls():
    institution = Institution.objects.create(name="Scoped SACCO", code="scoped")
    main_branch = Branch.objects.create(
        institution=institution,
        name="Main Branch",
        code="main",
    )
    sister_branch = Branch.objects.create(
        institution=institution,
        name="Sister Branch",
        code="sister",
    )
    other_institution = Institution.objects.create(name="Other SACCO", code="other")
    other_branch = Branch.objects.create(
        institution=other_institution,
        name="Other Branch",
        code="other-branch",
    )
    teller = create_user(
        email="teller@scoped.test",
        username="scoped-teller",
        role="teller",
        institution=institution,
        branch=main_branch,
    )
    branch_client_user = create_user(
        email="branch-client@example.com",
        username="branch-client",
        role="client",
        institution=institution,
        branch=main_branch,
    )
    linked_client_user = create_user(
        email="linked-client@example.com",
        username="linked-client",
        role="client",
        institution=institution,
        branch=main_branch,
    )
    linked_client = create_client(
        institution=institution,
        branch=main_branch,
        first_name="Linked",
        last_name="Client",
        phone="0700000302",
        user=linked_client_user,
    )
    create_user(
        email="sister-client@example.com",
        username="sister-client",
        role="client",
        institution=institution,
        branch=sister_branch,
    )
    create_user(
        email="outside-client@example.com",
        username="outside-client",
        role="client",
        institution=other_institution,
        branch=other_branch,
    )
    unassigned_client_user = create_user(
        email="floating-client@example.com",
        username="floating-client",
        role="client",
    )
    create_user(
        email="staff@example.com",
        username="staff-user",
        role="loan_officer",
        institution=institution,
        branch=main_branch,
    )

    api = auth_client(teller)

    list_response = api.get("/api/v1/clients/linkable-users/")
    assert list_response.status_code == 200
    listed_ids = {row["id"] for row in list_response.data["results"]}
    assert branch_client_user.id in listed_ids
    assert linked_client_user.id not in listed_ids

    linked_response = api.get(
        "/api/v1/clients/linkable-users/",
        {"client": str(linked_client.id)},
    )
    assert linked_response.status_code == 200
    linked_ids = {row["id"] for row in linked_response.data["results"]}
    assert linked_client_user.id in linked_ids

    search_response = api.get(
        "/api/v1/clients/linkable-users/",
        {"search": "floating-client@example.com"},
    )
    assert search_response.status_code == 200
    assert search_response.data["count"] == 1
    assert search_response.data["results"][0]["id"] == unassigned_client_user.id


@pytest.mark.django_db
def test_linking_client_user_updates_scope_and_audit_fields():
    institution = Institution.objects.create(name="Link SACCO", code="link")
    branch = Branch.objects.create(institution=institution, name="Main Branch", code="main")
    staff_user = create_user(
        email="manager@link.test",
        username="link-manager",
        role="branch_manager",
        institution=institution,
        branch=branch,
    )
    client_user = create_user(
        email="portal@example.com",
        username="portal-user",
        role="client",
    )
    api = auth_client(staff_user)

    create_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=institution,
            branch=branch,
            user=str(client_user.id),
            first_name="Portal",
            last_name="Member",
        ),
        format="json",
    )
    assert create_response.status_code == 201
    assert create_response.data["user_email"] == client_user.email
    assert create_response.data["created_by"] == staff_user.id
    assert create_response.data["updated_by"] == staff_user.id

    created_client = Client.objects.get(pk=create_response.data["id"])
    client_user.refresh_from_db()
    assert created_client.created_by == staff_user
    assert created_client.updated_by == staff_user
    assert client_user.institution == institution
    assert client_user.branch == branch

    duplicate_response = api.post(
        "/api/v1/clients/",
        client_payload(
            institution=institution,
            branch=branch,
            user=str(client_user.id),
            first_name="Duplicate",
            phone="0700000304",
        ),
        format="json",
    )
    assert duplicate_response.status_code == 400
    assert "user" in duplicate_response.data["errors"]


@pytest.mark.django_db
def test_clients_me_is_client_only_and_tracks_self_service_updates():
    institution = Institution.objects.create(name="Self SACCO", code="self")
    branch = Branch.objects.create(institution=institution, name="Main Branch", code="main")
    staff_user = create_user(
        email="manager@self.test",
        username="self-manager",
        role="branch_manager",
        institution=institution,
        branch=branch,
    )
    client_user = create_user(
        email="member@self.test",
        username="self-member",
        role="client",
        institution=institution,
        branch=branch,
    )
    client = create_client(
        institution=institution,
        branch=branch,
        user=client_user,
        first_name="Self",
        last_name="Member",
        phone="0700000305",
        created_by=staff_user,
        updated_by=staff_user,
    )

    api = auth_client(client_user)
    retrieve_response = api.get("/api/v1/clients/me/")
    assert retrieve_response.status_code == 200
    assert retrieve_response.data["id"] == str(client.id)

    update_response = api.patch(
        "/api/v1/clients/me/",
        {
            "phone": "0700000999",
            "address": "Kampala Road",
            "email": "member-updated@self.test",
        },
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["phone"] == "0700000999"
    assert update_response.data["address"] == "Kampala Road"
    assert update_response.data["email"] == "member-updated@self.test"
    assert update_response.data["updated_by"] == client_user.id

    client.refresh_from_db()
    assert client.updated_by == client_user

    denied_response = auth_client(staff_user).get("/api/v1/clients/me/")
    assert denied_response.status_code == 403


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
        phone="0700000400",
    )
    second_client = create_client(
        institution=institution,
        branch=main_branch,
        first_name="Second",
        last_name="Main",
        phone="0700000401",
    )
    east_client = create_client(
        institution=institution,
        branch=east_branch,
        first_name="East",
        last_name="Client",
        phone="0700000402",
    )

    assert first_client.member_number == "MAIN-000001"
    assert second_client.member_number == "MAIN-000002"
    assert east_client.member_number == "EAST-000001"
    assert ClientMemberSequence.objects.get(branch=main_branch).last_value == 2
    assert ClientMemberSequence.objects.get(branch=east_branch).last_value == 1
