from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import decorators, response, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import AuditService
from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsCashRole, IsStaffRole
from apps.users.models import CustomUser

from .models import ShareTransaction
from .serializers import (
    ShareAccountDetailSerializer,
    ShareAccountSerializer,
    ShareOperationSerializer,
    ShareProductSerializer,
    ShareTransactionSerializer,
)
from .selectors import share_accounts_for_user, share_products_for_user
from .services import ShareService

SHARE_PRODUCT_MANAGE_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
    CustomUser.Role.ACCOUNTANT,
}


class ScopedMixin:
    def scope_clients(self):
        return clients_for_user(self.request.user)


class ShareProductViewSet(viewsets.ModelViewSet):
    serializer_class = ShareProductSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = {"institution": ["exact"], "status": ["exact"], "code": ["exact"]}
    search_fields = ["name", "code", "description"]
    ordering_fields = ["created_at", "name", "code", "nominal_price", "status"]
    ordering = ["name"]

    def get_queryset(self):
        return share_products_for_user(self.request.user)

    def _validate_scope(self, serializer):
        institution = serializer.validated_data.get(
            "institution",
            getattr(serializer.instance, "institution", None),
        )
        user = self.request.user

        if user.role == CustomUser.Role.SUPER_ADMIN:
            return

        if not user.institution_id or not institution or institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage share products outside your institution.")

    def _require_manage_role(self):
        if self.request.user.role not in SHARE_PRODUCT_MANAGE_ROLES:
            raise PermissionDenied("You do not have permission to manage share products.")

    def perform_create(self, serializer):
        self._require_manage_role()
        self._validate_scope(serializer)
        product = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="shares.product.create",
            target=str(product.id),
            metadata={"code": product.code, "institution_id": str(product.institution_id)},
        )

    def perform_update(self, serializer):
        self._require_manage_role()
        self._validate_scope(serializer)
        product = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="shares.product.update",
            target=str(product.id),
            metadata={"code": product.code, "status": product.status},
        )

    def perform_destroy(self, instance):
        self._require_manage_role()
        if instance.accounts.exists():
            raise ValidationError("Share products with share accounts cannot be deleted.")

        product_id = str(instance.id)
        code = instance.code
        instance.delete()
        AuditService.log(
            user=self.request.user,
            action="shares.product.delete",
            target=product_id,
            metadata={"code": code},
        )


class ShareAccountViewSet(ScopedMixin, viewsets.ModelViewSet):
    serializer_class = ShareAccountSerializer
    filterset_fields = {
        "client": ["exact"],
        "product": ["exact"],
        "status": ["exact"],
        "client__branch": ["exact"],
        "client__institution": ["exact"],
    }
    search_fields = ["account_number", "client__member_number", "client__first_name", "client__last_name", "client__phone", "product__name"]
    ordering_fields = ["created_at", "account_number", "shares", "total_value", "status"]
    ordering = ["account_number"]

    def get_queryset(self):
        return share_accounts_for_user(self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ShareAccountDetailSerializer
        return ShareAccountSerializer

    def _get_scoped_account(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def _validate_scope(self, serializer):
        client = serializer.validated_data.get("client", getattr(serializer.instance, "client", None))
        product = serializer.validated_data.get("product", getattr(serializer.instance, "product", None))
        if client and not self.scope_clients().filter(pk=client.pk).exists():
            raise PermissionDenied("You cannot manage a share account outside your scope.")
        if product and not share_products_for_user(self.request.user).filter(pk=product.pk).exists():
            raise PermissionDenied("You cannot use a share product outside your scope.")
        if client and product and client.institution_id != product.institution_id:
            raise ValidationError({"product": ["Share product and client must belong to the same institution."]})

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        account = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="shares.account.create",
            target=str(account.id),
            metadata={
                "account_number": account.account_number,
                "client_id": str(account.client_id),
                "product_id": str(account.product_id),
            },
        )

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        account = serializer.save()
        AuditService.log(
            user=self.request.user,
            action="shares.account.update",
            target=str(account.id),
            metadata={"account_number": account.account_number, "status": account.status},
        )

    def perform_destroy(self, instance):
        if instance.transactions.exists():
            raise ValidationError("Share accounts with transaction history cannot be deleted.")
        if instance.shares > 0:
            raise ValidationError("Share accounts with a positive share balance cannot be deleted.")

        account_id = str(instance.id)
        account_number = instance.account_number
        instance.delete()
        AuditService.log(
            user=self.request.user,
            action="shares.account.delete",
            target=account_id,
            metadata={"account_number": account_number},
        )

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy", "purchase", "redeem"}:
            return [IsCashRole()]
        return [IsStaffRole()]

    @decorators.action(detail=True, methods=["post"])
    def purchase(self, request, pk=None):
        serializer = ShareOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = ShareService.post(
            account=self._get_scoped_account(pk),
            transaction_type=ShareTransaction.Type.PURCHASE,
            performed_by=request.user,
            **serializer.validated_data,
        )
        return response.Response(ShareTransactionSerializer(row).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["post"])
    def redeem(self, request, pk=None):
        serializer = ShareOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = ShareService.post(
            account=self._get_scoped_account(pk),
            transaction_type=ShareTransaction.Type.REDEEM,
            performed_by=request.user,
            **serializer.validated_data,
        )
        return response.Response(ShareTransactionSerializer(row).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        account = self._get_scoped_account(pk)
        qs = account.transactions.select_related(
            "account",
            "account__client__branch",
            "account__client__institution",
            "account__product",
            "performed_by",
        ).order_by("-created_at")

        transaction_type = request.query_params.get("type")
        if transaction_type:
            qs = qs.filter(type=transaction_type)

        search_term = request.query_params.get("search", "").strip()
        if search_term:
            qs = qs.filter(reference__icontains=search_term)

        from_date_raw = request.query_params.get("created_at__date__gte")
        to_date_raw = request.query_params.get("created_at__date__lte")

        if from_date_raw:
            from_date = parse_date(from_date_raw)
            if from_date is None:
                raise ValidationError({"created_at__date__gte": ["Use YYYY-MM-DD for the from date filter."]})
            qs = qs.filter(created_at__date__gte=from_date)

        if to_date_raw:
            to_date = parse_date(to_date_raw)
            if to_date is None:
                raise ValidationError({"created_at__date__lte": ["Use YYYY-MM-DD for the to date filter."]})
            qs = qs.filter(created_at__date__lte=to_date)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(ShareTransactionSerializer(page, many=True).data)
        return response.Response(ShareTransactionSerializer(qs, many=True).data)


class ShareTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ShareTransactionSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = {
        "account": ["exact"],
        "type": ["exact"],
        "account__client": ["exact"],
        "account__product": ["exact"],
        "account__client__branch": ["exact"],
        "account__client__institution": ["exact"],
        "created_at": ["date__gte", "date__lte"],
    }
    search_fields = ["reference", "account__account_number", "account__client__first_name", "account__client__last_name"]
    ordering_fields = ["created_at", "amount", "shares", "type", "reference"]
    ordering = ["-created_at"]

    def get_queryset(self):
        account_ids = share_accounts_for_user(self.request.user).values_list("id", flat=True)
        return (
            ShareTransaction.objects.select_related(
                "account",
                "account__client__branch",
                "account__client__institution",
                "account__product",
                "performed_by",
            )
            .filter(account_id__in=account_ids)
            .order_by("-created_at")
        )
