from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import JournalEntry, JournalEntryLine, LedgerAccount

ZERO_DECIMAL = Decimal("0.00")


def normalize_decimal(value):
    amount = Decimal(str(value or ZERO_DECIMAL)).quantize(Decimal("0.01"))
    return amount


class ChartOfAccountsService:
    DEFAULT_ACCOUNTS = (
        {
            "code": "1000",
            "name": "Cash on Hand",
            "type": LedgerAccount.AccountType.ASSET,
            "system_code": LedgerAccount.SystemCode.CASH_ON_HAND,
            "description": "Cash and teller float used for client-facing collections and payouts.",
        },
        {
            "code": "2000",
            "name": "Client Savings Control",
            "type": LedgerAccount.AccountType.LIABILITY,
            "system_code": LedgerAccount.SystemCode.SAVINGS_CONTROL,
            "description": "Outstanding liability owed to clients for savings balances.",
        },
        {
            "code": "1300",
            "name": "Loans Receivable",
            "type": LedgerAccount.AccountType.ASSET,
            "system_code": LedgerAccount.SystemCode.LOANS_RECEIVABLE,
            "description": "Principal outstanding on disbursed client loans.",
        },
        {
            "code": "4000",
            "name": "Interest Income",
            "type": LedgerAccount.AccountType.INCOME,
            "system_code": LedgerAccount.SystemCode.INTEREST_INCOME,
            "description": "Interest earned on loan repayments.",
        },
    )

    @classmethod
    def ensure_default_accounts(cls, institution):
        for config in cls.DEFAULT_ACCOUNTS:
            LedgerAccount.objects.update_or_create(
                institution=institution,
                code=config["code"],
                defaults={
                    "name": config["name"],
                    "type": config["type"],
                    "description": config["description"],
                    "system_code": config["system_code"],
                    "is_active": True,
                    "allow_manual_entries": True,
                },
            )

        return {
            account.system_code: account
            for account in LedgerAccount.objects.filter(
                institution=institution,
                system_code__in=[item["system_code"] for item in cls.DEFAULT_ACCOUNTS],
            )
        }

    @classmethod
    def get_system_accounts(cls, institution):
        accounts = cls.ensure_default_accounts(institution)
        missing_codes = [
            config["system_code"]
            for config in cls.DEFAULT_ACCOUNTS
            if config["system_code"] not in accounts
        ]
        if missing_codes:
            raise ValidationError(
                f"Missing required system accounts: {', '.join(missing_codes)}."
            )

        inactive_codes = [
            code for code, account in accounts.items() if not account.is_active
        ]
        if inactive_codes:
            raise ValidationError(
                f"Required system accounts are inactive: {', '.join(inactive_codes)}."
            )

        return accounts


