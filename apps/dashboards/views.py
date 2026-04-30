from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsAdminRole, IsStaffRole
from apps.common.models import StatusChoices
from apps.institutions.models import Branch, Institution
from apps.loans.models import LoanApplication, LoanRepayment, RepaymentSchedule
from apps.loans.selectors import loans_for_user
from apps.notifications.models import Notification
from apps.savings.selectors import savings_accounts_for_user
from apps.transactions.models import Transaction


class ClientDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        clients = clients_for_user(request.user)
        savings = savings_accounts_for_user(request.user)
        loans = loans_for_user(request.user)
        notifications = Notification.objects.filter(user=request.user).order_by("-created_at")

        return Response(
            {
                "client": clients.values(
                    "id",
                    "member_number",
                    "first_name",
                    "last_name",
                    "status",
                    "branch_id",
                    "branch__name",
                ).first(),
                "savings_accounts_count": savings.count(),
                "total_savings_balance": savings.aggregate(total=Sum("balance"))["total"] or 0,
                "active_loan_balance": loans.filter(
                    status__in=[
                        LoanApplication.Status.APPROVED,
                        LoanApplication.Status.DISBURSED,
                    ]
                ).aggregate(total=Sum("principal_balance"))["total"]
                or 0,
                "loan_applications": loans.count(),
                "active_loans": list(
                    loans.filter(status=LoanApplication.Status.DISBURSED)
                    .values(
                        "id",
                        "status",
                        "amount",
                        "principal_balance",
                        "interest_balance",
                        "disbursed_at",
                    )[:5]
                ),
                "recent_applications": list(
                    loans.values(
                        "id",
                        "status",
                        "amount",
                        "term_months",
                        "created_at",
                        "product__name",
                    )[:5]
                ),
                "recent_transactions": list(
                    Transaction.objects.filter(client__user=request.user)
                    .order_by("-created_at")
                    .values(
                        "id",
                        "category",
                        "direction",
                        "amount",
                        "reference",
                        "created_at",
                    )[:5]
                ),
                "notifications": list(
                    notifications.values(
                        "id",
                        "title",
                        "message",
                        "category",
                        "is_read",
                        "created_at",
                    )[:5]
                ),
            }
        )


class StaffDashboardView(APIView):
    permission_classes = [IsStaffRole]

    def get(self, request):
        today = timezone.localdate()
        clients = clients_for_user(request.user)
        savings = savings_accounts_for_user(request.user)
        loans = loans_for_user(request.user)
        loan_ids = loans.values_list("id", flat=True)
        overdue_loans = loans.filter(
            status=LoanApplication.Status.DISBURSED,
            schedule__due_date__lt=today,
            schedule__is_paid=False,
        ).distinct()

        transaction_scope = Transaction.objects.filter(id__in=Transaction.objects.filter(
            branch_id=request.user.branch_id if request.user.branch_id else None
        ).values("id"))
        if request.user.role == "super_admin":
            transaction_scope = Transaction.objects.all()
        elif request.user.branch_id:
            transaction_scope = Transaction.objects.filter(branch_id=request.user.branch_id)
        elif request.user.institution_id:
            transaction_scope = Transaction.objects.filter(institution_id=request.user.institution_id)
        else:
            transaction_scope = Transaction.objects.none()

        todays_transactions = transaction_scope.filter(created_at__date=today)
        todays_deposits = todays_transactions.filter(
            category=Transaction.Category.SAVINGS_DEPOSIT
        ).aggregate(total=Sum("amount"))["total"] or 0
        todays_withdrawals = todays_transactions.filter(
            category=Transaction.Category.SAVINGS_WITHDRAWAL
        ).aggregate(total=Sum("amount"))["total"] or 0
        todays_repayments = todays_transactions.filter(
            category=Transaction.Category.LOAN_REPAYMENT
        ).aggregate(total=Sum("amount"))["total"] or 0

        repayments_collected = (
            LoanRepayment.objects.filter(loan_id__in=loan_ids).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        return Response(
            {
                "clients_count": clients.count(),
                "active_clients": clients.filter(status=StatusChoices.ACTIVE).count(),
                "savings_accounts_count": savings.count(),
                "total_savings_balance": savings.aggregate(total=Sum("balance"))["total"] or 0,
                "pending_loan_applications": loans.filter(
                    status__in=[
                        LoanApplication.Status.SUBMITTED,
                        LoanApplication.Status.UNDER_REVIEW,
                    ]
                ).count(),
                "recommended_loans": loans.filter(
                    status=LoanApplication.Status.RECOMMENDED
                ).count(),
                "approved_loans": loans.filter(status=LoanApplication.Status.APPROVED).count(),
                "active_loans": loans.filter(status=LoanApplication.Status.DISBURSED).count(),
                "overdue_loans": overdue_loans.count(),
                "portfolio_balance": loans.aggregate(total=Sum("principal_balance"))["total"] or 0,
                "repayments_collected": repayments_collected,
                "todays_deposits": todays_deposits,
                "todays_withdrawals": todays_withdrawals,
                "todays_repayments": todays_repayments,
                "recent_transactions": list(
                    transaction_scope.order_by("-created_at").values(
                        "id",
                        "category",
                        "direction",
                        "amount",
                        "reference",
                        "created_at",
                    )[:5]
                ),
            }
        )


class AdminDashboardView(StaffDashboardView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        base_response = super().get(request).data

        institutions = Institution.objects.all()
        branches = Branch.objects.all()
        if request.user.role != "super_admin" and request.user.institution_id:
            institutions = institutions.filter(pk=request.user.institution_id)
            branches = branches.filter(institution_id=request.user.institution_id)

        base_response.update(
            {
                "institutions_count": institutions.count(),
                "branches_count": branches.count(),
                "active_branches": branches.filter(status=StatusChoices.ACTIVE).count(),
            }
        )
        return Response(base_response)
