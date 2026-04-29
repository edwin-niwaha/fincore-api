from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from apps.accounting.selectors import trial_balance_data_for_user
from apps.common.permissions import IsAccountingRole, IsStaffRole
from apps.loans.selectors import loans_for_user
from apps.savings.selectors import savings_accounts_for_user


class FinancialReportViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffRole]

    def get_permissions(self):
        if getattr(self, "action", None) == "trial_balance":
            return [IsAccountingRole()]
        return [permission() for permission in self.permission_classes]

    @action(detail=False, methods=["get"], url_path="savings-balances")
    def savings_balances(self, request):
        qs = savings_accounts_for_user(request.user)
        return response.Response(
            {
                "total_balance": qs.aggregate(total=Sum("balance"))["total"] or 0,
                "accounts": qs.count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="loan-portfolio")
    def loan_portfolio(self, request):
        qs = loans_for_user(request.user)
        return response.Response(
            {
                "principal_outstanding": qs.aggregate(total=Sum("principal_balance"))["total"]
                or 0,
                "loans": qs.count(),
                "pending": qs.filter(status="pending").count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = parse_date(as_of_raw) if as_of_raw else timezone.localdate()
        if as_of_raw and as_of is None:
            raise ValidationError({"as_of": ["Use YYYY-MM-DD for the as_of filter."]})

        data = trial_balance_data_for_user(
            request.user,
            institution_id=request.query_params.get("institution") or None,
            branch_id=request.query_params.get("branch") or None,
            as_of=as_of,
        )
        return response.Response(
            {
                "generated_at": timezone.now(),
                "as_of": as_of,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "rows": data["rows"],
                "totals": {
                    "debit": data["total_debit"],
                    "credit": data["total_credit"],
                    "difference": data["difference"],
                },
            }
        )

    @action(detail=False, methods=["get"], url_path="income-statement")
    def income_statement(self, request):
        return response.Response(
            {
                "detail": (
                    "Income statement endpoint placeholder. Connect to ledger account "
                    "type aggregation before production."
                )
            }
        )

    @action(detail=False, methods=["get"], url_path="balance-sheet")
    def balance_sheet(self, request):
        return response.Response(
            {
                "detail": (
                    "Balance sheet endpoint placeholder. Connect to asset/liability/equity "
                    "aggregation before production."
                )
            }
        )
