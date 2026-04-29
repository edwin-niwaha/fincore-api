from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class LedgerAccount(TimeStampedModel):
    class AccountType(models.TextChoices):
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"

    class NormalBalance(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    class SystemCode(models.TextChoices):
        CASH_ON_HAND = "cash_on_hand", "Cash on Hand"
        SAVINGS_CONTROL = "savings_control", "Savings Control"
        LOANS_RECEIVABLE = "loans_receivable", "Loans Receivable"
        INTEREST_INCOME = "interest_income", "Interest Income"

    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.CASCADE,
        related_name="ledger_accounts",
    )
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=160)
    type = models.CharField(max_length=20, choices=AccountType.choices)
    normal_balance = models.CharField(
        max_length=10,
        choices=NormalBalance.choices,
        default=NormalBalance.DEBIT,
    )
    description = models.TextField(blank=True)
    system_code = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    allow_manual_entries = models.BooleanField(default=True)

    class Meta:
        ordering = ["code", "name"]
        unique_together = ("institution", "code")

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        self.description = self.description.strip()
        if self.system_code:
            self.system_code = self.system_code.strip()
        self.normal_balance = self.normal_balance_for_type(self.type)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"

    @classmethod
    def normal_balance_for_type(cls, account_type):
        if account_type in {cls.AccountType.ASSET, cls.AccountType.EXPENSE}:
            return cls.NormalBalance.DEBIT
        return cls.NormalBalance.CREDIT

    @property
    def is_system(self):
        return bool(self.system_code)


class JournalEntry(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        SAVINGS_DEPOSIT = "savings_deposit", "Savings Deposit"
        SAVINGS_WITHDRAWAL = "savings_withdrawal", "Savings Withdrawal"
        LOAN_DISBURSEMENT = "loan_disbursement", "Loan Disbursement"
        LOAN_REPAYMENT = "loan_repayment", "Loan Repayment"

    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.PROTECT,
        related_name="journal_entries",
    )
    branch = models.ForeignKey(
        "institutions.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journal_entries",
    )
    reference = models.CharField(max_length=80)
    source_reference = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    entry_date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    source = models.CharField(
        max_length=40,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_journal_entries",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-entry_date", "-created_at"]
        unique_together = ("institution", "reference")

    def __str__(self):
        return self.reference

    @property
    def total_debit(self):
        return sum((line.debit for line in self.lines.all()), Decimal("0.00"))

    @property
    def total_credit(self):
        return sum((line.credit for line in self.lines.all()), Decimal("0.00"))

    @property
    def is_balanced(self):
        return self.total_debit > 0 and self.total_debit == self.total_credit


class JournalEntryLine(TimeStampedModel):
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.account.code} ({self.debit}/{self.credit})"
