from html import escape

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .selectors import transactions_for_user


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
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ text-align: left; padding: 0.6rem; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
    </style>
  </head>
  <body>
    <div class="stack">{body}</div>
  </body>
</html>""",
        content_type="text/html; charset=utf-8",
    )


@login_required
@require_GET
def ledger(request):
    queryset = transactions_for_user(request.user)

    category = request.GET.get("category", "").strip()
    if category:
        queryset = queryset.filter(category=category)

    direction = request.GET.get("direction", "").strip()
    if direction:
        queryset = queryset.filter(direction=direction)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)

    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    transactions = list(queryset)
    selected = None
    selected_id = request.GET.get("selected", "").strip()
    if selected_id:
        selected = get_object_or_404(queryset, pk=selected_id)

    rows = "".join(
        f"""
        <tr>
          <td>{escape(transaction.reference)}</td>
          <td>{escape(transaction.category_label)}</td>
          <td>{escape(transaction.get_direction_display())}</td>
          <td>{transaction.amount:.2f}</td>
          <td>{escape(transaction.description)}</td>
        </tr>
        """
        for transaction in transactions
    ) or '<tr><td colspan="5">No transactions match the current filters.</td></tr>'

    selected_markup = ""
    if selected is not None:
        selected_markup = f"""
        <div class="card">
          <h2>Detail Drawer</h2>
          <p><strong>{escape(selected.reference)}</strong></p>
          <p>{escape(selected.description)}</p>
          <p class="muted">{escape(selected.category_label)} | {escape(selected.get_direction_display())}</p>
        </div>
        """

    return _page(
        "Transaction ledger",
        f"""
        <div class="card">
          <h1>Transaction ledger with export-ready detail</h1>
          <p class="muted">Print / PDF ready</p>
          <table>
            <thead><tr><th>Reference</th><th>Category</th><th>Direction</th><th>Amount</th><th>Description</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        {selected_markup}
        """,
    )
