from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import decorators, response, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import AuditService
from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsAdminRole, IsCashRole
from apps.institutions.models import Institution
from apps.users.models import CustomUser

from .models import SavingsPolicy, SavingsTransaction
from .selectors import savings_accounts_for_user
from .serializers import (
    SavingsAccountDetailSerializer,
    SavingsAccountSerializer,
    SavingsOperationSerializer,
    SavingsPolicySerializer,
    SavingsTransactionSerializer,
)
from .services import SavingsService


class SavingsAccountViewSet(viewsets.ModelViewSet):
    filterset_fields = {
        "client": ["exact"],
        "status": ["exact"],
        "client__branch": ["exact"],
        "client__institution": ["exact"],
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
        return savings_accounts_for_user(self.request.user)

    def _get_scoped_account(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SavingsAccountDetailSerializer
        if self.action == "policy":
            return SavingsPolicySerializer
        return SavingsAccountSerializer

    def _policy_institution(self, request):
        institution = getattr(request.user, "institution", None)
        if institution is not None:
            return institution

        client_profile = getattr(request.user, "client_profile", None)
        if client_profile and client_profile.institution_id:
            return client_profile.institution

        if request.user.role == CustomUser.Role.SUPER_ADMIN:
            institution_id = request.query_params.get("institution") or request.data.get("institution")
            if not institution_id:
                raise ValidationError(
                    {"institution": ["Provide an institution id when managing a savings policy as super admin."]}
                )

            institution = Institution.objects.filter(pk=institution_id).first()
            if institution is None:
                raise ValidationError({"institution": ["Institution not found."]})
            return institution

        raise ValidationError(
            {"institution": ["Institution context is required for the savings policy."]}
        )

    def _validate_scope(self, serializer):
        client = serializer.validated_data.get("client", getattr(serializer.instance, "client", None))
        if client and not clients_for_user(self.request.user).filter(pk=client.pk).exists():
            raise PermissionDenied("You cannot manage a savings account outside your scope.")

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        account = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="savings.account.create",
            target=str(account.id),
            metadata={"account_number": account.account_number, "client_id": str(account.client_id)},
        )

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        account = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="savings.account.update",
            target=str(account.id),
            metadata={
                "account_number": account.account_number,
                "client_id": str(account.client_id),
                "status": account.status,
            },
        )

    def perform_destroy(self, instance):
        if instance.transactions.exists():
            raise ValidationError("Savings accounts with transaction history cannot be deleted.")
        if instance.balance > 0:
            raise ValidationError("Savings accounts with a positive balance cannot be deleted.")

        account_id = str(instance.id)
        account_number = instance.account_number
        instance.delete()
        AuditService.log(
            user=self.request.user,
            action="savings.account.delete",
            target=account_id,
            metadata={"account_number": account_number},
        )

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy", "deposit", "withdraw"}:
            return [IsCashRole()]
        if self.action == "policy" and self.request.method not in {"GET", "HEAD", "OPTIONS"}:
            return [IsAdminRole()]
        return super().get_permissions()

    @decorators.action(detail=False, methods=["get", "patch"])
    def policy(self, request):
        institution = self._policy_institution(request)
        policy = SavingsPolicy.current(institution)
        if request.method == "PATCH":
            serializer = SavingsPolicySerializer(policy, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            policy = serializer.save()
            AuditService.log(
                user=request.user,
                action="savings.policy.update",
                target=str(policy.id),
                metadata={
                    "institution_id": str(policy.institution_id),
                    "minimum_balance": str(policy.minimum_balance),
                    "withdrawal_charge": str(policy.withdrawal_charge),
                    "is_active": policy.is_active,
                },
            )
            return response.Response(SavingsPolicySerializer(policy).data)
        return response.Response(SavingsPolicySerializer(policy).data)

    @decorators.action(detail=True, methods=["post"])
    def deposit(self, request, pk=None):
        serializer = SavingsOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction_row = SavingsService.deposit(
            account=self._get_scoped_account(pk),
            performed_by=request.user,
            **serializer.validated_data,
        )
        return response.Response(SavingsTransactionSerializer(transaction_row).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        serializer = SavingsOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction_row = SavingsService.withdraw(
            account=self._get_scoped_account(pk),
            performed_by=request.user,
            **serializer.validated_data,
        )
        return response.Response(SavingsTransactionSerializer(transaction_row).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        queryset = (
            self._get_scoped_account(pk)
            .transactions.select_related(
                "performed_by",
                "account__client__branch",
                "account__client__institution",
            )
            .order_by("-transaction_date", "-created_at")
        )

        transaction_type = request.query_params.get("type")
        if transaction_type:
            queryset = queryset.filter(type=transaction_type)

        search_term = request.query_params.get("search", "").strip()
        if search_term:
            queryset = queryset.filter(reference__icontains=search_term)

        from_date_raw = request.query_params.get("transaction_date__gte")
        to_date_raw = request.query_params.get("transaction_date__lte")

        if from_date_raw:
            from_date = parse_date(from_date_raw)
            if from_date is None:
                raise ValidationError({"transaction_date__gte": ["Use YYYY-MM-DD for the from date filter."]})
            queryset = queryset.filter(transaction_date__gte=from_date)

        if to_date_raw:
            to_date = parse_date(to_date_raw)
            if to_date is None:
                raise ValidationError({"transaction_date__lte": ["Use YYYY-MM-DD for the to date filter."]})
            queryset = queryset.filter(transaction_date__lte=to_date)

        page = self.paginate_queryset(queryset)
        serializer = SavingsTransactionSerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)


class SavingsTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SavingsTransactionSerializer
    filterset_fields = {
        "account": ["exact"],
        "type": ["exact"],
        "account__client": ["exact"],
        "account__client__branch": ["exact"],
        "account__client__institution": ["exact"],
        "transaction_date": ["gte", "lte"],
        "created_at": ["date__gte", "date__lte"],
    }
    search_fields = [
        "reference",
        "account__account_number",
        "account__client__member_number",
        "account__client__first_name",
        "account__client__last_name",
        "account__client__phone",
    ]
    ordering_fields = ["transaction_date", "created_at", "amount", "reference"]
    ordering = ["-transaction_date", "-created_at"]

    def get_queryset(self):
        account_ids = savings_accounts_for_user(self.request.user).values_list("id", flat=True)
        return (
            SavingsTransaction.objects.filter(account_id__in=account_ids)
            .select_related(
                "performed_by",
                "account__client__branch",
                "account__client__institution",
            )
            .order_by("-transaction_date", "-created_at")
        )
