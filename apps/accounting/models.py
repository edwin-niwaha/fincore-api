from django.conf import settings
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from apps.common.models import TimeStampedModel

class LedgerAccount(TimeStampedModel):
    class Type(models.TextChoices):
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"
    institution = models.ForeignKey("institutions.Institution", on_delete=models.PROTECT, related_name="ledger_accounts")
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=160)
    type = models.CharField(max_length=20, choices=Type.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("institution", "code")

    def __str__(self):
        return f"{self.code} - {self.name}"

class JournalEntry(TimeStampedModel):
    institution = models.ForeignKey("institutions.Institution", on_delete=models.PROTECT)
    branch = models.ForeignKey("institutions.Branch", null=True, blank=True, on_delete=models.PROTECT)
    reference = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    posted_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.pk:
            debits = sum((line.debit for line in self.lines.all()), Decimal("0.00"))
            credits = sum((line.credit for line in self.lines.all()), Decimal("0.00"))
            if debits != credits:
                raise ValidationError("Journal entry must balance.")

class JournalEntryLine(TimeStampedModel):
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    def clean(self):
        if self.debit and self.credit:
            raise ValidationError("A line cannot have both debit and credit.")
        if self.debit < 0 or self.credit < 0:
            raise ValidationError("Debit and credit cannot be negative.")
