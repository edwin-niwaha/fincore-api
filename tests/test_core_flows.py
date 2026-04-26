import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.clients.models import Client
from apps.institutions.models import Branch, Institution
from apps.savings.models import SavingsAccount
from apps.savings.services import SavingsService
from apps.loans.models import LoanApplication, LoanProduct
from apps.loans.services import LoanService

@pytest.mark.django_db
def test_login_and_profile():
    User = get_user_model()
    user = User.objects.create_user(username="admin", password="Password123!", role="super_admin")
    api = APIClient()
    res = api.post("/api/auth/login/", {"username": "admin", "password": "Password123!"}, format="json")
    assert res.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
    profile = api.get("/api/auth/profile/")
    assert profile.status_code == 200
    assert profile.data["username"] == user.username

@pytest.mark.django_db
def test_savings_deposit_and_withdraw_prevents_negative_balance():
    User = get_user_model()
    inst = Institution.objects.create(name="Demo", code="demo")
    branch = Branch.objects.create(institution=inst, name="Main", code="main")
    staff = User.objects.create_user(username="teller", password="x", role="teller", institution=inst, branch=branch)
    client = Client.objects.create(institution=inst, branch=branch, first_name="Jane", last_name="Doe", phone="0700")
    account = SavingsAccount.objects.create(client=client)
    SavingsService.deposit(account=account, amount=100, performed_by=staff, reference="DEP-1")
    account.refresh_from_db()
    assert account.balance == Decimal("100.00")
    SavingsService.withdraw(account=account, amount=40, performed_by=staff, reference="WIT-1")
    account.refresh_from_db()
    assert account.balance == Decimal("60.00")
    with pytest.raises(Exception):
        SavingsService.withdraw(account=account, amount=100, performed_by=staff, reference="WIT-2")

@pytest.mark.django_db
def test_loan_approval_disbursement_and_repayment():
    User = get_user_model()
    inst = Institution.objects.create(name="Demo", code="demo")
    branch = Branch.objects.create(institution=inst, name="Main", code="main")
    officer = User.objects.create_user(username="officer", password="x", role="loan_officer", institution=inst, branch=branch)
    client = Client.objects.create(institution=inst, branch=branch, first_name="John", last_name="Doe", phone="0701")
    product = LoanProduct.objects.create(institution=inst, name="Small Loan", code="small", min_amount=100, max_amount=1000, annual_interest_rate=12, min_term_months=1, max_term_months=12)
    loan = LoanApplication.objects.create(client=client, product=product, amount=600, term_months=6)
    LoanService.approve(loan=loan, user=officer)
    LoanService.disburse(loan=loan, user=officer, reference="DISB-1")
    loan.refresh_from_db()
    assert loan.status == "disbursed"
    repayment = LoanService.repay(loan=loan, amount=100, reference="REP-1", received_by=officer)
    assert repayment.amount == Decimal("100.00")
