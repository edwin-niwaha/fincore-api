from decimal import Decimal
from django.db import transaction
from rest_framework.exceptions import ValidationError
from apps.audit.services import AuditService
from apps.transactions.models import Transaction
from .models import SavingsTransaction

class SavingsService:
    @staticmethod
    @transaction.atomic
    def deposit(*, account, amount, performed_by=None, reference, notes=""):
        account = type(account).objects.select_for_update().select_related("client__institution", "client__branch").get(pk=account.pk)
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("Deposit amount must be positive.")
        account.balance += amount
        account.save(update_fields=["balance", "updated_at"])
        tx = SavingsTransaction.objects.create(account=account, type="deposit", amount=amount, balance_after=account.balance, reference=reference, performed_by=performed_by, notes=notes)
        Transaction.objects.create(institution=account.client.institution, branch=account.client.branch, client=account.client, category="savings", direction="credit", amount=amount, reference=reference, description="Savings deposit", created_by=performed_by)
        AuditService.log(user=performed_by, action="savings.deposit", target=str(account.id), metadata={"amount": str(amount), "reference": reference})
        return tx

    @staticmethod
    @transaction.atomic
    def withdraw(*, account, amount, performed_by=None, reference, notes=""):
        account = type(account).objects.select_for_update().select_related("client__institution", "client__branch").get(pk=account.pk)
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("Withdrawal amount must be positive.")
        if account.balance < amount:
            raise ValidationError("Insufficient savings balance.")
        account.balance -= amount
        account.save(update_fields=["balance", "updated_at"])
        tx = SavingsTransaction.objects.create(account=account, type="withdrawal", amount=amount, balance_after=account.balance, reference=reference, performed_by=performed_by, notes=notes)
        Transaction.objects.create(institution=account.client.institution, branch=account.client.branch, client=account.client, category="savings", direction="debit", amount=amount, reference=reference, description="Savings withdrawal", created_by=performed_by)
        AuditService.log(user=performed_by, action="savings.withdraw", target=str(account.id), metadata={"amount": str(amount), "reference": reference})
        return tx
