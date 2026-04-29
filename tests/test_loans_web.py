from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient
from django.urls import reverse

from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanProduct
from apps.loans.services import LoanService


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
        "first_name": "Maria",
        "last_name": "Kato",
        "phone": "0700000000",
        "status": "active",
    }
    payload.update(overrides)
    return Client.objects.create(**payload)


@pytest.mark.django_db
def test_loan_web_pages_render_products_applications_and_disbursed_schedule():
    institution = Institution.objects.create(name="Web Loans SACCO", code="web-loans")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    officer = create_user(
        email="officer@web-loans.test",
        username="web-loans-officer",
        role="loan_officer",
        institution=institution,
        branch=branch,
    )
    teller = create_user(
        email="teller@web-loans.test",
        username="web-loans-teller",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch)
    product = LoanProduct.objects.create(
        institution=institution,
        name="Agri Grow",
        code="agri-grow",
        min_amount=Decimal("200.00"),
        max_amount=Decimal("4000.00"),
        annual_interest_rate=Decimal("12.00"),
        min_term_months=3,
        max_term_months=18,
    )
    loan = LoanApplication.objects.create(
        client=client,
        product=product,
        amount=Decimal("900.00"),
        term_months=6,
        purpose="Farm inputs",
    )
    LoanService.approve(loan=loan, user=officer)
    LoanService.disburse(loan=loan, user=teller, reference="WEB-DISB-1")

    browser = DjangoClient()
    browser.force_login(officer)

    products_page = browser.get(reverse("loans_web:product-list"))
    assert products_page.status_code == 200
    assert b"Agri Grow" in products_page.content
    assert b"agri-grow" in products_page.content

    applications_page = browser.get(reverse("loans_web:application-list"))
    assert applications_page.status_code == 200
    assert client.member_number.encode() in applications_page.content
    assert b"Open detail" in applications_page.content

    detail_page = browser.get(reverse("loans_web:application-detail", kwargs={"pk": loan.pk}))
    assert detail_page.status_code == 200
    assert b"Repayment schedule" in detail_page.content
    assert b"Disbursed" in detail_page.content or b"disbursed" in detail_page.content

    teller_browser = DjangoClient()
    teller_browser.force_login(teller)
    teller_detail_page = teller_browser.get(
        reverse("loans_web:application-detail", kwargs={"pk": loan.pk})
    )
    assert teller_detail_page.status_code == 200
    assert b"Record repayment" in teller_detail_page.content


@pytest.mark.django_db
def test_loan_web_actions_approve_disburse_and_repay_and_block_unauthorized_users():
    institution = Institution.objects.create(name="Desk Loans SACCO", code="desk-loans")
    branch = Branch.objects.create(institution=institution, name="Main", code="main")
    officer = create_user(
        email="officer@desk-loans.test",
        username="desk-loans-officer",
        role="loan_officer",
        institution=institution,
        branch=branch,
    )
    teller = create_user(
        email="teller@desk-loans.test",
        username="desk-loans-teller",
        role="teller",
        institution=institution,
        branch=branch,
    )
    client_user = create_user(
        email="client@desk-loans.test",
        username="desk-loans-client",
        role="client",
        institution=institution,
        branch=branch,
    )
    client = create_client(institution=institution, branch=branch, user=client_user)
    product = LoanProduct.objects.create(
        institution=institution,
        name="School Fees",
        code="school-fees",
        min_amount=Decimal("100.00"),
        max_amount=Decimal("3000.00"),
        annual_interest_rate=Decimal("10.00"),
        min_term_months=1,
        max_term_months=12,
    )
    loan = LoanApplication.objects.create(
        client=client,
        product=product,
        amount=Decimal("600.00"),
        term_months=6,
        purpose="Tuition",
    )

    officer_browser = DjangoClient()
    officer_browser.force_login(officer)
    approve_response = officer_browser.post(
        reverse("loans_web:application-approve", kwargs={"pk": loan.pk}),
        follow=True,
    )
    assert approve_response.status_code == 200
    loan.refresh_from_db()
    assert loan.status == LoanApplication.Status.APPROVED
    assert b"Loan approved" in approve_response.content

    teller_browser = DjangoClient()
    teller_browser.force_login(teller)
    disburse_response = teller_browser.post(
        reverse("loans_web:application-disburse", kwargs={"pk": loan.pk}),
        {"reference": "WEB-DISB-2"},
        follow=True,
    )
    assert disburse_response.status_code == 200
    loan.refresh_from_db()
    assert loan.status == LoanApplication.Status.DISBURSED
    assert b"Loan disbursed" in disburse_response.content

    repay_response = teller_browser.post(
        reverse("loans_web:application-repay", kwargs={"pk": loan.pk}),
        {"amount": "100.00", "reference": "WEB-REP-1"},
        follow=True,
    )
    assert repay_response.status_code == 200
    loan.refresh_from_db()
    assert loan.principal_balance < Decimal("600.00")
    assert b"Repayment recorded" in repay_response.content

    client_browser = DjangoClient()
    client_browser.force_login(client_user)
    blocked_response = client_browser.post(
        reverse("loans_web:application-approve", kwargs={"pk": loan.pk}),
        follow=False,
    )
    assert blocked_response.status_code == 403
