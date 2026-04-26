from rest_framework import decorators, response, viewsets
from .models import Notification
from .serializers import NotificationSerializer
class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    @decorators.action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        n = self.get_object(); n.is_read = True; n.save(update_fields=["is_read", "updated_at"])
        return response.Response(self.get_serializer(n).data)