class JournalService:
    @staticmethod
    def _normalize_account(account, institution):
        if isinstance(account, LedgerAccount):
            resolved = account
        else:
            resolved = LedgerAccount.objects.select_related("institution").get(pk=account)

        if resolved.institution_id != institution.id:
            raise ValidationError("Journal line account must belong to the selected institution.")

        if not resolved.is_active:
            raise ValidationError(f"Ledger account {resolved.code} is inactive.")

        return resolved

    @classmethod
    def normalize_lines(cls, *, lines, institution):
        normalized = []

        if not lines:
            raise ValidationError({"lines": ["At least one journal line is required."]})

        for index, line in enumerate(lines, start=1):
            account = cls._normalize_account(line.get("account"), institution)
            debit = normalize_decimal(line.get("debit"))
            credit = normalize_decimal(line.get("credit"))

            if debit < 0 or credit < 0:
                raise ValidationError(
                    {"lines": [f"Line {index} cannot contain negative debit or credit values."]}
                )

            if (debit > 0 and credit > 0) or (debit <= 0 and credit <= 0):
                raise ValidationError(
                    {
                        "lines": [
                            f"Line {index} must contain a positive debit or a positive credit."
                        ]
                    }
                )

            normalized.append(
                {
                    "account": account,
                    "description": (line.get("description") or "").strip(),
                    "debit": debit,
                    "credit": credit,
                }
            )

        return normalized

    @staticmethod
    def line_totals(lines):
        total_debit = sum((line["debit"] for line in lines), ZERO_DECIMAL)
        total_credit = sum((line["credit"] for line in lines), ZERO_DECIMAL)
        return total_debit, total_credit

    @classmethod
    def validate_postable_lines(cls, lines):
        total_debit, total_credit = cls.line_totals(lines)
        if total_debit <= 0:
            raise ValidationError("Journal entry must have a positive debit total before posting.")
        if total_debit != total_credit:
            raise ValidationError("Journal entry cannot be posted unless debits equal credits.")
        return total_debit, total_credit

    @staticmethod
    def _create_lines(entry, lines):
        JournalEntryLine.objects.bulk_create(
            [
                JournalEntryLine(
                    journal_entry=entry,
                    account=line["account"],
                    description=line["description"],
                    debit=line["debit"],
                    credit=line["credit"],
                )
                for line in lines
            ]
        )

    @classmethod
    @transaction.atomic
    def create_entry(
        cls,
        *,
        institution,
        branch=None,
        reference,
        description="",
        entry_date=None,
        lines,
        posted_by=None,
        status=JournalEntry.Status.DRAFT,
        source=JournalEntry.Source.MANUAL,
        source_reference="",
    ):
        normalized_lines = cls.normalize_lines(lines=lines, institution=institution)
        entry = JournalEntry.objects.create(
            institution=institution,
            branch=branch,
            reference=reference.strip(),
            source_reference=source_reference.strip(),
            description=description.strip(),
            entry_date=entry_date or timezone.localdate(),
            status=JournalEntry.Status.DRAFT,
            source=source,
        )
        cls._create_lines(entry, normalized_lines)

        if status == JournalEntry.Status.POSTED:
            entry = cls.post_existing_entry(entry=entry, posted_by=posted_by)

        return entry

    @classmethod
    @transaction.atomic
    def update_draft_entry(
        cls,
        *,
        entry,
        institution=None,
        branch=None,
        reference=None,
        description=None,
        entry_date=None,
        lines=None,
        status=None,
        posted_by=None,
    ):
        entry = JournalEntry.objects.select_for_update().prefetch_related("lines").get(pk=entry.pk)

        if entry.status == JournalEntry.Status.POSTED:
            raise ValidationError("Posted journal entries cannot be edited.")

        if institution is not None and institution.id != entry.institution_id:
            raise ValidationError("Draft journal entries cannot be moved to another institution.")

        if branch is not None:
            entry.branch = branch

        if reference is not None:
            entry.reference = reference.strip()

        if description is not None:
            entry.description = description.strip()

        if entry_date is not None:
            entry.entry_date = entry_date

        if lines is not None:
            normalized_lines = cls.normalize_lines(lines=lines, institution=entry.institution)
            entry.lines.all().delete()
            cls._create_lines(entry, normalized_lines)

        entry.save()

        if status == JournalEntry.Status.POSTED:
            return cls.post_existing_entry(entry=entry, posted_by=posted_by)

        return entry

    @classmethod
    @transaction.atomic
    def post_existing_entry(cls, *, entry, posted_by=None):
        entry = JournalEntry.objects.select_for_update().prefetch_related("lines").get(pk=entry.pk)

        if entry.status == JournalEntry.Status.POSTED:
            raise ValidationError("Journal entry is already posted.")

        lines = [
            {
                "account": line.account,
                "description": line.description,
                "debit": line.debit,
                "credit": line.credit,
            }
            for line in entry.lines.select_related("account")
        ]
        cls.validate_postable_lines(lines)
        entry.status = JournalEntry.Status.POSTED
        entry.posted_at = timezone.now()
        entry.posted_by = posted_by
        entry.save(update_fields=["status", "posted_at", "posted_by", "updated_at"])
        return entry


