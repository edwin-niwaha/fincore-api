from rest_framework import viewsets
from .models import Transaction
from .serializers import TransactionSerializer
class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer
    filterset_fields = ["institution", "branch", "client", "category", "direction"]
    search_fields = ["reference", "description"]
    ordering_fields = ["created_at", "amount"]
    def get_queryset(self):
        user = self.request.user
        qs = Transaction.objects.select_related("institution", "branch", "client", "created_by")
        if user.role == "client":
            return qs.filter(client__user=user)
        if user.role == "super_admin":
            return qs
        if user.branch_id:
            return qs.filter(branch=user.branch)
        if user.institution_id:
            return qs.filter(institution=user.institution)
        return qs.none()
