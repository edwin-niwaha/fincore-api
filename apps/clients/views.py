from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.common.permissions import IsStaffRole
from apps.users.models import CustomUser

from .models import Client
from .selectors import clients_for_user
from .serializers import (
    ClientDetailSerializer,
    ClientSelfServiceUpdateSerializer,
    ClientSerializer,
)


class ClientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_fields = ["institution", "branch", "status", "user"]
    search_fields = [
        "member_number",
        "first_name",
        "last_name",
        "phone",
        "email",
        "national_id",
    ]
    ordering_fields = ["created_at", "member_number", "first_name", "last_name", "status"]
    ordering = ["member_number", "last_name", "first_name"]

    def get_queryset(self):
        return clients_for_user(self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClientDetailSerializer
        return ClientSerializer

    def _validate_scope(self, serializer):
        user = self.request.user
        institution = serializer.validated_data.get(
            "institution",
            getattr(serializer.instance, "institution", None),
        )
        branch = serializer.validated_data.get(
            "branch",
            getattr(serializer.instance, "branch", None),
        )

        if user.role == CustomUser.Role.SUPER_ADMIN:
            return

        if user.institution_id and institution and institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage clients outside your institution.")

        if user.branch_id and branch and branch.pk != user.branch_id:
            raise PermissionDenied("You cannot manage clients outside your branch.")

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        serializer.save()

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsStaffRole()]
        return super().get_permissions()

    @decorators.action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        client = (
            Client.objects.select_related("institution", "branch", "user")
            .filter(user=request.user)
            .first()
        )
        if not client:
            return response.Response({"detail": "No client profile found."}, status=404)

        if request.method == "PATCH":
            update_serializer = ClientSelfServiceUpdateSerializer(
                client,
                data=request.data,
                partial=True,
                context=self.get_serializer_context(),
            )
            update_serializer.is_valid(raise_exception=True)
            client = update_serializer.save()

        detail_serializer = ClientDetailSerializer(
            client,
            context=self.get_serializer_context(),
        )
        return response.Response(detail_serializer.data)
