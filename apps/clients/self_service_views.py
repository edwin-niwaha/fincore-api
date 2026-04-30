from django.db.models import Q, Sum
from django.utils.dateparse import parse_date
from rest_framework import decorators, response, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.audit.services import AuditService
from apps.common.models import StatusChoices
from apps.loans.models import LoanApplication, LoanProduct, LoanRepayment
from apps.loans.selectors import loans_for_user
from apps.loans.serializers import (
    LoanApplicationDetailSerializer,
    LoanApplicationSerializer,
    LoanProductSerializer,
    LoanRepaymentSerializer,
    RepaymentScheduleSerializer,
)
from apps.loans.views import LoanApplicationViewSet, LoanRepaymentViewSet
from apps.notifications.models import Notification
from apps.savings.models import SavingsTransaction
from apps.savings.selectors import savings_accounts_for_user
from apps.savings.serializers import SavingsAccountSerializer, SavingsTransactionSerializer
from apps.savings.views import SavingsTransactionViewSet
from apps.transactions.models import Transaction
from apps.transactions.views import TransactionViewSet
from apps.users.models import CustomUser

from .models import Client
from .self_service_serializers import (
    SelfServiceLoanStatementRepaymentSerializer,
    SelfServiceNotificationSerializer,
    SelfServiceProfileSerializer,
    SelfServiceSavingsStatementEntrySerializer,
    SelfServiceUnifiedTransactionSerializer,
)
from .serializers import ClientSelfServiceUpdateSerializer, format_decimal


def parse_optional_date_param(request, field_name):
    value = request.query_params.get(field_name)
    if not value:
        return None

    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError({field_name: ["Use the YYYY-MM-DD format."]})
    return parsed


class SelfServiceClientMixin:
    permission_classes = [IsAuthenticated]

    def get_linked_client(self):
        if hasattr(self, "_linked_client"):
            return self._linked_client

        user = self.request.user
        if not user or not user.is_authenticated or user.role != CustomUser.Role.CLIENT:
            raise PermissionDenied("Only client self-service users can access this endpoint.")

        try:
            linked_client = user.client_profile
        except Client.DoesNotExist as exc:
            raise PermissionDenied(
                "Your user account is not linked to a client profile."
            ) from exc

        self._linked_client = Client.objects.select_related("institution", "branch", "user").get(
            pk=linked_client.pk
        )
        return self._linked_client


