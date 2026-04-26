from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsAdminRole, IsStaffRole
from apps.loans.selectors import loans_for_user
from apps.savings.selectors import savings_accounts_for_user
from apps.transactions.models import Transaction

class ClientDashboardView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        clients = clients_for_user(request.user)
        savings = savings_accounts_for_user(request.user)
        loans = loans_for_user(request.user)
        return Response({
            "client": clients.values("id", "member_number", "first_name", "last_name", "status").first(),
            "total_savings_balance": savings.aggregate(total=Sum("balance"))["total"] or 0,
            "active_loan_balance": loans.aggregate(total=Sum("principal_balance"))["total"] or 0,
            "loan_applications": loans.count(),
            "recent_transactions": list(Transaction.objects.filter(client__user=request.user).order_by("-created_at").values("id", "category", "direction", "amount", "reference", "created_at")[:5]),
        })

class StaffDashboardView(APIView):
    permission_classes = [IsStaffRole]
    def get(self, request):
        clients = clients_for_user(request.user)
        savings = savings_accounts_for_user(request.user)
        loans = loans_for_user(request.user)
        return Response({
            "clients_count": clients.count(),
            "savings_accounts_count": savings.count(),
            "total_savings_balance": savings.aggregate(total=Sum("balance"))["total"] or 0,
            "pending_loans": loans.filter(status="pending").count(),
            "active_loan_principal": loans.aggregate(total=Sum("principal_balance"))["total"] or 0,
        })

class AdminDashboardView(StaffDashboardView):
    permission_classes = [IsAdminRole]
