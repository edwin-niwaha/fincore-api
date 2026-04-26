from rest_framework import viewsets
from apps.common.permissions import IsAdminRole
from .models import AuditLog
from .serializers import AuditLogSerializer
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]
