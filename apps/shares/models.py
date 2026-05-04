from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q, Sum

from apps.common.models import StatusChoices, TimeStampedModel


class ShareProduct(TimeStampedModel):
    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.PROTECT,
        related_name="share_products",
    )
    name = models.CharField(max_length=160)
    code = models.SlugField()
    nominal_price = models.DecimalField(max_digits=14, decimal_places=2)
    minimum_shares = models.PositiveIntegerField(default=1)
    maximum_shares = models.PositiveIntegerField(null=True, blank=True)
    allow_dividends = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    description = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        unique_together = ("institution", "code")
        indexes = [models.Index(fields=["institution", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(nominal_price__gt=0),
                name="share_product_nominal_price_positive",
            ),
            models.CheckConstraint(
                condition=Q(minimum_shares__gte=1),
                name="share_product_minimum_shares_positive",
            ),
            models.CheckConstraint(
                condition=Q(maximum_shares__isnull=True) | Q(maximum_shares__gte=1),
                name="share_product_maximum_shares_positive",
            ),
            models.CheckConstraint(
                condition=Q(maximum_shares__isnull=True)
                | Q(maximum_shares__gte=F("minimum_shares")),
                name="share_product_maximum_gte_minimum",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class ShareAccountSequence(models.Model):
    branch = models.OneToOneField(
        "institutions.Branch",
        on_delete=models.CASCADE,
        related_name="share_account_sequence",
    )
    last_value = models.PositiveIntegerField(default=0)

    @classmethod
    def next_value_for_branch(cls, branch):
        with transaction.atomic():
            sequence, _ = cls.objects.select_for_update().get_or_create(branch=branch)
            sequence.last_value = F("last_value") + 1
            sequence.save(update_fields=["last_value"])
            sequence.refresh_from_db(fields=["last_value"])
            return sequence.last_value


class ShareAccount(TimeStampedModel):
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="share_accounts")
    product = models.ForeignKey(ShareProduct, on_delete=models.PROTECT, related_name="accounts")
    account_number = models.CharField(max_length=40, unique=True, blank=True)
    shares = models.PositiveIntegerField(default=0)
    total_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["client", "product"], name="unique_client_share_product"),
            models.CheckConstraint(condition=Q(shares__gte=0), name="share_account_shares_non_negative"),
            models.CheckConstraint(condition=Q(total_value__gte=0), name="share_account_value_non_negative"),
        ]
        indexes = [models.Index(fields=["client", "status"]), models.Index(fields=["product", "status"])]

    def save(self, *args, **kwargs):
        if not self.account_number:
            next_value = ShareAccountSequence.next_value_for_branch(self.client.branch)
            self.account_number = f"SHR-{self.client.member_number}-{next_value:03d}"
        super().save(*args, **kwargs)

    def refresh_totals(self):
        totals = self.transactions.aggregate(
            issued=Sum("shares", filter=Q(type=ShareTransaction.Type.PURCHASE)),
            transferred_in=Sum("shares", filter=Q(type=ShareTransaction.Type.TRANSFER_IN)),
            redeemed=Sum("shares", filter=Q(type=ShareTransaction.Type.REDEEM)),
            transferred_out=Sum("shares", filter=Q(type=ShareTransaction.Type.TRANSFER_OUT)),
        )
        credits = (totals["issued"] or 0) + (totals["transferred_in"] or 0)
        debits = (totals["redeemed"] or 0) + (totals["transferred_out"] or 0)
        self.shares = max(credits - debits, 0)
        self.total_value = Decimal(self.shares) * self.product.nominal_price
        self.save(update_fields=["shares", "total_value", "updated_at"])

    def __str__(self):
        return self.account_number


class ShareTransaction(TimeStampedModel):
    class Type(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        REDEEM = "redeem", "Redeem"
        TRANSFER_IN = "transfer_in", "Transfer In"
        TRANSFER_OUT = "transfer_out", "Transfer Out"
        DIVIDEND = "dividend", "Dividend"

    account = models.ForeignKey(ShareAccount, on_delete=models.PROTECT, related_name="transactions")
    type = models.CharField(max_length=20, choices=Type.choices)
    shares = models.PositiveIntegerField(default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.PositiveIntegerField(default=0)
    reference = models.CharField(max_length=80, unique=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="share_transaction_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(balance_after__gte=0),
                name="share_transaction_balance_after_non_negative",
            ),
        ]
        indexes = [models.Index(fields=["account", "type", "created_at"])]

    def __str__(self):
        return f"{self.reference} ({self.get_type_display()})"
