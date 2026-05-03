from django.shortcuts import get_object_or_404
from rest_framework import decorators, response, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import AuditService
from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsCashRole, IsStaffRole
from .models import ShareAccount, ShareProduct, ShareTransaction
from .serializers import ShareAccountSerializer, ShareOperationSerializer, ShareProductSerializer, ShareTransactionSerializer
from .services import ShareService


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
        qs = ShareProduct.objects.select_related("institution")
        user = self.request.user
        if getattr(user, "role", "") == "super_admin":
            return qs
        if getattr(user, "institution_id", None):
            return qs.filter(institution_id=user.institution_id)
        return qs.none()

    def perform_create(self, serializer):
        product = serializer.save()
        AuditService.log(user=self.request.user, action="shares.product.create", target=str(product.id), metadata={"code": product.code})

    def perform_update(self, serializer):
        product = serializer.save()
        AuditService.log(user=self.request.user, action="shares.product.update", target=str(product.id), metadata={"code": product.code})


class ShareAccountViewSet(ScopedMixin, viewsets.ModelViewSet):
    serializer_class = ShareAccountSerializer
    filterset_fields = {"client": ["exact"], "product": ["exact"], "status": ["exact"], "client__branch": ["exact"], "client__institution": ["exact"]}
    search_fields = ["account_number", "client__member_number", "client__first_name", "client__last_name", "client__phone", "product__name"]
    ordering_fields = ["created_at", "account_number", "shares", "total_value", "status"]
    ordering = ["account_number"]

    def get_queryset(self):
        return ShareAccount.objects.select_related("client", "client__branch", "client__institution", "product").filter(client__in=self.scope_clients())

    def _validate_scope(self, serializer):
        client = serializer.validated_data.get("client", getattr(serializer.instance, "client", None))
        product = serializer.validated_data.get("product", getattr(serializer.instance, "product", None))
        if client and not self.scope_clients().filter(pk=client.pk).exists():
            raise PermissionDenied("You cannot manage a share account outside your scope.")
        if client and product and client.institution_id != product.institution_id:
            raise ValidationError("Share product and client must belong to the same institution.")

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        account = serializer.save()
        AuditService.log(user=self.request.user, action="shares.account.create", target=str(account.id), metadata={"account_number": account.account_number})

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        account = serializer.save()
        AuditService.log(user=self.request.user, action="shares.account.update", target=str(account.id), metadata={"account_number": account.account_number, "status": account.status})

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy", "purchase", "redeem"}:
            return [IsCashRole()]
        return [IsStaffRole()]

    @decorators.action(detail=True, methods=["post"])
    def purchase(self, request, pk=None):
        serializer = ShareOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = ShareService.post(account=get_object_or_404(self.get_queryset(), pk=pk), transaction_type=ShareTransaction.Type.PURCHASE, performed_by=request.user, **serializer.validated_data)
        return response.Response(ShareTransactionSerializer(row).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["post"])
    def redeem(self, request, pk=None):
        serializer = ShareOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = ShareService.post(account=get_object_or_404(self.get_queryset(), pk=pk), transaction_type=ShareTransaction.Type.REDEEM, performed_by=request.user, **serializer.validated_data)
        return response.Response(ShareTransactionSerializer(row).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        account = get_object_or_404(self.get_queryset(), pk=pk)
        qs = account.transactions.select_related("account", "account__client", "account__product", "performed_by")
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(ShareTransactionSerializer(page, many=True).data)
        return response.Response(ShareTransactionSerializer(qs, many=True).data)


class ShareTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ShareTransactionSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = {"account": ["exact"], "type": ["exact"], "account__client": ["exact"], "account__product": ["exact"]}
    search_fields = ["reference", "account__account_number", "account__client__first_name", "account__client__last_name"]
    ordering_fields = ["created_at", "amount", "shares", "type"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return ShareTransaction.objects.select_related("account", "account__client", "account__product", "performed_by").filter(account__client__in=clients_for_user(self.request.user))
