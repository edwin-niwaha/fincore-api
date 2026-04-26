from rest_framework import viewsets
from apps.common.permissions import IsAccountingRole
from .models import JournalEntry, LedgerAccount
from .serializers import JournalEntrySerializer, LedgerAccountSerializer

class AccountViewSet(viewsets.ModelViewSet):
    queryset = LedgerAccount.objects.select_related("institution")
    serializer_class = LedgerAccountSerializer
    permission_classes = [IsAccountingRole]
    filterset_fields = ["institution", "type", "is_active"]
    search_fields = ["code", "name"]

class JournalEntryViewSet(viewsets.ModelViewSet):
    queryset = JournalEntry.objects.prefetch_related("lines").select_related("institution", "branch", "posted_by")
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAccountingRole]
    filterset_fields = ["institution", "branch"]
    search_fields = ["reference", "description"]
