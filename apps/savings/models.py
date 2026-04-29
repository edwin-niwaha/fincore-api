from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q

from apps.common.models import StatusChoices, TimeStampedModel


class SavingsAccountSequence(models.Model):
    branch = models.OneToOneField(
        "institutions.Branch",
        on_delete=models.CASCADE,
        related_name="savings_account_sequence",
    )
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Savings account sequence"
        verbose_name_plural = "Savings account sequences"

    def __str__(self):
        return f"{self.branch.code.upper()} savings #{self.last_value}"

    @classmethod
    def next_value_for_branch(cls, branch):
        with transaction.atomic():
            sequence, _ = cls.objects.select_for_update().get_or_create(
                branch=branch,
                defaults={"last_value": 0},
            )
            sequence.last_value = F("last_value") + 1
            sequence.save(update_fields=["last_value"])
            sequence.refresh_from_db(fields=["last_value"])
            return sequence.last_value


class SavingsAccount(TimeStampedModel):
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="savings_accounts",
    )
    account_number = models.CharField(max_length=40, unique=True, blank=True)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE,
    )

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(balance__gte=0),
                name="savings_account_balance_non_negative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["client", "status"],
                name="sav_acc_client_status_idx",
            ),
        ]

    def __str__(self):
        return self.account_number or f"Savings account for {self.client}"

    def save(self, *args, **kwargs):
        if not self.account_number:
            next_value = SavingsAccountSequence.next_value_for_branch(self.client.branch)
            self.account_number = f"SAV-{self.client.member_number}-{next_value:03d}"
        super().save(*args, **kwargs)


class SavingsTransaction(TimeStampedModel):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"

    account = models.ForeignKey(
        SavingsAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, unique=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    notes = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="savings_transaction_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(balance_after__gte=0),
                name="savings_transaction_balance_after_non_negative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["account", "type", "created_at"],
                name="sav_tx_acct_type_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.get_type_display()})"
