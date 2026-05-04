from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.audit.services import AuditService
from apps.clients.models import ClientStatusChoices
from apps.common.models import StatusChoices
from apps.notifications.services import NotificationService

from .models import ShareAccount, ShareTransaction

ZERO_DECIMAL = Decimal("0.00")


class ShareService:
    @staticmethod
    def _normalize_shares(shares):
        normalized_shares = int(shares)
        if normalized_shares <= 0:
            raise ValidationError({"shares": ["Shares must be greater than zero."]})
        return normalized_shares

    @staticmethod
    def _normalize_reference(reference):
        normalized_reference = str(reference).strip()
        if not normalized_reference:
            raise ValidationError({"reference": ["Reference is required."]})
        return normalized_reference

    @staticmethod
    def _normalize_notes(notes):
        return str(notes or "").strip()

    @staticmethod
    def _duplicate_reference_error():
        return ValidationError(
            {"reference": ["A share transaction with this reference already exists."]}
        )

    @classmethod
    def _validate_account_state(cls, account):
        if account.status != StatusChoices.ACTIVE:
            raise ValidationError("Only active share accounts can transact.")
        if account.product.status != StatusChoices.ACTIVE:
            raise ValidationError("Only active share products can transact.")
        if account.client.status != ClientStatusChoices.ACTIVE:
            raise ValidationError("Only active clients can transact on share accounts.")
        if account.client.institution_id != account.product.institution_id:
            raise ValidationError("Share account client and product must belong to the same institution.")

    @classmethod
    def _validate_resulting_balance(cls, *, account, transaction_type, shares, new_balance):
        minimum_shares = int(account.product.minimum_shares or 1)
        maximum_shares = account.product.maximum_shares

        if transaction_type == ShareTransaction.Type.PURCHASE and maximum_shares is not None:
            if new_balance > maximum_shares:
                raise ValidationError(
                    {
                        "shares": [
                            f"Share balance cannot exceed the product maximum of {maximum_shares} shares."
                        ]
                    }
                )

        if new_balance > 0 and new_balance < minimum_shares:
            if transaction_type == ShareTransaction.Type.PURCHASE:
                raise ValidationError(
                    {
                        "shares": [
                            f"Share balance must reach the product minimum of {minimum_shares} shares."
                        ]
                    }
                )
            raise ValidationError(
                {
                    "shares": [
                        f"Share balance must remain at or above the product minimum of {minimum_shares} shares unless fully redeemed."
                    ]
                }
            )

    @classmethod
    @transaction.atomic
    def post(
        cls,
        *,
        account: ShareAccount,
        transaction_type: str,
        shares: int,
        reference: str,
        performed_by=None,
        notes: str = "",
    ):
        account = (
            ShareAccount.objects.select_for_update()
            .select_related("product", "client__institution", "client__branch")
            .get(pk=account.pk)
        )
        shares = cls._normalize_shares(shares)
        reference = cls._normalize_reference(reference)
        notes = cls._normalize_notes(notes)
        if ShareTransaction.objects.filter(reference__iexact=reference).exists():
            raise cls._duplicate_reference_error()
        cls._validate_account_state(account)

        new_balance = account.shares
        if transaction_type in {ShareTransaction.Type.PURCHASE, ShareTransaction.Type.TRANSFER_IN}:
            new_balance += shares
        elif transaction_type in {ShareTransaction.Type.REDEEM, ShareTransaction.Type.TRANSFER_OUT}:
            if shares > account.shares:
                raise ValidationError({"shares": ["Insufficient shares for this transaction."]})
            new_balance -= shares
        else:
            raise ValidationError("Unsupported share operation.")

        cls._validate_resulting_balance(
            account=account,
            transaction_type=transaction_type,
            shares=shares,
            new_balance=new_balance,
        )

        amount = Decimal(shares) * account.product.nominal_price
        if amount <= ZERO_DECIMAL:
            raise ValidationError("Share transaction amount must be greater than zero.")

        try:
            row = ShareTransaction.objects.create(
                account=account,
                type=transaction_type,
                shares=shares,
                amount=amount,
                balance_after=new_balance,
                reference=reference,
                performed_by=performed_by
                if getattr(performed_by, "is_authenticated", False)
                else None,
                notes=notes,
            )
        except IntegrityError as exc:
            raise cls._duplicate_reference_error() from exc

        account.shares = new_balance
        account.total_value = Decimal(new_balance) * account.product.nominal_price
        account.save(update_fields=["shares", "total_value", "updated_at"])

        AuditService.log(
            user=performed_by,
            action=f"shares.{transaction_type}",
            target=str(account.id),
            metadata={
                "account_number": account.account_number,
                "product_id": str(account.product_id),
                "product_code": account.product.code,
                "reference": reference,
                "shares": shares,
                "amount": str(amount),
                "balance_after": new_balance,
                "total_value_after": str(account.total_value),
            },
        )
        NotificationService.notify_client(
            client=account.client,
            title=(
                "Share purchase recorded"
                if transaction_type == ShareTransaction.Type.PURCHASE
                else "Share redemption recorded"
            ),
            message=(
                f"{shares} share(s) were "
                f"{'purchased into' if transaction_type == ShareTransaction.Type.PURCHASE else 'redeemed from'} "
                f"share account {account.account_number}. New balance: {account.shares} share(s)."
            ),
            category=(
                "share_purchase_recorded"
                if transaction_type == ShareTransaction.Type.PURCHASE
                else "share_redemption_recorded"
            ),
            data={
                "account_id": str(account.id),
                "account_number": account.account_number,
                "product_id": str(account.product_id),
                "product_name": account.product.name,
                "reference": reference,
                "shares": shares,
                "amount": f"{amount:.2f}",
                "balance_after": account.shares,
                "total_value_after": f"{account.total_value:.2f}",
            },
        )
        return row
