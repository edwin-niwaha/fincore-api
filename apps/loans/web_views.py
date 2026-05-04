from html import escape

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from rest_framework.exceptions import ValidationError

from apps.users.models import CustomUser

from .models import LoanApplication
from .selectors import loan_products_for_user, loans_for_user
from .services import LoanService

APPROVER_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
}
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
      .muted {{ color: #64748b; }}
      .badge {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 999px; background: #e2e8f0; font-size: 0.85rem; font-weight: 700; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ text-align: left; padding: 0.6rem; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
      form {{ display: grid; gap: 0.75rem; }}
      input, textarea {{ width: 100%; padding: 0.7rem; border-radius: 0.7rem; border: 1px solid #cbd5e1; }}
      button {{ padding: 0.7rem 1rem; border-radius: 0.7rem; border: 0; background: #127D61; color: white; font-weight: 700; cursor: pointer; }}
      a.button {{ display: inline-block; padding: 0.7rem 1rem; border-radius: 0.7rem; background: #127D61; color: white; font-weight: 700; text-decoration: none; }}
      .alert {{ padding: 0.85rem 1rem; border-radius: 0.85rem; background: #ecfccb; color: #365314; }}
      .error {{ padding: 0.85rem 1rem; border-radius: 0.85rem; background: #fef2f2; color: #991b1b; }}
    </style>
  </head>
  <body>
    <div class="stack">
      {body}
    </div>
  </body>
</html>""",
        content_type="text/html; charset=utf-8",
    )


def _loan_detail_markup(loan, user, message=None, error=None):
    schedule_rows = list(loan.schedule.order_by("due_date", "created_at"))
    repayments = list(loan.repayments.order_by("-created_at"))
    can_approve = user.role in APPROVER_ROLES and loan.status in {
        LoanApplication.Status.RECOMMENDED,
        LoanApplication.Status.APPRAISED,
    }
    can_disburse = user.role in CASH_ROLES and loan.status == LoanApplication.Status.APPROVED
    can_repay = user.role in CASH_ROLES and loan.status == LoanApplication.Status.DISBURSED

    actions = []
    if can_approve:
        actions.append(
            f"""
            <form method="post" action="{escape(reverse('loans_web:application-approve', kwargs={'pk': loan.pk}))}">
              <button type="submit">Approve loan</button>
            </form>
            """
        )
    if can_disburse:
        actions.append(
            f"""
            <form method="post" action="{escape(reverse('loans_web:application-disburse', kwargs={'pk': loan.pk}))}">
              <input name="reference" placeholder="Disbursement reference" required />
              <button type="submit">Disburse loan</button>
            </form>
            """
        )
    if can_repay:
        actions.append(
            f"""
            <form method="post" action="{escape(reverse('loans_web:application-repay', kwargs={'pk': loan.pk}))}">
              <p><strong>Record repayment</strong></p>
              <input name="amount" placeholder="Amount" required />
              <input name="reference" placeholder="Repayment reference" required />
              <button type="submit">Record repayment</button>
            </form>
            """
        )

    message_block = f'<div class="alert">{escape(message)}</div>' if message else ""
    error_block = f'<div class="error">{escape(error)}</div>' if error else ""
    schedule_markup = "".join(
        f"""
        <tr>
          <td>{escape(str(row.due_date))}</td>
          <td>{row.principal_due:.2f}</td>
          <td>{row.interest_due:.2f}</td>
          <td>{row.paid_amount:.2f}</td>
        </tr>
        """
        for row in schedule_rows
    ) or '<tr><td colspan="4">No schedule available.</td></tr>'
    repayment_markup = "".join(
        f"""
        <tr>
          <td>{escape(repayment.reference)}</td>
          <td>{repayment.amount:.2f}</td>
          <td>{repayment.remaining_balance_after:.2f}</td>
        </tr>
        """
        for repayment in repayments
    ) or '<tr><td colspan="3">No repayments recorded.</td></tr>'

    return f"""
      <div class="card">
        <h1>{escape(loan.product.name)} application</h1>
        <p class="muted">{escape(loan.client.member_number)} | {escape(loan.client.first_name)} {escape(loan.client.last_name)}</p>
        <p><span class="badge">{escape(loan.get_status_display())}</span></p>
        <p>Outstanding balance: {(loan.principal_balance + loan.interest_balance):.2f}</p>
        {message_block}
        {error_block}
      </div>
      <div class="card">
        <h2>Repayment schedule</h2>
        <table>
          <thead><tr><th>Due date</th><th>Principal</th><th>Interest</th><th>Paid</th></tr></thead>
          <tbody>{schedule_markup}</tbody>
        </table>
      </div>
      <div class="card">
        <h2>Repayments</h2>
        <table>
          <thead><tr><th>Reference</th><th>Amount</th><th>Remaining</th></tr></thead>
          <tbody>{repayment_markup}</tbody>
        </table>
      </div>
      <div class="card">
        <h2>Actions</h2>
        {' '.join(actions) if actions else '<p class="muted">No actions available for your role or the current loan status.</p>'}
      </div>
    """


@login_required
@require_GET
def product_list(request):
    products = loan_products_for_user(request.user)
    rows = "".join(
        f"""
        <tr>
          <td>{escape(product.name)}</td>
          <td>{escape(product.code)}</td>
          <td>{product.min_amount:.2f}</td>
          <td>{product.max_amount:.2f}</td>
        </tr>
        """
        for product in products
    ) or '<tr><td colspan="4">No loan products available.</td></tr>'

    return _page(
        "Loan products",
        f"""
        <div class="card">
          <h1>Loan products</h1>
          <table>
            <thead><tr><th>Name</th><th>Code</th><th>Minimum</th><th>Maximum</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """,
    )


@login_required
@require_GET
def application_list(request):
    loans = loans_for_user(request.user)
    rows = "".join(
        f"""
        <tr>
          <td>{escape(loan.client.member_number)}</td>
          <td>{escape(loan.product.name)}</td>
          <td>{loan.amount:.2f}</td>
          <td>{escape(loan.get_status_display())}</td>
          <td><a class="button" href="{escape(reverse('loans_web:application-detail', kwargs={'pk': loan.pk}))}">Open detail</a></td>
        </tr>
        """
        for loan in loans
    ) or '<tr><td colspan="5">No loan applications available.</td></tr>'

    return _page(
        "Loan applications",
        f"""
        <div class="card">
          <h1>Loan applications</h1>
          <table>
            <thead><tr><th>Member</th><th>Product</th><th>Amount</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """,
    )


@login_required
@require_GET
def application_detail(request, pk):
    loan = get_object_or_404(loans_for_user(request.user), pk=pk)
    return _page("Loan detail", _loan_detail_markup(loan, request.user))


@login_required
@require_POST
def application_approve(request, pk):
    if request.user.role not in APPROVER_ROLES:
        return HttpResponseForbidden("You do not have permission to approve loans.")

    loan = get_object_or_404(loans_for_user(request.user), pk=pk)
    try:
        loan = LoanService.approve(loan=loan, user=request.user)
        message = "Loan approved"
        error = None
    except ValidationError as exc:
        message = None
        error = _format_problem(exc)

    refreshed = get_object_or_404(loans_for_user(request.user), pk=loan.pk)
    return _page("Loan detail", _loan_detail_markup(refreshed, request.user, message, error))


@login_required
@require_POST
def application_disburse(request, pk):
    if request.user.role not in CASH_ROLES:
        return HttpResponseForbidden("You do not have permission to disburse loans.")

    loan = get_object_or_404(loans_for_user(request.user), pk=pk)
    try:
        loan = LoanService.disburse(
            loan=loan,
            user=request.user,
            reference=request.POST.get("reference", ""),
        )
        message = "Loan disbursed"
        error = None
    except ValidationError as exc:
        message = None
        error = _format_problem(exc)

    refreshed = get_object_or_404(loans_for_user(request.user), pk=loan.pk)
    return _page("Loan detail", _loan_detail_markup(refreshed, request.user, message, error))


@login_required
@require_POST
def application_repay(request, pk):
    if request.user.role not in CASH_ROLES:
        return HttpResponseForbidden("You do not have permission to record repayments.")

    loan = get_object_or_404(loans_for_user(request.user), pk=pk)
    try:
        LoanService.repay(
            loan=loan,
            amount=request.POST.get("amount", ""),
            reference=request.POST.get("reference", ""),
            received_by=request.user,
        )
        message = "Repayment recorded"
        error = None
    except ValidationError as exc:
        message = None
        error = _format_problem(exc)

    refreshed = get_object_or_404(loans_for_user(request.user), pk=loan.pk)
    return _page("Loan detail", _loan_detail_markup(refreshed, request.user, message, error))
