from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from apps.users.access import is_super_admin
from apps.users.models import CustomUser

from .models import JournalEntry, JournalEntryLine, LedgerAccount

ZERO_DECIMAL = Decimal("0.00")


def ledger_accounts_for_user(user):
    queryset = LedgerAccount.objects.select_related("institution").order_by("code", "name")

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.role == CustomUser.Role.CLIENT:
        return queryset.none()

    if is_super_admin(user):
        return queryset

    if user.institution_id:
        return queryset.filter(institution_id=user.institution_id)

    return queryset.none()


def journal_entries_for_user(user):
    queryset = JournalEntry.objects.select_related(
        "institution",
        "branch",
        "posted_by",
    ).prefetch_related("lines__account")

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.role == CustomUser.Role.CLIENT:
        return queryset.none()

    if is_super_admin(user):
        return queryset

    if user.branch_id:
        return queryset.filter(branch_id=user.branch_id)

    if user.institution_id:
        return queryset.filter(institution_id=user.institution_id)

    return queryset.none()


def trial_balance_data_for_user(user, *, institution_id=None, branch_id=None, as_of=None):
    entries = journal_entries_for_user(user).filter(status=JournalEntry.Status.POSTED)

    if institution_id:
        entries = entries.filter(institution_id=institution_id)

    if branch_id:
        entries = entries.filter(branch_id=branch_id)

    if as_of:
        entries = entries.filter(entry_date__lte=as_of)

    lines = (
        JournalEntryLine.objects.filter(journal_entry__in=entries)
        .values(
            "account_id",
            "account__code",
            "account__name",
            "account__type",
            "account__normal_balance",
        )
        .annotate(
            total_debit=Coalesce(
                Sum("debit"),
                Value(ZERO_DECIMAL),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            total_credit=Coalesce(
                Sum("credit"),
                Value(ZERO_DECIMAL),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("account__code", "account__name")
    )

    rows = []
    total_debit = ZERO_DECIMAL
    total_credit = ZERO_DECIMAL

    for line in lines:
        debit = line["total_debit"]
        credit = line["total_credit"]
        total_debit += debit
        total_credit += credit
        if line["account__normal_balance"] == LedgerAccount.NormalBalance.DEBIT:
            balance = debit - credit
        else:
            balance = credit - debit
        rows.append(
            {
                "account": line["account_id"],
                "code": line["account__code"],
                "name": line["account__name"],
                "type": line["account__type"],
                "normal_balance": line["account__normal_balance"],
                "total_debit": debit,
                "total_credit": credit,
                "balance": balance,
            }
        )

    return {
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "difference": total_debit - total_credit,
    }
