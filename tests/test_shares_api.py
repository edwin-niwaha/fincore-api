from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.notifications.models import Notification
from apps.shares.models import ShareAccount, ShareProduct, ShareTransaction


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
def test_share_product_management_is_scoped_and_role_restricted():
    institution_a = Institution.objects.create(name="Alpha Shares", code="alpha-shares")
    institution_b = Institution.objects.create(name="Beta Shares", code="beta-shares")
    accountant_a = create_user(
        email="accountant@alpha-shares.test",
        username="alpha-shares-accountant",
        role="accountant",
        institution=institution_a,
    )
    teller_a = create_user(
        email="teller@alpha-shares.test",
        username="alpha-shares-teller",
        role="teller",
        institution=institution_a,
    )

    accountant_api = APIClient()
    accountant_api.force_authenticate(user=accountant_a)
    teller_api = APIClient()
    teller_api.force_authenticate(user=teller_a)

    blocked_teller_create = teller_api.post(
        "/api/v1/shares/products/",
        {
            "institution": str(institution_a.id),
            "name": "Teller Blocked",
            "code": "teller-blocked",
            "nominal_price": "1000.00",
            "minimum_shares": 5,
        },
        format="json",
    )
    assert blocked_teller_create.status_code == 403

    blocked_cross_scope = accountant_api.post(
        "/api/v1/shares/products/",
        {
            "institution": str(institution_b.id),
            "name": "Cross Scope",
            "code": "cross-scope",
            "nominal_price": "1000.00",
            "minimum_shares": 5,
        },
        format="json",
    )
    assert blocked_cross_scope.status_code == 403

    created = accountant_api.post(
        "/api/v1/shares/products/",
        {
            "institution": str(institution_a.id),
            "name": "Member Capital",
            "code": "member-capital",
            "nominal_price": "1000.00",
            "minimum_shares": 5,
            "maximum_shares": 200,
            "status": "active",
        },
        format="json",
    )
    assert created.status_code == 201
    product_id = created.data["id"]
    assert created.data["institution_name"] == institution_a.name

    update_response = accountant_api.patch(
        f"/api/v1/shares/products/{product_id}/",
        {"status": "inactive"},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["status"] == "inactive"


@pytest.mark.django_db
def test_share_accounts_purchases_redemptions_and_history_work_with_auditability():
    institution = Institution.objects.create(name="Capital SACCO", code="capital")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    accountant = create_user(
        email="accountant@capital.test",
        username="capital-accountant",
        role="accountant",
        institution=institution,
        branch=branch,
    )
    client_user = create_user(
        email="client@capital.test",
        username="capital-client",
        role="client",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch, user=client_user)
    product = ShareProduct.objects.create(
        institution=institution,
        name="Share Capital",
        code="share-capital",
        nominal_price=Decimal("2500.00"),
        minimum_shares=5,
        maximum_shares=200,
    )

    api = APIClient()
    api.force_authenticate(user=accountant)

    account_response = api.post(
        "/api/v1/shares/accounts/",
        {"client": str(client.id), "product": str(product.id), "status": "active"},
        format="json",
    )
    assert account_response.status_code == 201
    account_id = account_response.data["id"]
    assert account_response.data["transaction_count"] == 0

    duplicate_account_response = api.post(
        "/api/v1/shares/accounts/",
        {"client": str(client.id), "product": str(product.id), "status": "active"},
        format="json",
    )
    assert duplicate_account_response.status_code == 400
    assert (
        "already has a share account"
        in duplicate_account_response.data["message"].lower()
    )

    purchase_response = api.post(
        f"/api/v1/shares/accounts/{account_id}/purchase/",
        {"shares": 20, "reference": "SHR-BUY-1", "notes": "Opening share purchase"},
        format="json",
    )
    assert purchase_response.status_code == 201
    assert purchase_response.data["amount"] == "50000.00"
    assert purchase_response.data["balance_after"] == 20
    assert purchase_response.data["status"] == "posted"

    redeem_response = api.post(
        f"/api/v1/shares/accounts/{account_id}/redeem/",
        {"shares": 5, "reference": "SHR-RED-1", "notes": "Client redemption"},
        format="json",
    )
    assert redeem_response.status_code == 201
    assert redeem_response.data["amount"] == "12500.00"
    assert redeem_response.data["balance_after"] == 15

    detail_response = api.get(f"/api/v1/shares/accounts/{account_id}/")
    assert detail_response.status_code == 200
    assert detail_response.data["shares"] == 15
    assert detail_response.data["total_value"] == "37500.00"
    assert detail_response.data["transaction_count"] == 2
    assert len(detail_response.data["recent_transactions"]) == 2

    history_response = api.get(
        f"/api/v1/shares/accounts/{account_id}/transactions/",
        {"type": "purchase", "search": "BUY"},
    )
    assert history_response.status_code == 200
    assert history_response.data["count"] == 1
    assert history_response.data["results"][0]["reference"] == "SHR-BUY-1"

    account = ShareAccount.objects.get(pk=account_id)
    assert account.shares == 15
    assert account.total_value == Decimal("37500.00")

    audit_actions = list(
        AuditLog.objects.filter(target=str(account.id))
        .order_by("created_at")
        .values_list("action", flat=True)
    )
    assert "shares.purchase" in audit_actions
    assert "shares.redeem" in audit_actions

    client_notifications = list(
        Notification.objects.filter(user=client_user).values_list("category", flat=True)
    )
    assert "share_purchase_recorded" in client_notifications
    assert "share_redemption_recorded" in client_notifications


@pytest.mark.django_db
def test_share_product_rules_and_status_rules_block_invalid_operations():
    institution = Institution.objects.create(name="Rules SACCO", code="rules")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    accountant = create_user(
        email="accountant@rules.test",
        username="rules-accountant",
        role="accountant",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    product = ShareProduct.objects.create(
        institution=institution,
        name="Rules Product",
        code="rules-product",
        nominal_price=Decimal("1000.00"),
        minimum_shares=10,
        maximum_shares=30,
    )
    account = ShareAccount.objects.create(client=client, product=product)

    api = APIClient()
    api.force_authenticate(user=accountant)

    below_min_purchase = api.post(
        f"/api/v1/shares/accounts/{account.id}/purchase/",
        {"shares": 5, "reference": "RULES-BUY-LOW"},
        format="json",
    )
    assert below_min_purchase.status_code == 400
    assert "product minimum of 10 shares" in below_min_purchase.data["message"].lower()

    valid_purchase = api.post(
        f"/api/v1/shares/accounts/{account.id}/purchase/",
        {"shares": 20, "reference": "RULES-BUY-OK"},
        format="json",
    )
    assert valid_purchase.status_code == 201

    above_max_purchase = api.post(
        f"/api/v1/shares/accounts/{account.id}/purchase/",
        {"shares": 15, "reference": "RULES-BUY-MAX"},
        format="json",
    )
    assert above_max_purchase.status_code == 400
    assert "product maximum of 30 shares" in above_max_purchase.data["message"].lower()

    below_min_redeem = api.post(
        f"/api/v1/shares/accounts/{account.id}/redeem/",
        {"shares": 15, "reference": "RULES-RED-LOW"},
        format="json",
    )
    assert below_min_redeem.status_code == 400
    assert "product minimum of 10 shares" in below_min_redeem.data["message"].lower()

    valid_redeem = api.post(
        f"/api/v1/shares/accounts/{account.id}/redeem/",
        {"shares": 20, "reference": "RULES-RED-CLOSE"},
        format="json",
    )
    assert valid_redeem.status_code == 201

    account.refresh_from_db()
    assert account.shares == 0
    assert account.total_value == Decimal("0.00")

    inactive_product = ShareProduct.objects.create(
        institution=institution,
        name="Inactive Product",
        code="inactive-product",
        nominal_price=Decimal("500.00"),
        minimum_shares=1,
        status="inactive",
    )
    inactive_client = create_client(
        institution=institution,
        branch=branch,
        first_name="Inactive",
        last_name="Client",
        status="inactive",
    )

    blocked_inactive_account = api.post(
        "/api/v1/shares/accounts/",
        {
            "client": str(inactive_client.id),
            "product": str(product.id),
            "status": "active",
        },
        format="json",
    )
    assert blocked_inactive_account.status_code == 400
    assert "Only active clients can open share accounts." in blocked_inactive_account.data["errors"]["client"]

    blocked_inactive_product = api.post(
        "/api/v1/shares/accounts/",
        {
            "client": str(client.id),
            "product": str(inactive_product.id),
            "status": "active",
        },
        format="json",
    )
    assert blocked_inactive_product.status_code == 400
    assert "Only active share products can be assigned to share accounts." in blocked_inactive_product.data["errors"]["product"]


@pytest.mark.django_db
def test_share_scope_duplicate_references_and_lifecycle_guards_are_enforced():
    institution = Institution.objects.create(name="Scope Shares", code="scope-shares")
    branch_a = Branch.objects.create(institution=institution, name="Main", code="main")
    branch_b = Branch.objects.create(institution=institution, name="North", code="north")
    accountant_a = create_user(
        email="accountant-a@scope-shares.test",
        username="scope-shares-a",
        role="accountant",
        institution=institution,
        branch=branch_a,
    )
    accountant_b = create_user(
        email="accountant-b@scope-shares.test",
        username="scope-shares-b",
        role="accountant",
        institution=institution,
        branch=branch_b,
    )
    client_a = create_client(institution=institution, branch=branch_a)
    client_b = create_client(institution=institution, branch=branch_b)
    product = ShareProduct.objects.create(
        institution=institution,
        name="Scoped Product",
        code="scoped-product",
        nominal_price=Decimal("1000.00"),
        minimum_shares=5,
    )
    account_a = ShareAccount.objects.create(client=client_a, product=product)
    account_b = ShareAccount.objects.create(client=client_b, product=product)

    api_a = APIClient()
    api_a.force_authenticate(user=accountant_a)

    blocked_detail = api_a.get(f"/api/v1/shares/accounts/{account_b.id}/")
    assert blocked_detail.status_code == 404

    blocked_purchase = api_a.post(
        f"/api/v1/shares/accounts/{account_b.id}/purchase/",
        {"shares": 10, "reference": "SCOPE-HIDDEN"},
        format="json",
    )
    assert blocked_purchase.status_code == 404

    first_purchase = api_a.post(
        f"/api/v1/shares/accounts/{account_a.id}/purchase/",
        {"shares": 10, "reference": "SCOPE-REF-1"},
        format="json",
    )
    assert first_purchase.status_code == 201

    duplicate_reference = api_a.post(
        f"/api/v1/shares/accounts/{account_a.id}/purchase/",
        {"shares": 10, "reference": "SCOPE-REF-1"},
        format="json",
    )
    assert duplicate_reference.status_code == 400
    assert "reference" in duplicate_reference.data["errors"]

    close_with_balance = api_a.patch(
        f"/api/v1/shares/accounts/{account_a.id}/",
        {"status": "closed"},
        format="json",
    )
    assert close_with_balance.status_code == 400
    assert "positive share balance cannot be closed" in close_with_balance.data["message"].lower()

    delete_with_history = api_a.delete(f"/api/v1/shares/accounts/{account_a.id}/")
    assert delete_with_history.status_code == 400
    assert "transaction history cannot be deleted" in delete_with_history.data["message"].lower()

    delete_product_with_account = api_a.delete(f"/api/v1/shares/products/{product.id}/")
    assert delete_product_with_account.status_code == 400
    assert "share products with share accounts cannot be deleted" in delete_product_with_account.data["message"].lower()

    account_a.refresh_from_db()
    assert account_a.shares == 10
    assert ShareTransaction.objects.filter(account=account_a).count() == 1
