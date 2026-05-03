from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit.services import AuditService
from .models import ShareAccount, ShareTransaction


class ShareService:
    @staticmethod
    @transaction.atomic
    def post(*, account: ShareAccount, transaction_type: str, shares: int, reference: str, performed_by=None, notes: str = ""):
        account = ShareAccount.objects.select_for_update().select_related("product").get(pk=account.pk)
        if ShareTransaction.objects.filter(reference=reference).exists():
            raise ValidationError("A share transaction with this reference already exists.")
        if account.status != "active":
            raise ValidationError("Only active share accounts can transact.")

        new_balance = account.shares
        if transaction_type in {ShareTransaction.Type.PURCHASE, ShareTransaction.Type.TRANSFER_IN}:
            new_balance += shares
        elif transaction_type in {ShareTransaction.Type.REDEEM, ShareTransaction.Type.TRANSFER_OUT}:
            if shares > account.shares:
                raise ValidationError("Insufficient shares for this transaction.")
            new_balance -= shares
        else:
            raise ValidationError("Unsupported share operation.")

        amount = Decimal(shares) * account.product.nominal_price
        row = ShareTransaction.objects.create(
            account=account,
            type=transaction_type,
            shares=shares,
            amount=amount,
            balance_after=new_balance,
            reference=reference,
            performed_by=performed_by if getattr(performed_by, "is_authenticated", False) else None,
            notes=notes,
        )
        account.shares = new_balance
        account.total_value = Decimal(new_balance) * account.product.nominal_price
        account.save(update_fields=["shares", "total_value", "updated_at"])
        AuditService.log(user=performed_by, action=f"shares.{transaction_type}", target=str(account.id), metadata={"reference": reference, "shares": shares, "amount": str(amount)})
        return row
