from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from apps.common.permissions import IsStaffRole
from .models import Client
from .selectors import clients_for_user
from .serializers import ClientSelfServiceSerializer, ClientSerializer

class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["institution", "branch", "status"]
    search_fields = ["member_number", "first_name", "last_name", "phone", "national_id"]
    ordering_fields = ["created_at", "member_number", "first_name"]

    def get_queryset(self):
        return clients_for_user(self.request.user)

    def _validate_scope(self, serializer):
        user = self.request.user
        institution = serializer.validated_data.get("institution")
        branch = serializer.validated_data.get("branch")
        if user.role != "super_admin":
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
        client = Client.objects.filter(user=request.user).first()
        if not client:
            return response.Response({"detail": "No client profile found."}, status=404)
        serializer = ClientSelfServiceSerializer(client, data=request.data or None, partial=True)
        if request.method == "PATCH":
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return response.Response(serializer.data)
