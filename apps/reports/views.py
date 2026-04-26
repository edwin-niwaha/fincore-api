from django.db.models import Sum
from rest_framework import response, viewsets
from rest_framework.decorators import action
from apps.common.permissions import IsStaffRole
from apps.loans.selectors import loans_for_user
from apps.savings.selectors import savings_accounts_for_user

class FinancialReportViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffRole]

    @action(detail=False, methods=["get"], url_path="savings-balances")
    def savings_balances(self, request):
        qs = savings_accounts_for_user(request.user)
        return response.Response({"total_balance": qs.aggregate(total=Sum("balance"))["total"] or 0, "accounts": qs.count()})

    @action(detail=False, methods=["get"], url_path="loan-portfolio")
    def loan_portfolio(self, request):
        qs = loans_for_user(request.user)
        return response.Response({"principal_outstanding": qs.aggregate(total=Sum("principal_balance"))["total"] or 0, "loans": qs.count(), "pending": qs.filter(status="pending").count()})

    @action(detail=False, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request):
        return response.Response({"detail": "Trial balance endpoint placeholder. Connect to JournalEntryLine aggregation before production."})

    @action(detail=False, methods=["get"], url_path="income-statement")
    def income_statement(self, request):
        return response.Response({"detail": "Income statement endpoint placeholder. Connect to ledger account type aggregation before production."})

    @action(detail=False, methods=["get"], url_path="balance-sheet")
    def balance_sheet(self, request):
        return response.Response({"detail": "Balance sheet endpoint placeholder. Connect to asset/liability/equity aggregation before production."})
