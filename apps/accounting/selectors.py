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


def general_ledger_data_for_user(
    user,
    *,
    institution_id=None,
    branch_id=None,
    account_id=None,
    date_from=None,
    date_to=None,
):
    entries = journal_entries_for_user(user).filter(status=JournalEntry.Status.POSTED)

    if institution_id:
        entries = entries.filter(institution_id=institution_id)

    if branch_id:
        entries = entries.filter(branch_id=branch_id)

    if date_from:
        entries = entries.filter(entry_date__gte=date_from)

    if date_to:
        entries = entries.filter(entry_date__lte=date_to)

    lines = JournalEntryLine.objects.filter(journal_entry__in=entries).select_related(
        "journal_entry",
        "account",
    )

    if account_id:
        lines = lines.filter(account_id=account_id)

    lines = lines.order_by("account__code", "journal_entry__entry_date", "created_at", "id")

    rows = []
    running_by_account = {}
    for line in lines:
        account_id_value = str(line.account_id)
        if account_id_value not in running_by_account:
            running_by_account[account_id_value] = ZERO_DECIMAL

        delta = line.debit - line.credit
        if line.account.normal_balance == LedgerAccount.NormalBalance.CREDIT:
            delta = line.credit - line.debit

        running_by_account[account_id_value] += delta
        rows.append(
            {
                "entry_id": str(line.journal_entry_id),
                "entry_date": line.journal_entry.entry_date,
                "reference": line.journal_entry.reference,
                "source_reference": line.journal_entry.source_reference,
                "description": line.description or line.journal_entry.description,
                "account": str(line.account_id),
                "account_code": line.account.code,
                "account_name": line.account.name,
                "debit": line.debit,
                "credit": line.credit,
                "running_balance": running_by_account[account_id_value],
            }
        )

    return rows


def balance_sheet_data_for_user(user, *, institution_id=None, branch_id=None, as_of=None):
    trial_balance = trial_balance_data_for_user(
        user,
        institution_id=institution_id,
        branch_id=branch_id,
        as_of=as_of,
    )

    sections = {
        "assets": [],
        "liabilities": [],
        "equity": [],
    }
    totals = {
        "assets": ZERO_DECIMAL,
        "liabilities": ZERO_DECIMAL,
        "equity": ZERO_DECIMAL,
    }

    type_to_section = {
        LedgerAccount.AccountType.ASSET: "assets",
        LedgerAccount.AccountType.LIABILITY: "liabilities",
        LedgerAccount.AccountType.EQUITY: "equity",
    }

    for row in trial_balance["rows"]:
        section = type_to_section.get(row["type"])
        if not section:
            continue

        balance = row["balance"]
        sections[section].append(row)
        totals[section] += balance

    totals["difference"] = totals["assets"] - (totals["liabilities"] + totals["equity"])

    return {
        "sections": sections,
        "totals": totals,
    }
