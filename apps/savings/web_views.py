from html import escape

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from rest_framework.exceptions import ValidationError

from apps.users.models import CustomUser

from .selectors import savings_accounts_for_user
from .services import SavingsService

CASH_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
    CustomUser.Role.ACCOUNTANT,
    CustomUser.Role.TELLER,
}


def _format_problem(exc):
    detail = getattr(exc, "detail", exc)
    if isinstance(detail, dict):
        parts = []
        for value in detail.values():
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            else:
                parts.append(str(value))
        return " ".join(parts)
    if isinstance(detail, list):
        return " ".join(str(item) for item in detail)
    return str(detail)


def _page(title, body):
    return HttpResponse(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{escape(title)}</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 2rem; color: #0f172a; }}
      .stack {{ display: grid; gap: 1rem; }}
      .card {{ border: 1px solid #cbd5e1; border-radius: 1rem; padding: 1rem; background: #fff; }}
      .alert {{ padding: 0.85rem 1rem; border-radius: 0.85rem; background: #ecfccb; color: #365314; }}
      .error {{ padding: 0.85rem 1rem; border-radius: 0.85rem; background: #fef2f2; color: #991b1b; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ text-align: left; padding: 0.6rem; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
      form {{ display: grid; gap: 0.75rem; }}
      input, textarea {{ width: 100%; padding: 0.7rem; border-radius: 0.7rem; border: 1px solid #cbd5e1; }}
      button {{ padding: 0.7rem 1rem; border-radius: 0.7rem; border: 0; background: #127D61; color: white; font-weight: 700; cursor: pointer; }}
    </style>
  </head>
  <body>
    <div class="stack">{body}</div>
  </body>
</html>""",
        content_type="text/html; charset=utf-8",
    )


def _account_detail_markup(account, message=None, error=None):
    transactions = list(account.transactions.order_by("-created_at"))
    transaction_rows = "".join(
        f"""
        <tr>
          <td>{escape(transaction.reference)}</td>
          <td>{escape(transaction.get_type_display())}</td>
          <td>{transaction.amount:.2f}</td>
          <td>{transaction.balance_after:.2f}</td>
        </tr>
        """
        for transaction in transactions
    ) or '<tr><td colspan="4">No savings transactions recorded.</td></tr>'

    message_block = f'<div class="alert">{escape(message)}</div>' if message else ""
    error_block = f'<div class="error">{escape(error)}</div>' if error else ""

    return f"""
      <div class="card">
        <h1>Savings account detail</h1>
        <p>{escape(account.account_number)} | {escape(account.client.member_number)}</p>
        <p>Balance: {account.balance:.2f}</p>
        {message_block}
        {error_block}
      </div>
      <div class="card" id="deposit-modal">
        <h2>Deposit</h2>
        <form method="post" action="{escape(reverse('savings_web:account-deposit', kwargs={'pk': account.pk}))}">
          <input name="amount" placeholder="Amount" required />
          <input name="reference" placeholder="Reference" required />
          <textarea name="notes" placeholder="Notes"></textarea>
          <button type="submit">Post deposit</button>
        </form>
      </div>
      <div class="card" id="withdraw-modal">
        <h2>Withdraw</h2>
        <form method="post" action="{escape(reverse('savings_web:account-withdraw', kwargs={'pk': account.pk}))}">
          <input name="amount" placeholder="Amount" required />
          <input name="reference" placeholder="Reference" required />
          <textarea name="notes" placeholder="Notes"></textarea>
          <button type="submit">Post withdrawal</button>
        </form>
      </div>
      <div class="card">
        <h2>Transaction history</h2>
        <table>
          <thead><tr><th>Reference</th><th>Type</th><th>Amount</th><th>Balance after</th></tr></thead>
          <tbody>{transaction_rows}</tbody>
        </table>
      </div>
    """


@login_required
@require_GET
def account_list(request):
    accounts = savings_accounts_for_user(request.user)
    rows = "".join(
        f"""
        <tr>
          <td>{escape(account.account_number)}</td>
          <td>{escape(account.client.member_number)}</td>
          <td>{account.balance:.2f}</td>
          <td><a href="{escape(reverse('savings_web:account-detail', kwargs={'pk': account.pk}))}">Open detail</a></td>
        </tr>
        """
        for account in accounts
    ) or '<tr><td colspan="4">No savings accounts available.</td></tr>'

    return _page(
        "Savings accounts",
        f"""
        <div class="card">
          <h1>Savings accounts</h1>
          <table>
            <thead><tr><th>Account</th><th>Member</th><th>Balance</th><th>Action</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """,
    )


@login_required
@require_GET
def account_detail(request, pk):
    account = get_object_or_404(savings_accounts_for_user(request.user), pk=pk)
    return _page("Savings account detail", _account_detail_markup(account))


@login_required
@require_POST
def account_deposit(request, pk):
    if request.user.role not in CASH_ROLES:
        return HttpResponseForbidden("You do not have permission to post deposits.")

    account = get_object_or_404(savings_accounts_for_user(request.user), pk=pk)
    try:
        SavingsService.deposit(
            account=account,
            amount=request.POST.get("amount", ""),
            performed_by=request.user,
            reference=request.POST.get("reference", ""),
            notes=request.POST.get("notes", ""),
        )
        message = "Deposit recorded"
        error = None
    except ValidationError as exc:
        message = None
        error = _format_problem(exc)

    refreshed = get_object_or_404(savings_accounts_for_user(request.user), pk=account.pk)
    return _page("Savings account detail", _account_detail_markup(refreshed, message, error))


@login_required
@require_POST
def account_withdraw(request, pk):
    if request.user.role not in CASH_ROLES:
        return HttpResponseForbidden("You do not have permission to post withdrawals.")

    account = get_object_or_404(savings_accounts_for_user(request.user), pk=pk)
    try:
        SavingsService.withdraw(
            account=account,
            amount=request.POST.get("amount", ""),
            performed_by=request.user,
            reference=request.POST.get("reference", ""),
            notes=request.POST.get("notes", ""),
        )
        message = "Withdrawal recorded"
        error = None
    except ValidationError as exc:
        message = None
        error = _format_problem(exc)

    refreshed = get_object_or_404(savings_accounts_for_user(request.user), pk=account.pk)
    return _page("Savings account detail", _account_detail_markup(refreshed, message, error))
