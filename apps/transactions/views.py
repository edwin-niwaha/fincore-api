from rest_framework import viewsets

from .filters import TransactionFilterSet
from .selectors import transactions_for_user
from .serializers import TransactionSerializer


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    http_method_names = ["get", "head", "options"]
    serializer_class = TransactionSerializer
    filterset_class = TransactionFilterSet
    search_fields = [
        "reference",
        "description",
        "client__member_number",
        "client__first_name",
        "client__last_name",
        "branch__name",
        "institution__name",
    ]
    ordering_fields = ["created_at", "amount", "reference", "category", "direction"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        return transactions_for_user(self.request.user)
