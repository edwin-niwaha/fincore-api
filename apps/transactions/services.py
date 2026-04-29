from decimal import Decimal

from django.db import IntegrityError
from rest_framework.exceptions import ValidationError

from .models import Transaction

ZERO_DECIMAL = Decimal("0.00")


class TransactionLedgerService:
    @staticmethod
    def _normalize_amount(amount):
        normalized_amount = Decimal(str(amount))
        if normalized_amount <= ZERO_DECIMAL:
            raise ValidationError("Amount must be greater than zero.")
        return normalized_amount

    @staticmethod
    def _normalize_reference(reference):
        normalized_reference = str(reference or "").strip()
        if not normalized_reference:
            raise ValidationError({"reference": ["Reference is required."]})
        return normalized_reference

    @staticmethod
    def _normalize_text(value):
        return str(value or "").strip()

    @classmethod
    def _validate_scope(cls, *, institution, branch, client=None):
        if branch.institution_id != institution.id:
            raise ValidationError("Selected branch does not belong to the selected institution.")

        if client is not None:
            if client.institution_id != institution.id:
                raise ValidationError(
                    "Selected client does not belong to the selected institution."
                )
            if client.branch_id != branch.id:
                raise ValidationError("Selected client does not belong to the selected branch.")

    @classmethod
    def record(
        cls,
        *,
        institution,
        branch,
        client=None,
        category,
        direction,
        amount,
        reference,
        description="",
        created_by=None,
    ):
        category = cls._normalize_text(category)
        direction = cls._normalize_text(direction)
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        description = cls._normalize_text(description)
        cls._validate_scope(institution=institution, branch=branch, client=client)

        if direction not in Transaction.Direction.values:
            raise ValidationError({"direction": ["Unsupported transaction direction."]})

        try:
            return Transaction.objects.create(
                institution=institution,
                branch=branch,
                client=client,
                category=category,
                direction=direction,
                amount=amount,
                reference=reference,
                description=description,
                created_by=created_by,
            )
        except IntegrityError as exc:
            raise ValidationError(
                {"reference": ["A transaction with this reference already exists."]}
            ) from exc