class AccountingPostingService:
    @staticmethod
    def _journal_reference(prefix, reference):
        return f"{prefix}-{reference}".strip()

    @classmethod
    def post_savings_deposit(cls, *, account, amount, reference, posted_by=None):
        system_accounts = ChartOfAccountsService.get_system_accounts(account.client.institution)
        return JournalService.create_entry(
            institution=account.client.institution,
            branch=account.client.branch,
            reference=cls._journal_reference("SAV-DEP", reference),
            source_reference=reference,
            description=f"Savings deposit for {account.client.member_number}",
            entry_date=timezone.localdate(),
            status=JournalEntry.Status.POSTED,
            source=JournalEntry.Source.SAVINGS_DEPOSIT,
            posted_by=posted_by,
            lines=[
                {
                    "account": system_accounts[LedgerAccount.SystemCode.CASH_ON_HAND],
                    "debit": amount,
                    "credit": ZERO_DECIMAL,
                },
                {
                    "account": system_accounts[LedgerAccount.SystemCode.SAVINGS_CONTROL],
                    "debit": ZERO_DECIMAL,
                    "credit": amount,
                },
            ],
        )

    @classmethod
    def post_savings_withdrawal(cls, *, account, amount, reference, posted_by=None):
        system_accounts = ChartOfAccountsService.get_system_accounts(account.client.institution)
        return JournalService.create_entry(
            institution=account.client.institution,
            branch=account.client.branch,
            reference=cls._journal_reference("SAV-WIT", reference),
            source_reference=reference,
            description=f"Savings withdrawal for {account.client.member_number}",
            entry_date=timezone.localdate(),
            status=JournalEntry.Status.POSTED,
            source=JournalEntry.Source.SAVINGS_WITHDRAWAL,
            posted_by=posted_by,
            lines=[
                {
                    "account": system_accounts[LedgerAccount.SystemCode.SAVINGS_CONTROL],
                    "debit": amount,
                    "credit": ZERO_DECIMAL,
                },
                {
                    "account": system_accounts[LedgerAccount.SystemCode.CASH_ON_HAND],
                    "debit": ZERO_DECIMAL,
                    "credit": amount,
                },
            ],
        )

    @classmethod
    def post_loan_disbursement(cls, *, loan, reference, posted_by=None):
        system_accounts = ChartOfAccountsService.get_system_accounts(loan.client.institution)
        return JournalService.create_entry(
            institution=loan.client.institution,
            branch=loan.client.branch,
            reference=cls._journal_reference("LOAN-DISB", reference),
            source_reference=reference,
            description=f"Loan disbursement for {loan.client.member_number}",
            entry_date=timezone.localdate(),
            status=JournalEntry.Status.POSTED,
            source=JournalEntry.Source.LOAN_DISBURSEMENT,
            posted_by=posted_by,
            lines=[
                {
                    "account": system_accounts[LedgerAccount.SystemCode.LOANS_RECEIVABLE],
                    "debit": loan.amount,
                    "credit": ZERO_DECIMAL,
                },
                {
                    "account": system_accounts[LedgerAccount.SystemCode.CASH_ON_HAND],
                    "debit": ZERO_DECIMAL,
                    "credit": loan.amount,
                },
            ],
        )

    @classmethod
    def post_loan_repayment(
        cls,
        *,
        loan,
        amount,
        principal_component,
        interest_component,
        reference,
        posted_by=None,
    ):
        system_accounts = ChartOfAccountsService.get_system_accounts(loan.client.institution)
        lines = [
            {
                "account": system_accounts[LedgerAccount.SystemCode.CASH_ON_HAND],
                "debit": amount,
                "credit": ZERO_DECIMAL,
            }
        ]

        if principal_component > 0:
            lines.append(
                {
                    "account": system_accounts[LedgerAccount.SystemCode.LOANS_RECEIVABLE],
                    "debit": ZERO_DECIMAL,
                    "credit": principal_component,
                }
            )

        if interest_component > 0:
            lines.append(
                {
                    "account": system_accounts[LedgerAccount.SystemCode.INTEREST_INCOME],
                    "debit": ZERO_DECIMAL,
                    "credit": interest_component,
                }
            )

        return JournalService.create_entry(
            institution=loan.client.institution,
            branch=loan.client.branch,
            reference=cls._journal_reference("LOAN-REP", reference),
            source_reference=reference,
            description=f"Loan repayment for {loan.client.member_number}",
            entry_date=timezone.localdate(),
            status=JournalEntry.Status.POSTED,
            source=JournalEntry.Source.LOAN_REPAYMENT,
            posted_by=posted_by,
            lines=lines,
        )
