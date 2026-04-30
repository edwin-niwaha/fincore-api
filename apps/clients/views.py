from django.db.models import Q
from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import AuditService
from apps.common.permissions import IsStaffRole
from apps.users.models import CustomUser

from .models import Client, ClientStatusChoices
from .selectors import clients_for_user
from .serializers import (
    ClientDetailSerializer,
    ClientSelfServiceUpdateSerializer,
    ClientSerializer,
    LinkableClientUserSerializer,
)


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsStaffRole]
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

    def _linkable_client_users_queryset(self):
        actor = self.request.user
        queryset = CustomUser.objects.filter(
            role=CustomUser.Role.CLIENT,
            is_active=True,
        ).select_related("institution", "branch", "client_profile")

        if actor.role == CustomUser.Role.SUPER_ADMIN:
            return queryset

        search_term = self.request.query_params.get("search", "").strip()
        base_scope = Q()
        if actor.branch_id:
            base_scope |= Q(
                institution_id=actor.institution_id,
                branch_id=actor.branch_id,
            )
        elif actor.institution_id:
            base_scope |= Q(institution_id=actor.institution_id)
        else:
            return queryset.none()

        if search_term:
            base_scope |= Q(institution__isnull=True, branch__isnull=True)

        return queryset.filter(base_scope)

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        client = serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
        )
        AuditService.log(
            user=self.request.user,
            action="client.create",
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "branch_id": str(client.branch_id),
                "institution_id": str(client.institution_id),
                "user_id": str(client.user_id) if client.user_id else "",
            },
        )

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        client = serializer.save(updated_by=self.request.user)
        AuditService.log(
            user=self.request.user,
            action="client.update",
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "status": client.status,
                "branch_id": str(client.branch_id),
                "institution_id": str(client.institution_id),
                "user_id": str(client.user_id) if client.user_id else "",
            },
        )

    def perform_destroy(self, instance):
        client_id = str(instance.id)
        member_number = instance.member_number
        instance.delete()
        AuditService.log(
            user=self.request.user,
            action="client.delete",
            target=client_id,
            metadata={"member_number": member_number},
        )

    def get_permissions(self):
        if self.action == "me":
            return [IsAuthenticated()]
        return [permission() for permission in self.permission_classes]

    @decorators.action(detail=False, methods=["get"], url_path="linkable-users")
    def linkable_users(self, request):
        queryset = self._linkable_client_users_queryset()
        institution_id = request.query_params.get("institution")
        branch_id = request.query_params.get("branch")
        search_term = request.query_params.get("search", "").strip()
        current_client_id = request.query_params.get("client")

        if institution_id:
            queryset = queryset.filter(institution_id=institution_id)
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        if search_term:
            queryset = queryset.filter(
                Q(email__icontains=search_term)
                | Q(username__icontains=search_term)
                | Q(first_name__icontains=search_term)
                | Q(last_name__icontains=search_term)
            )

        queryset = queryset.filter(
            Q(client_profile__isnull=True) | Q(client_profile__id=current_client_id)
        ).order_by("email")

        page = self.paginate_queryset(queryset)
        serializer = LinkableClientUserSerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)

    @decorators.action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        client = self.get_object()
        client.status = ClientStatusChoices.ACTIVE
        client.updated_by = request.user
        client.save(update_fields=["status", "updated_by", "updated_at"])
        AuditService.log(
            user=request.user,
            action="client.activate",
            target=str(client.id),
            metadata={"member_number": client.member_number},
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        client = self.get_object()
        client.status = ClientStatusChoices.INACTIVE
        client.updated_by = request.user
        client.save(update_fields=["status", "updated_by", "updated_at"])
        AuditService.log(
            user=request.user,
            action="client.deactivate",
            target=str(client.id),
            metadata={"member_number": client.member_number},
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="link-user")
    def link_user(self, request, pk=None):
        client = self.get_object()
        serializer = ClientSerializer(
            client,
            data={"user": request.data.get("user")},
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        self._validate_scope(serializer)
        client = serializer.save(updated_by=request.user)
        AuditService.log(
            user=request.user,
            action="client.link_user",
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "user_id": str(client.user_id) if client.user_id else "",
            },
        )
        return response.Response(ClientDetailSerializer(client, context=self.get_serializer_context()).data)

    @decorators.action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        if request.user.role != CustomUser.Role.CLIENT:
            raise PermissionDenied("Only client users can access the self-service client profile.")

        client = (
            Client.objects.select_related(
                "institution",
                "branch",
                "user",
                "created_by",
                "updated_by",
            )
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
            client = update_serializer.save(updated_by=request.user)
            AuditService.log(
                user=request.user,
                action="client.self_service_update",
                target=str(client.id),
                metadata={"member_number": client.member_number},
            )

        detail_serializer = ClientDetailSerializer(
            client,
            context=self.get_serializer_context(),
        )
        return response.Response(detail_serializer.data)
