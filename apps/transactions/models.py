from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimeStampedModel


class Transaction(TimeStampedModel):
    class Category:
        SAVINGS_DEPOSIT = "savings_deposit"
        SAVINGS_WITHDRAWAL = "savings_withdrawal"
        LOAN_DISBURSEMENT = "loan_disbursement"
        LOAN_REPAYMENT = "loan_repayment"

    class Direction(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    institution = models.ForeignKey("institutions.Institution", on_delete=models.PROTECT)
    branch = models.ForeignKey("institutions.Branch", on_delete=models.PROTECT)
    client = models.ForeignKey("clients.Client", null=True, blank=True, on_delete=models.PROTECT)
    category = models.CharField(max_length=40)
    direction = models.CharField(max_length=20, choices=Direction.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="transaction_amount_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["institution", "created_at"],
                name="txn_inst_created_idx",
            ),
            models.Index(
                fields=["branch", "created_at"],
                name="txn_branch_created_idx",
            ),
            models.Index(
                fields=["client", "created_at"],
                name="txn_client_created_idx",
            ),
            models.Index(
                fields=["category", "direction", "created_at"],
                name="txn_cat_dir_created_idx",
            ),
        ]

    def __str__(self):
        return self.reference

    @property
    def category_label(self):
        return self.category.replace("_", " ").title()
