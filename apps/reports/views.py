from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from apps.accounting.selectors import (
    balance_sheet_data_for_user,
    general_ledger_data_for_user,
    trial_balance_data_for_user,
)
from apps.common.permissions import IsAccountingRole, IsStaffRole
from apps.loans.models import LoanApplication
from apps.loans.selectors import loans_for_user
from apps.savings.selectors import savings_accounts_for_user


class FinancialReportViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffRole]

    def get_permissions(self):
        if getattr(self, "action", None) in {
            "trial_balance",
            "general_ledger",
            "balance_sheet",
        }:
            return [IsAccountingRole()]
        return [permission() for permission in self.permission_classes]

    def _parse_date(self, value, *, field_name):
        if not value:
            return None

        parsed = parse_date(value)
        if parsed is None:
            raise ValidationError({field_name: [f"Use YYYY-MM-DD for {field_name}."]})
        return parsed

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
                "interest_outstanding": qs.aggregate(total=Sum("interest_balance"))["total"] or 0,
                "portfolio_balance": (
                    qs.aggregate(total=Sum("principal_balance"))["total"] or 0
                )
                + (qs.aggregate(total=Sum("interest_balance"))["total"] or 0),
                "loans": qs.count(),
                "pending": qs.filter(
                    status__in=[
                        LoanApplication.Status.SUBMITTED,
                        LoanApplication.Status.UNDER_REVIEW,
                    ]
                ).count(),
                "recommended": qs.filter(status=LoanApplication.Status.RECOMMENDED).count(),
                "approved": qs.filter(status=LoanApplication.Status.APPROVED).count(),
                "active": qs.filter(status=LoanApplication.Status.DISBURSED).count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = self._parse_date(as_of_raw, field_name="as_of") if as_of_raw else timezone.localdate()

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

    @action(detail=False, methods=["get"], url_path="general-ledger")
    def general_ledger(self, request):
        rows = general_ledger_data_for_user(
            request.user,
            institution_id=request.query_params.get("institution") or None,
            branch_id=request.query_params.get("branch") or None,
            account_id=request.query_params.get("account") or None,
            date_from=self._parse_date(
                request.query_params.get("date_from"),
                field_name="date_from",
            ),
            date_to=self._parse_date(
                request.query_params.get("date_to"),
                field_name="date_to",
            ),
        )
        return response.Response(
            {
                "generated_at": timezone.now(),
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "account": request.query_params.get("account"),
                "rows": rows,
            }
        )

    @action(detail=False, methods=["get"], url_path="income-statement")
    def income_statement(self, request):
        return response.Response(
            {
                "detail": (
                    "Income statement is not yet fully implemented. Use trial balance "
                    "and balance sheet for current accounting verification."
                )
            }
        )

    @action(detail=False, methods=["get"], url_path="balance-sheet")
    def balance_sheet(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = self._parse_date(as_of_raw, field_name="as_of") if as_of_raw else timezone.localdate()

        data = balance_sheet_data_for_user(
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
                "sections": data["sections"],
                "totals": data["totals"],
            }
        )
