from django.conf import settings
from decimal import Decimal
from django.db import models
from apps.common.models import StatusChoices, TimeStampedModel

class SavingsAccount(TimeStampedModel):
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="savings_accounts")
    account_number = models.CharField(max_length=40, unique=True, blank=True)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)

    def save(self, *args, **kwargs):
        if not self.account_number:
            count = SavingsAccount.objects.filter(client__branch=self.client.branch).count() + 1
            self.account_number = f"SAV-{self.client.member_number}-{count:03d}"
        super().save(*args, **kwargs)

class SavingsTransaction(TimeStampedModel):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
    account = models.ForeignKey(SavingsAccount, on_delete=models.PROTECT, related_name="transactions")
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, unique=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)
