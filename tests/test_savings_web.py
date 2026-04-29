from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient
from django.urls import reverse

from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.savings.models import SavingsAccount
from apps.savings.services import SavingsService


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
        "first_name": "Amina",
        "last_name": "Nakato",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


@pytest.mark.django_db
def test_savings_web_list_and_detail_show_modals_and_transaction_history():
    institution = Institution.objects.create(name="Web SACCO", code="web")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@web.test",
        username="web-teller",
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
        reference="WEB-DEP-1",
    )
    SavingsService.withdraw(
        account=account,
        amount=Decimal("50.00"),
        performed_by=teller,
        reference="WEB-WIT-1",
    )

    web_client = DjangoClient()
    web_client.force_login(teller)

    list_response = web_client.get(reverse("savings_web:account-list"))
    assert list_response.status_code == 200
    assert account.account_number.encode() in list_response.content
    assert client.member_number.encode() in list_response.content

    detail_response = web_client.get(
        reverse("savings_web:account-detail", kwargs={"pk": account.pk})
    )
    assert detail_response.status_code == 200
    assert b"deposit-modal" in detail_response.content
    assert b"withdraw-modal" in detail_response.content
    assert b"Transaction history" in detail_response.content
    assert b"WEB-DEP-1" in detail_response.content
    assert b"WEB-WIT-1" in detail_response.content


@pytest.mark.django_db
def test_savings_web_forms_submit_successfully_and_block_client_cash_actions():
    institution = Institution.objects.create(name="Desk SACCO", code="desk")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    teller = create_user(
        email="teller@desk.test",
        username="desk-teller",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client_user = create_user(
        email="client@desk.test",
        username="desk-client",
        role="client",
        institution=institution,
        branch=branch,
    )
    member = create_client(institution=institution, branch=branch, user=client_user)
    account = SavingsAccount.objects.create(client=member)

    web_client = DjangoClient()
    web_client.force_login(teller)

    deposit_response = web_client.post(
        reverse("savings_web:account-deposit", kwargs={"pk": account.pk}),
        {"amount": "75.00", "reference": "FORM-DEP-1", "notes": "Desk cash-in"},
        follow=True,
    )
    assert deposit_response.status_code == 200

    withdrawal_response = web_client.post(
        reverse("savings_web:account-withdraw", kwargs={"pk": account.pk}),
        {"amount": "25.00", "reference": "FORM-WIT-1", "notes": "Desk cash-out"},
        follow=True,
    )
    assert withdrawal_response.status_code == 200

    account.refresh_from_db()
    assert account.balance == Decimal("50.00")
    assert b"FORM-DEP-1" in withdrawal_response.content
    assert b"FORM-WIT-1" in withdrawal_response.content

    client_browser = DjangoClient()
    client_browser.force_login(client_user)
    blocked_response = client_browser.post(
        reverse("savings_web:account-deposit", kwargs={"pk": account.pk}),
        {"amount": "10.00", "reference": "BLOCKED-WEB"},
    )
    assert blocked_response.status_code == 403
