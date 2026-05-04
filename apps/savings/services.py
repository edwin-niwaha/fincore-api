from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounting.services import AccountingPostingService
from apps.audit.services import AuditService
from apps.notifications.services import NotificationService
from apps.common.models import StatusChoices
from apps.transactions.models import Transaction
from apps.transactions.services import TransactionLedgerService

from .models import SavingsAccount, SavingsPolicy, SavingsTransaction

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

    @staticmethod
    def _normalize_transaction_date(transaction_date=None):
        normalized_date = transaction_date or timezone.localdate()
        if normalized_date > timezone.localdate():
            raise ValidationError(
                {"transaction_date": ["Transaction date cannot be in the future."]}
            )
        return normalized_date

    @classmethod
    def _validate_account_state(cls, account):
        if account.status != StatusChoices.ACTIVE:
            raise ValidationError("Only active savings accounts can process transactions.")

    @classmethod
    def _ensure_reference_available(cls, reference):
        if SavingsTransaction.objects.filter(reference__iexact=reference).exists():
            raise ValidationError({"reference": ["A savings transaction with this reference exists."]})
        if Transaction.objects.filter(reference__iexact=reference).exists():
            raise ValidationError({"reference": ["A transaction with this reference already exists."]})

    @staticmethod
    def _duplicate_reference_error():
        return ValidationError({"reference": ["A transaction with this reference already exists."]})

    @classmethod
    def _charge_reference(cls, reference):
        return f"{reference}-CHG"

    @classmethod
    @transaction.atomic
    def deposit(cls, *, account, amount, performed_by=None, reference, transaction_date=None, notes=""):
        account = (
            SavingsAccount.objects.select_for_update()
            .select_related("client__institution", "client__branch")
            .get(pk=account.pk)
        )
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        transaction_date = cls._normalize_transaction_date(transaction_date)
        notes = str(notes).strip()
        cls._validate_account_state(account)
        cls._ensure_reference_available(reference)

        account.balance += amount
        account.save(update_fields=["balance", "updated_at"])

        try:
            savings_transaction = SavingsTransaction.objects.create(
                account=account,
                type=SavingsTransaction.Type.DEPOSIT,
                transaction_date=transaction_date,
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
                "transaction_date": transaction_date.isoformat(),
            },
        )
        NotificationService.notify_client(
            client=account.client,
            title="Savings deposit recorded",
            message=(
                f"A deposit of {amount:.2f} was posted to savings account "
                f"{account.account_number}. New balance: {account.balance:.2f}."
            ),
            category="savings_deposit_recorded",
            data={
                "account_id": str(account.id),
                "account_number": account.account_number,
                "reference": reference,
                "transaction_date": transaction_date.isoformat(),
                "amount": f"{amount:.2f}",
                "balance_after": f"{account.balance:.2f}",
            },
        )
        return savings_transaction

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, account, amount, performed_by=None, reference, transaction_date=None, notes=""):
        account = (
            SavingsAccount.objects.select_for_update()
            .select_related("client__institution", "client__branch")
            .get(pk=account.pk)
        )
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        transaction_date = cls._normalize_transaction_date(transaction_date)
        notes = str(notes).strip()
        policy = SavingsPolicy.current(account.client.institution)
        withdrawal_charge = Decimal(policy.withdrawal_charge or ZERO_DECIMAL)
        minimum_balance = Decimal(policy.minimum_balance or ZERO_DECIMAL)
        total_debit = amount + withdrawal_charge

        cls._validate_account_state(account)
        cls._ensure_reference_available(reference)
        if withdrawal_charge > ZERO_DECIMAL:
            cls._ensure_reference_available(cls._charge_reference(reference))

        if account.balance < total_debit:
            raise ValidationError(
                {
                    "amount": [
                        f"Insufficient savings balance. Required amount including charge is {total_debit:.2f}."
                    ]
                }
            )

        projected_balance = account.balance - total_debit
        if projected_balance < minimum_balance:
            raise ValidationError(
                {
                    "amount": [
                        f"Withdrawal denied. Minimum balance of {minimum_balance:.2f} must remain after withdrawal and charge."
                    ]
                }
            )

        account.balance -= amount
        account.save(update_fields=["balance", "updated_at"])

        try:
            savings_transaction = SavingsTransaction.objects.create(
                account=account,
                type=SavingsTransaction.Type.WITHDRAWAL,
                transaction_date=transaction_date,
                amount=amount,
                balance_after=account.balance,
                reference=reference,
                performed_by=performed_by,
                notes=notes,
            )

            if withdrawal_charge > ZERO_DECIMAL:
                account.balance -= withdrawal_charge
                account.save(update_fields=["balance", "updated_at"])
                SavingsTransaction.objects.create(
                    account=account,
                    type=SavingsTransaction.Type.WITHDRAWAL_CHARGE,
                    transaction_date=transaction_date,
                    amount=withdrawal_charge,
                    balance_after=account.balance,
                    reference=cls._charge_reference(reference),
                    performed_by=performed_by,
                    notes=f"Withdrawal charge for {reference}",
                )

            TransactionLedgerService.record(
                institution=account.client.institution,
                branch=account.client.branch,
                client=account.client,
                category=Transaction.Category.SAVINGS_WITHDRAWAL,
                direction=Transaction.Direction.DEBIT,
                amount=total_debit,
                reference=reference,
                description=f"Savings withdrawal from {account.account_number}",
                created_by=performed_by,
            )
            AccountingPostingService.post_savings_withdrawal(
                account=account,
                amount=total_debit,
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
                "withdrawal_charge": str(withdrawal_charge),
                "minimum_balance": str(minimum_balance),
                "total_debit": str(total_debit),
                "reference": reference,
                "transaction_date": transaction_date.isoformat(),
            },
        )
        NotificationService.notify_client(
            client=account.client,
            title="Savings withdrawal recorded",
            message=(
                f"A withdrawal of {amount:.2f} was posted to savings account "
                f"{account.account_number}. Charge: {withdrawal_charge:.2f}. "
                f"New balance: {account.balance:.2f}."
            ),
            category="savings_withdrawal_recorded",
            data={
                "account_id": str(account.id),
                "account_number": account.account_number,
                "reference": reference,
                "transaction_date": transaction_date.isoformat(),
                "amount": f"{amount:.2f}",
                "withdrawal_charge": f"{withdrawal_charge:.2f}",
                "minimum_balance": f"{minimum_balance:.2f}",
                "total_debit": f"{total_debit:.2f}",
                "balance_after": f"{account.balance:.2f}",
            },
        )
        return savings_transaction
