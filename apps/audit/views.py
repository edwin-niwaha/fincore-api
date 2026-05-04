from django.db.models import Count
from django.utils import timezone
from rest_framework import decorators, response, viewsets

from apps.common.permissions import IsAdminRole
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = {
        "user": ["exact"],
        "institution": ["exact"],
        "branch": ["exact"],
        "module": ["exact"],
        "resource": ["exact"],
        "event": ["exact"],
        "created_at": ["date__gte", "date__lte", "gte", "lte"],
    }
    search_fields = [
        "action",
        "target",
        "module",
        "resource",
        "event",
        "request_path",
        "user__email",
        "user__username",
        "user__first_name",
        "user__last_name",
        "institution__name",
        "institution__code",
        "branch__name",
        "branch__code",
    ]
    ordering_fields = [
        "created_at",
        "action",
        "module",
        "resource",
        "event",
        "user__email",
        "institution__name",
        "branch__name",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = AuditLog.objects.select_related(
            "user",
            "institution",
            "branch",
        ).order_by("-created_at")
        user = self.request.user

        if getattr(user, "is_superuser", False) or getattr(user, "role", None) == "super_admin":
            return queryset

        if getattr(user, "role", None) == "institution_admin" and getattr(user, "institution_id", None):
            return queryset.filter(institution_id=user.institution_id)

        return queryset.none()

    @decorators.action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        today = timezone.localdate()

        module_breakdown = list(
            queryset.values("module")
            .annotate(count=Count("id"))
            .order_by("-count", "module")[:8]
        )
        event_breakdown = list(
            queryset.values("event")
            .annotate(count=Count("id"))
            .order_by("-count", "event")[:8]
        )

        return response.Response(
            {
                "total_logs": queryset.count(),
                "today_logs": queryset.filter(created_at__date=today).count(),
                "actors": queryset.exclude(user_id__isnull=True).values("user_id").distinct().count(),
                "modules": queryset.exclude(module="").values("module").distinct().count(),
                "latest_activity_at": queryset.values_list("created_at", flat=True).first(),
                "module_breakdown": module_breakdown,
                "event_breakdown": event_breakdown,
            }
        )
