from rest_framework import decorators, response, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.audit.services import AuditService
from apps.clients.selectors import clients_for_user
from apps.users.models import CustomUser

from .models import LoanRepayment
from .selectors import loan_products_for_user, loans_for_user
from .serializers import (
    LoanActionSerializer,
    LoanApplicationDetailSerializer,
    LoanApplicationSerializer,
    LoanProductSerializer,
    LoanRepaymentCreateSerializer,
    LoanRepaymentSerializer,
    RepaymentScheduleSerializer,
)
from .services import LoanService

LOAN_PRODUCT_MANAGE_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
    CustomUser.Role.ACCOUNTANT,
}
LOAN_CREATE_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
    CustomUser.Role.LOAN_OFFICER,
}
LOAN_REVIEW_ROLES = LoanService.LOAN_OFFICER_ROLES
LOAN_APPROVER_ROLES = LoanService.APPROVER_ROLES
LOAN_REJECTION_ROLES = LoanService.LOAN_OFFICER_ROLES | LoanService.APPROVER_ROLES
CASH_COLLECTION_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
    CustomUser.Role.ACCOUNTANT,
    CustomUser.Role.TELLER,
}


def _has_role(user, roles):
    return bool(user and user.is_authenticated and user.role in roles)


class LoanProductViewSet(viewsets.ModelViewSet):
    serializer_class = LoanProductSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["institution", "is_active"]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at", "updated_at"]
    ordering = ["institution__name", "code", "name"]

    def get_queryset(self):
        return loan_products_for_user(self.request.user)

    def _validate_scope(self, serializer):
        institution = serializer.validated_data.get(
            "institution",
            getattr(serializer.instance, "institution", None),
        )
        user = self.request.user

        if user.role == CustomUser.Role.SUPER_ADMIN:
            return

        if not user.institution_id or not institution or institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage loan products outside your institution.")

    def _require_manage_role(self):
        if not _has_role(self.request.user, LOAN_PRODUCT_MANAGE_ROLES):
            raise PermissionDenied("You do not have permission to manage loan products.")

    def perform_create(self, serializer):
        self._require_manage_role()
        self._validate_scope(serializer)
        product = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="loan.product.create",
            target=str(product.id),
            metadata={"code": product.code, "institution_id": str(product.institution_id)},
        )

    def perform_update(self, serializer):
        self._require_manage_role()
        self._validate_scope(serializer)
        product = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="loan.product.update",
            target=str(product.id),
            metadata={"code": product.code, "is_active": product.is_active},
        )

    def perform_destroy(self, instance):
        self._require_manage_role()
        if instance.loanapplication_set.exists():
            raise ValidationError("Loan products with applications cannot be deleted.")

        product_id = str(instance.id)
        code = instance.code
        instance.delete()
        AuditService.log(
            user=self.request.user,
            action="loan.product.delete",
            target=product_id,
            metadata={"code": code},
        )


class LoanApplicationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_fields = ["client", "product", "status", "client__branch", "client__institution"]
    search_fields = [
        "client__member_number",
        "client__first_name",
        "client__last_name",
        "purpose",
        "product__name",
        "product__code",
        "disbursement_reference",
    ]
    ordering_fields = ["created_at", "updated_at", "amount", "term_months", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return loans_for_user(self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LoanApplicationDetailSerializer
        return LoanApplicationSerializer

    def _validate_scope(self, serializer):
        client = serializer.validated_data.get(
            "client",
            getattr(serializer.instance, "client", None),
        )
        product = serializer.validated_data.get(
            "product",
            getattr(serializer.instance, "product", None),
        )
        user = self.request.user

        if client and not clients_for_user(user).filter(pk=client.pk).exists():
            raise PermissionDenied("You cannot manage a loan application outside your scope.")

        if product and not loan_products_for_user(user).filter(pk=product.pk).exists():
            raise PermissionDenied("You cannot use a loan product outside your scope.")

        if user.role == CustomUser.Role.CLIENT and client and client.user_id != user.id:
            raise PermissionDenied("Client users can only manage their own loan applications.")

    def _require_roles(self, roles, message):
        if not _has_role(self.request.user, roles):
            raise PermissionDenied(message)

    def perform_create(self, serializer):
        user = self.request.user
        if user.role != CustomUser.Role.CLIENT:
            self._require_roles(
                LOAN_CREATE_ROLES,
                "You do not have permission to create loan applications.",
            )

        self._validate_scope(serializer)
        loan = serializer.save()
        submit_requested = user.role == CustomUser.Role.CLIENT or str(
            self.request.data.get("submit", "")
        ).lower() in {"1", "true", "yes", "on"}
        loan = LoanService.initialize_new_application(
            loan=loan,
            created_by=user,
            submit=submit_requested,
        )
        serializer.instance = loan

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        loan = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="loan.application.update",
            target=str(loan.id),
            metadata={"status": loan.status, "amount": str(loan.amount)},
        )

    def perform_destroy(self, instance):
        if instance.status != instance.Status.DRAFT:
            raise ValidationError("Only draft loan applications can be deleted.")

        loan_id = str(instance.id)
        instance.delete()
        AuditService.log(
            user=self.request.user,
            action="loan.application.delete",
            target=loan_id,
        )

    @decorators.action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        loan = self.get_object()
        if request.user.role != CustomUser.Role.CLIENT:
            self._require_roles(
                LOAN_CREATE_ROLES,
                "You do not have permission to submit loan applications.",
            )
        loan = LoanService.submit(loan=loan, user=request.user)
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"], url_path="start-review")
    def start_review(self, request, pk=None):
        self._require_roles(
            LOAN_REVIEW_ROLES,
            "You do not have permission to review loan applications.",
        )
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.start_review(
            loan=self.get_object(),
            user=request.user,
            comment=serializer.validated_data.get("comment", ""),
        )
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"])
    def recommend(self, request, pk=None):
        self._require_roles(
            LOAN_REVIEW_ROLES,
            "You do not have permission to recommend loan applications.",
        )
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.recommend(
            loan=self.get_object(),
            user=request.user,
            comment=serializer.validated_data.get("comment", ""),
        )
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        self._require_roles(
            LOAN_APPROVER_ROLES,
            "You do not have permission to approve loan applications.",
        )
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.approve(
            loan=self.get_object(),
            user=request.user,
            comment=serializer.validated_data.get("comment", ""),
            override=serializer.validated_data.get("override", False),
        )
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        self._require_roles(
            LOAN_REJECTION_ROLES,
            "You do not have permission to reject loan applications.",
        )
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.reject(
            loan=self.get_object(),
            user=request.user,
            reason=serializer.validated_data.get("reason", ""),
            comment=serializer.validated_data.get("comment", ""),
        )
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"])
    def disburse(self, request, pk=None):
        self._require_roles(
            CASH_COLLECTION_ROLES,
            "You do not have permission to disburse loans.",
        )
        serializer = LoanActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = LoanService.disburse(
            loan=self.get_object(),
            user=request.user,
            reference=serializer.validated_data.get("reference") or f"DISB-{pk}",
            disbursement_method=serializer.validated_data.get("disbursement_method", ""),
        )
        return response.Response(self.get_serializer(loan).data)

    @decorators.action(detail=True, methods=["post"])
    def repay(self, request, pk=None):
        self._require_roles(
            CASH_COLLECTION_ROLES,
            "You do not have permission to record loan repayments.",
        )
        serializer = LoanRepaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repayment = LoanService.repay(
            loan=self.get_object(),
            received_by=request.user,
            **serializer.validated_data,
        )
        return response.Response(LoanRepaymentSerializer(repayment).data, status=201)

    @decorators.action(detail=True, methods=["get"])
    def schedule(self, request, pk=None):
        queryset = self.get_object().schedule.order_by("due_date", "created_at")
        serializer = RepaymentScheduleSerializer(queryset, many=True)
        return response.Response(serializer.data)

    @decorators.action(detail=True, methods=["get"])
    def repayments(self, request, pk=None):
        queryset = self.get_object().repayments.select_related("received_by").order_by(
            "-created_at"
        )
        page = self.paginate_queryset(queryset)
        serializer = LoanRepaymentSerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)


class LoanRepaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LoanRepaymentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["loan", "loan__client", "loan__client__branch", "loan__client__institution"]
    search_fields = [
        "reference",
        "loan__client__member_number",
        "loan__client__first_name",
        "loan__client__last_name",
    ]
    ordering_fields = ["created_at", "amount", "reference"]
    ordering = ["-created_at"]

    def get_queryset(self):
        loan_ids = loans_for_user(self.request.user).values_list("id", flat=True)
        return (
            LoanRepayment.objects.filter(loan_id__in=loan_ids)
            .select_related("loan", "loan__client", "received_by")
            .order_by("-created_at")
        )
