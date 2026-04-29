from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.accounting.services import AccountingPostingService
from apps.audit.services import AuditService
from apps.common.models import StatusChoices
from apps.transactions.models import Transaction
from apps.transactions.services import TransactionLedgerService

from .models import SavingsAccount, SavingsTransaction

ZERO_DECIMAL = Decimal("0.00")


class SavingsService:
    @staticmethod
    def _normalize_amount(amount):
        normalized_amount = Decimal(str(amount))
        if normalized_amount <= ZERO_DECIMAL:
            raise ValidationError("Amount must be greater than zero.")
        return normalized_amount

    @staticmethod
    def _normalize_reference(reference):
        normalized_reference = str(reference).strip()
        if not normalized_reference:
            raise ValidationError({"reference": ["Reference is required."]})
        return normalized_reference

    @classmethod
    def _validate_account_state(cls, account):
        if account.status != StatusChoices.ACTIVE:
            raise ValidationError("Only active savings accounts can process transactions.")

    @classmethod
    def _ensure_reference_available(cls, reference):
        if SavingsTransaction.objects.filter(reference__iexact=reference).exists():
            raise ValidationError(
                {"reference": ["A savings transaction with this reference exists."]}
            )

        if Transaction.objects.filter(reference__iexact=reference).exists():
            raise ValidationError(
                {"reference": ["A transaction with this reference already exists."]}
            )

    @staticmethod
    def _duplicate_reference_error():
        return ValidationError({"reference": ["A transaction with this reference already exists."]})

    @classmethod
    @transaction.atomic
    def deposit(cls, *, account, amount, performed_by=None, reference, notes=""):
        account = (
            SavingsAccount.objects.select_for_update()
            .select_related("client__institution", "client__branch")
            .get(pk=account.pk)
        )
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        notes = str(notes).strip()
        cls._validate_account_state(account)
        cls._ensure_reference_available(reference)

        account.balance += amount
        account.save(update_fields=["balance", "updated_at"])

        try:
            savings_transaction = SavingsTransaction.objects.create(
                account=account,
                type=SavingsTransaction.Type.DEPOSIT,
                amount=amount,
                balance_after=account.balance,
                reference=reference,
                performed_by=performed_by,
                notes=notes,
            )
            TransactionLedgerService.record(
                institution=account.client.institution,
                branch=account.client.branch,
                client=account.client,
                category=Transaction.Category.SAVINGS_DEPOSIT,
                direction=Transaction.Direction.CREDIT,
                amount=amount,
                reference=reference,
                description=f"Savings deposit to {account.account_number}",
                created_by=performed_by,
            )
            AccountingPostingService.post_savings_deposit(
                account=account,
                amount=amount,
                reference=reference,
                posted_by=performed_by,
            )
        except IntegrityError as exc:
            raise cls._duplicate_reference_error() from exc

        AuditService.log(
            user=performed_by,
            action="savings.deposit",
            target=str(account.id),
            metadata={
                "account_number": account.account_number,
                "amount": str(amount),
                "reference": reference,
            },
        )
        return savings_transaction

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, account, amount, performed_by=None, reference, notes=""):
        account = (
            SavingsAccount.objects.select_for_update()
            .select_related("client__institution", "client__branch")
            .get(pk=account.pk)
        )
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        notes = str(notes).strip()
        cls._validate_account_state(account)
        cls._ensure_reference_available(reference)

        if account.balance < amount:
            raise ValidationError("Insufficient savings balance.")

        account.balance -= amount
        account.save(update_fields=["balance", "updated_at"])

        try:
            savings_transaction = SavingsTransaction.objects.create(
                account=account,
                type=SavingsTransaction.Type.WITHDRAWAL,
                amount=amount,
                balance_after=account.balance,
                reference=reference,
                performed_by=performed_by,
                notes=notes,
            )
            TransactionLedgerService.record(
                institution=account.client.institution,
                branch=account.client.branch,
                client=account.client,
                category=Transaction.Category.SAVINGS_WITHDRAWAL,
                direction=Transaction.Direction.DEBIT,
                amount=amount,
                reference=reference,
                description=f"Savings withdrawal from {account.account_number}",
                created_by=performed_by,
            )
            AccountingPostingService.post_savings_withdrawal(
                account=account,
                amount=amount,
                reference=reference,
                posted_by=performed_by,
            )
        except IntegrityError as exc:
            raise cls._duplicate_reference_error() from exc

        AuditService.log(
            user=performed_by,
            action="savings.withdraw",
            target=str(account.id),
            metadata={
                "account_number": account.account_number,
                "amount": str(amount),
                "reference": reference,
            },
        )
        return savings_transaction
