from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied
from apps.clients.selectors import clients_for_user
from apps.common.permissions import IsCashRole
from .models import SavingsTransaction
from .selectors import savings_accounts_for_user
from .serializers import SavingsAccountSerializer, SavingsOperationSerializer, SavingsTransactionSerializer
from .services import SavingsService

class SavingsAccountViewSet(viewsets.ModelViewSet):
    serializer_class = SavingsAccountSerializer
    filterset_fields = ["client", "status"]
    search_fields = ["account_number", "client__member_number", "client__first_name", "client__last_name"]

    def get_queryset(self):
        return savings_accounts_for_user(self.request.user)

    def perform_create(self, serializer):
        client = serializer.validated_data.get("client")
        if not clients_for_user(self.request.user).filter(pk=getattr(client, "pk", None)).exists():
            raise PermissionDenied("You cannot create a savings account for this client.")
        serializer.save()

    def get_permissions(self):
        if self.action in ["create", "deposit", "withdraw"]:
            return [IsCashRole()]
        return super().get_permissions()

    @decorators.action(detail=True, methods=["post"])
    def deposit(self, request, pk=None):
        serializer = SavingsOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx = SavingsService.deposit(account=self.get_object(), performed_by=request.user, **serializer.validated_data)
        return response.Response(SavingsTransactionSerializer(tx).data, status=201)

    @decorators.action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        serializer = SavingsOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx = SavingsService.withdraw(account=self.get_object(), performed_by=request.user, **serializer.validated_data)
        return response.Response(SavingsTransactionSerializer(tx).data, status=201)

class SavingsTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SavingsTransactionSerializer
    filterset_fields = ["account", "type"]
    search_fields = ["reference"]

    def get_queryset(self):
        account_ids = savings_accounts_for_user(self.request.user).values_list("id", flat=True)
        return SavingsTransaction.objects.filter(account_id__in=account_ids).select_related("account", "performed_by")
