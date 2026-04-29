import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


def create_user(*, email, username, password="Password123!", role="super_admin"):
    return get_user_model().objects.create_user(
        email=email,
        username=username,
        password=password,
        role=role,
    )


@pytest.mark.django_db
def test_api_v1_schema_and_docs_are_available():
    api = APIClient()

    schema = api.get("/api/v1/schema/")
    docs = api.get("/api/v1/docs/")
    legacy_schema = api.get("/api/schema/")
    legacy_docs = api.get("/api/docs/")

    assert schema.status_code == 200
    assert docs.status_code == 200
    assert legacy_schema.status_code == 302
    assert legacy_schema["Location"].endswith("/api/v1/schema/")
    assert legacy_docs.status_code == 302
    assert legacy_docs["Location"].endswith("/api/v1/docs/")


@pytest.mark.django_db
def test_login_validation_errors_use_standard_error_shape():
    api = APIClient()
    response = api.post(
        "/api/v1/auth/login/",
        {"password": "Password123!"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["message"] == "This field is required."
    assert response.data["status"] == 400
    assert response.data["status_code"] == 400
    assert response.data["code"] == "required"
    assert response.data["errors"] == {"email": ["This field is required."]}
    assert response.data["path"] == "/api/v1/auth/login/"


@pytest.mark.django_db
def test_login_authentication_errors_use_standard_error_shape():
    create_user(email="admin@example.com", username="admin")

    api = APIClient()
    response = api.post(
        "/api/v1/auth/login/",
        {"email": "admin@example.com", "password": "WrongPassword123!"},
        format="json",
    )

    assert response.status_code == 401
    assert response.data["message"] == "Invalid email or password."
    assert response.data["status"] == 401
    assert response.data["status_code"] == 401
    assert response.data["code"] == "authentication_failed"
    assert response.data["errors"] == {}
    assert response.data["path"] == "/api/v1/auth/login/"


@pytest.mark.django_db
def test_users_endpoint_is_paginated_under_api_v1():
    manager = create_user(email="manager@example.com", username="manager")
    create_user(email="user1@example.com", username="user1", role="teller")
    create_user(email="user2@example.com", username="user2", role="teller")
    create_user(email="user3@example.com", username="user3", role="teller")

    api = APIClient()
    api.force_authenticate(user=manager)

    response = api.get("/api/v1/users/?page_size=2")

    assert response.status_code == 200
    assert response.data["count"] == 4
    assert len(response.data["results"]) == 2
    assert "next" in response.data
    assert "previous" in response.data