class SelfServiceProfileView(SelfServiceClientMixin, APIView):
    def get(self, request):
        serializer = SelfServiceProfileSerializer(self.get_linked_client())
        return response.Response(serializer.data)

    def patch(self, request):
        client = self.get_linked_client()
        serializer = ClientSelfServiceUpdateSerializer(
            client,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        client = serializer.save(updated_by=request.user)
        AuditService.log(
            user=request.user,
            action="client.self_service_update",
            target=str(client.id),
            metadata={"member_number": client.member_number},
        )
        refreshed_client = Client.objects.select_related("institution", "branch", "user").get(
            pk=client.pk
        )
        return response.Response(SelfServiceProfileSerializer(refreshed_client).data)


class SelfServiceDashboardView(SelfServiceClientMixin, APIView):
    def get(self, request):
        client = self.get_linked_client()
        savings_accounts = savings_accounts_for_user(request.user).filter(client=client)
        loan_applications = loans_for_user(request.user).filter(client=client)
        visible_loans = loan_applications.filter(
            status__in=[
                LoanApplication.Status.APPROVED,
                LoanApplication.Status.DISBURSED,
                LoanApplication.Status.CLOSED,
            ]
        )
        active_loans = loan_applications.filter(
            status__in=[
                LoanApplication.Status.APPROVED,
                LoanApplication.Status.DISBURSED,
            ]
        )
        pending_applications = loan_applications.filter(
            status__in=[
                LoanApplication.Status.DRAFT,
                LoanApplication.Status.SUBMITTED,
                LoanApplication.Status.UNDER_REVIEW,
                LoanApplication.Status.RECOMMENDED,
            ]
        )
        repayments = (
            LoanRepayment.objects.filter(loan__client=client)
            .select_related("loan", "received_by")
            .order_by("-created_at")
        )
        notifications = Notification.objects.filter(user=request.user).order_by("-created_at")
        recent_savings_transactions = (
            SavingsTransaction.objects.filter(account__client=client)
            .select_related(
                "performed_by",
                "account__client__branch",
                "account__client__institution",
            )
            .order_by("-created_at")[:5]
        )

        return response.Response(
            {
                "profile_summary": SelfServiceProfileSerializer(client).data,
                "total_savings_balance": format_decimal(
                    savings_accounts.aggregate(total=Sum("balance"))["total"]
                ),
                "active_savings_accounts_count": savings_accounts.filter(
                    status=StatusChoices.ACTIVE
                ).count(),
                "active_loans_count": active_loans.count(),
                "pending_loan_applications_count": pending_applications.count(),
                "outstanding_loan_balance": format_decimal(
                    sum(
                        (
                            loan.principal_balance + loan.interest_balance
                            for loan in visible_loans
                        ),
                        0,
                    )
                ),
                "total_repayments_made": format_decimal(
                    repayments.aggregate(total=Sum("amount"))["total"]
                ),
                "recent_savings_transactions": SavingsTransactionSerializer(
                    recent_savings_transactions,
                    many=True,
                ).data,
                "recent_loan_applications": LoanApplicationSerializer(
                    loan_applications.order_by("-created_at")[:5],
                    many=True,
                ).data,
                "recent_repayments": LoanRepaymentSerializer(
                    repayments[:5],
                    many=True,
                ).data,
                "unread_notifications_count": notifications.filter(is_read=False).count(),
                "recent_notifications": SelfServiceNotificationSerializer(
                    notifications[:5],
                    many=True,
                ).data,
            }
        )


class SelfServiceSavingsSummaryView(SelfServiceClientMixin, APIView):
    def get(self, request):
        client = self.get_linked_client()
        savings_accounts = savings_accounts_for_user(request.user).filter(client=client)
        recent_transactions = (
            SavingsTransaction.objects.filter(account__client=client)
            .select_related("account", "performed_by")
            .order_by("-created_at")[:5]
        )

        return response.Response(
            {
                "client_id": str(client.id),
                "client_name": f"{client.first_name} {client.last_name}".strip(),
                "member_number": client.member_number,
                "currency": client.institution.currency if client.institution_id else None,
                "total_balance": format_decimal(
                    savings_accounts.aggregate(total=Sum("balance"))["total"]
                ),
                "account_count": savings_accounts.count(),
                "accounts": SavingsAccountSerializer(savings_accounts, many=True).data,
                "recent_activity": SelfServiceSavingsStatementEntrySerializer(
                    recent_transactions,
                    many=True,
                ).data,
            }
        )


class SelfServiceSavingsStatementView(SelfServiceClientMixin, APIView):
    def get(self, request):
        client = self.get_linked_client()
        date_from = parse_optional_date_param(request, "date_from")
        date_to = parse_optional_date_param(request, "date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                {"date_to": ["End date must be on or after the start date."]}
            )

        savings_accounts = savings_accounts_for_user(request.user).filter(client=client)
        transactions = SavingsTransaction.objects.filter(account__client=client).select_related(
            "account",
            "performed_by",
        )

        account_id = request.query_params.get("account")
        if account_id:
            transactions = transactions.filter(account_id=account_id)

        if date_from:
            transactions = transactions.filter(created_at__date__gte=date_from)
        if date_to:
            transactions = transactions.filter(created_at__date__lte=date_to)

        transactions = transactions.order_by("-created_at")

        return response.Response(
            {
                "client_id": str(client.id),
                "client_name": f"{client.first_name} {client.last_name}".strip(),
                "member_number": client.member_number,
                "currency": client.institution.currency if client.institution_id else None,
                "total_balance": format_decimal(
                    savings_accounts.aggregate(total=Sum("balance"))["total"]
                ),
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "transactions": SelfServiceSavingsStatementEntrySerializer(
                    transactions,
                    many=True,
                ).data,
            }
        )


class SelfServiceSavingsViewSet(SelfServiceClientMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SavingsAccountSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "status": ["exact"],
    }
    search_fields = [
        "account_number",
        "client__member_number",
        "client__first_name",
        "client__last_name",
        "client__phone",
    ]
    ordering_fields = ["created_at", "updated_at", "account_number", "balance", "status"]
    ordering = ["account_number"]

    def get_queryset(self):
        client = self.get_linked_client()
        return savings_accounts_for_user(self.request.user).filter(client=client)


class SelfServiceSavingsTransactionViewSet(
    SelfServiceClientMixin,
    SavingsTransactionViewSet,
):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        client = self.get_linked_client()
        return super().get_queryset().filter(account__client=client)


class SelfServiceLoanProductViewSet(SelfServiceClientMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = LoanProductSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = {"is_active": ["exact"]}
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at", "updated_at"]
    ordering = ["code", "name"]

    def get_queryset(self):
        client = self.get_linked_client()
        return LoanProduct.objects.select_related("institution").filter(
            institution=client.institution,
            is_active=True,
        )


class SelfServiceLoanApplicationViewSet(SelfServiceClientMixin, LoanApplicationViewSet):
    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "status": ["exact"],
        "product": ["exact"],
        "created_at": ["date__gte", "date__lte"],
    }
    search_fields = [
        "purpose",
        "product__name",
        "product__code",
        "disbursement_reference",
    ]

    def get_queryset(self):
        client = self.get_linked_client()
        return loans_for_user(self.request.user).filter(client=client)


class SelfServiceLoanViewSet(SelfServiceClientMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "status": ["exact"],
        "product": ["exact"],
        "disbursed_at": ["date__gte", "date__lte"],
    }
    search_fields = [
        "purpose",
        "product__name",
        "product__code",
        "disbursement_reference",
    ]
    ordering_fields = ["created_at", "updated_at", "amount", "disbursed_at", "status"]
    ordering = ["-disbursed_at", "-created_at"]

    def get_queryset(self):
        client = self.get_linked_client()
        return loans_for_user(self.request.user).filter(
            client=client,
            status__in=[
                LoanApplication.Status.APPROVED,
                LoanApplication.Status.DISBURSED,
                LoanApplication.Status.CLOSED,
            ],
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LoanApplicationDetailSerializer
        return LoanApplicationSerializer


class SelfServiceLoanStatementView(SelfServiceClientMixin, APIView):
    def get(self, request):
        client = self.get_linked_client()
        eligible_loans = (
            loans_for_user(request.user)
            .filter(client=client)
            .filter(
                Q(
                    status__in=[
                        LoanApplication.Status.APPROVED,
                        LoanApplication.Status.DISBURSED,
                        LoanApplication.Status.CLOSED,
                    ]
                )
                | Q(repayment_count__gt=0)
            )
            .distinct()
            .order_by("-disbursed_at", "-approved_at", "-created_at")
        )

        selected_loan = None
        loan_id = request.query_params.get("loan")
        if loan_id:
            selected_loan = eligible_loans.filter(pk=loan_id).first()
            if selected_loan is None:
                raise NotFound("Loan statement not found.")
        else:
            selected_loan = eligible_loans.first()

        repayments = LoanRepayment.objects.none()
        schedule = []
        balances = {
            "principal_balance": format_decimal(0),
            "interest_balance": format_decimal(0),
            "outstanding_balance": format_decimal(0),
            "total_repaid": format_decimal(0),
        }

        if selected_loan is not None:
            repayments = selected_loan.repayments.select_related("received_by").order_by(
                "-created_at"
            )
            schedule = selected_loan.schedule.order_by("due_date", "created_at")
            balances = {
                "principal_balance": format_decimal(selected_loan.principal_balance),
                "interest_balance": format_decimal(selected_loan.interest_balance),
                "outstanding_balance": format_decimal(selected_loan.outstanding_balance),
                "total_repaid": format_decimal(
                    repayments.aggregate(total=Sum("amount"))["total"]
                ),
            }

        return response.Response(
            {
                "currency": client.institution.currency if client.institution_id else None,
                "selected_loan_id": str(selected_loan.id) if selected_loan else None,
                "available_loans": LoanApplicationSerializer(
                    eligible_loans,
                    many=True,
                ).data,
                "loan_summary": (
                    LoanApplicationSerializer(selected_loan).data
                    if selected_loan is not None
                    else None
                ),
                "balances": balances,
                "repayments": SelfServiceLoanStatementRepaymentSerializer(
                    repayments,
                    many=True,
                ).data,
                "repayment_schedule": RepaymentScheduleSerializer(
                    schedule,
                    many=True,
                ).data,
            }
        )


class SelfServiceLoanRepaymentViewSet(SelfServiceClientMixin, LoanRepaymentViewSet):
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "loan": ["exact"],
        "created_at": ["date__gte", "date__lte"],
    }
    search_fields = ["reference", "payment_method", "loan__product__name"]

    def get_queryset(self):
        client = self.get_linked_client()
        return super().get_queryset().filter(loan__client=client)


class SelfServiceTransactionViewSet(SelfServiceClientMixin, TransactionViewSet):
    serializer_class = SelfServiceUnifiedTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        client = self.get_linked_client()
        queryset = super().get_queryset().filter(client=client)

        source = self.request.query_params.get("source", "").strip().lower()
        if source == "savings":
            queryset = queryset.filter(
                category__in=[
                    Transaction.Category.SAVINGS_DEPOSIT,
                    Transaction.Category.SAVINGS_WITHDRAWAL,
                ]
            )
        elif source == "loans":
            queryset = queryset.filter(
                category__in=[
                    Transaction.Category.LOAN_DISBURSEMENT,
                    Transaction.Category.LOAN_REPAYMENT,
                ]
            )

        transaction_type = self.request.query_params.get("type", "").strip().lower()
        if transaction_type:
            queryset = queryset.filter(category=transaction_type)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = list(page) if page is not None else list(queryset)
        references = [row.reference for row in rows]

        savings_by_reference = {
            row.reference: row
            for row in SavingsTransaction.objects.select_related("account").filter(
                reference__in=references
            )
        }
        repayments_by_reference = {
            row.reference: row
            for row in LoanRepayment.objects.select_related("loan").filter(
                reference__in=references
            )
        }
        loans_by_reference = {
            row.disbursement_reference: row
            for row in loans_for_user(request.user).filter(
                disbursement_reference__in=references,
                status__in=[
                    LoanApplication.Status.DISBURSED,
                    LoanApplication.Status.CLOSED,
                ],
            )
            if row.disbursement_reference
        }

        serializer = self.get_serializer(
            rows,
            many=True,
            context={
                **self.get_serializer_context(),
                "savings_by_reference": savings_by_reference,
                "repayments_by_reference": repayments_by_reference,
                "loans_by_reference": loans_by_reference,
            },
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)


class SelfServiceNotificationViewSet(SelfServiceClientMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SelfServiceNotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = {"is_read": ["exact"], "category": ["exact"]}
    search_fields = ["title", "message", "category"]
    ordering_fields = ["created_at", "updated_at", "is_read"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        self.get_linked_client()
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")

    @decorators.action(detail=True, methods=["post", "patch"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read", "updated_at"])
        return response.Response(self.get_serializer(notification).data)

    @decorators.action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return response.Response(
            {"detail": "Notifications marked as read.", "updated": updated},
            status=status.HTTP_200_OK,
        )
