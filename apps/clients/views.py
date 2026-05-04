from django.db.models import Q
from django.utils import timezone
from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.common.models import StatusChoices
from apps.audit.services import AuditService
from apps.common.permissions import IsStaffRole
from apps.loans.models import LoanApplication
from apps.users.models import CustomUser

from .models import Client, ClientStatusChoices, ClientStatusHistory, KycStatusChoices
from .selectors import clients_for_user
from .serializers import (
    ClientDetailSerializer,
    ClientKycVerificationSerializer,
    ClientSelfServiceUpdateSerializer,
    ClientSerializer,
    ClientStatusChangeSerializer,
    ClientStatusHistorySerializer,
    LinkableClientUserSerializer,
)


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsStaffRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = [
        "institution",
        "branch",
        "status",
        "user",
        "membership_type",
        "kyc_status",
        "risk_rating",
        "is_watchlist_flagged",
    ]
    search_fields = [
        "member_number",
        "first_name",
        "last_name",
        "phone",
        "email",
        "national_id",
        "passport_number",
        "registration_number",
    ]
    ordering_fields = [
        "created_at",
        "member_number",
        "first_name",
        "last_name",
        "status",
        "joining_date",
        "kyc_status",
    ]
    ordering = ["member_number", "last_name", "first_name"]

    def get_queryset(self):
        return clients_for_user(self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClientDetailSerializer
        return ClientSerializer

    def _record_status_history(self, *, client, from_status, to_status, changed_by, reason=""):
        return ClientStatusHistory.objects.create(
            client=client,
            from_status=from_status or "",
            to_status=to_status,
            changed_by=changed_by if getattr(changed_by, "is_authenticated", False) else None,
            reason=reason.strip(),
        )

    def _transition_status(self, *, client, to_status, changed_by, reason="", action):
        if client.status == to_status:
            return client

        previous_status = client.status
        client.status = to_status
        client.updated_by = changed_by
        client.save(update_fields=["status", "updated_by", "updated_at"])
        self._record_status_history(
            client=client,
            from_status=previous_status,
            to_status=to_status,
            changed_by=changed_by,
            reason=reason,
        )
        AuditService.log(
            user=changed_by,
            action=action,
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "from_status": previous_status,
                "to_status": to_status,
                "reason": reason.strip(),
            },
        )
        return client

    def _validate_can_activate(self, client):
        if client.kyc_status != KycStatusChoices.VERIFIED:
            raise ValidationError("Only KYC-verified members can be activated.")
        if client.status in {
            ClientStatusChoices.CLOSED,
            ClientStatusChoices.REJECTED,
            ClientStatusChoices.BLACKLISTED,
        }:
            raise ValidationError("This member cannot be activated from the current status.")

    def _validate_can_close(self, client):
        open_savings_accounts = client.savings_accounts.exclude(
            status=StatusChoices.CLOSED
        )
        if open_savings_accounts.exists():
            raise ValidationError(
                "Close or settle all member savings accounts before closing the member profile."
            )

        open_loans = client.loan_applications.exclude(
            status__in=[
                LoanApplication.Status.CLOSED,
                LoanApplication.Status.REJECTED,
                LoanApplication.Status.WITHDRAWN,
            ]
        )
        if open_loans.exists():
            raise ValidationError(
                "This member still has open or unsettled loan records and cannot be closed."
            )

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
        self._record_status_history(
            client=client,
            from_status="",
            to_status=client.status,
            changed_by=self.request.user,
            reason="Initial member registration.",
        )
        AuditService.log(
            user=self.request.user,
            action="client.create",
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "status": client.status,
                "kyc_status": client.kyc_status,
                "branch_id": str(client.branch_id),
                "institution_id": str(client.institution_id),
                "user_id": str(client.user_id) if client.user_id else "",
            },
        )

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        previous_status = serializer.instance.status
        client = serializer.save(updated_by=self.request.user)
        if previous_status != client.status:
            self._record_status_history(
                client=client,
                from_status=previous_status,
                to_status=client.status,
                changed_by=self.request.user,
                reason="Profile status updated.",
            )
        AuditService.log(
            user=self.request.user,
            action="client.update",
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "status": client.status,
                "kyc_status": client.kyc_status,
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
        self._validate_can_activate(client)
        client = self._transition_status(
            client=client,
            to_status=ClientStatusChoices.ACTIVE,
            changed_by=request.user,
            action="client.activate",
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        client = self.get_object()
        serializer = ClientStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = self._transition_status(
            client=client,
            to_status=ClientStatusChoices.INACTIVE,
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
            action="client.deactivate",
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        client = self.get_object()
        serializer = ClientStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = self._transition_status(
            client=client,
            to_status=ClientStatusChoices.SUSPENDED,
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
            action="client.suspend",
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        client = self.get_object()
        serializer = ClientStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = self._transition_status(
            client=client,
            to_status=ClientStatusChoices.REJECTED,
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
            action="client.reject",
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        client = self.get_object()
        serializer = ClientStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._validate_can_close(client)
        client = self._transition_status(
            client=client,
            to_status=ClientStatusChoices.CLOSED,
            changed_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
            action="client.close",
        )
        return response.Response(self.get_serializer(client).data)

    @decorators.action(detail=True, methods=["post"], url_path="verify-kyc")
    def verify_kyc(self, request, pk=None):
        client = self.get_object()
        serializer = ClientKycVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        previous_status = client.status

        client.kyc_status = serializer.validated_data["kyc_status"]
        client.kyc_level = serializer.validated_data.get("kyc_level", "")
        client.risk_rating = serializer.validated_data.get("risk_rating", client.risk_rating)
        client.is_watchlist_flagged = serializer.validated_data.get(
            "is_watchlist_flagged",
            client.is_watchlist_flagged,
        )
        client.verification_comments = serializer.validated_data.get(
            "verification_comments",
            "",
        )

        client.verified_by = request.user
        client.verified_at = timezone.now()

        if client.is_watchlist_flagged and client.status == ClientStatusChoices.ACTIVE:
            client.status = ClientStatusChoices.BLACKLISTED

        client.updated_by = request.user
        update_fields = [
            "kyc_status",
            "kyc_level",
            "risk_rating",
            "is_watchlist_flagged",
            "verification_comments",
            "verified_by",
            "verified_at",
            "status",
            "updated_by",
            "updated_at",
        ]
        client.save(update_fields=update_fields)

        if previous_status != client.status:
            self._record_status_history(
                client=client,
                from_status=previous_status,
                to_status=client.status,
                changed_by=request.user,
                reason="Watchlist flag enabled during KYC verification."
                if client.status == ClientStatusChoices.BLACKLISTED
                else "Status updated during KYC verification.",
            )

        AuditService.log(
            user=request.user,
            action="client.verify_kyc",
            target=str(client.id),
            metadata={
                "member_number": client.member_number,
                "kyc_status": client.kyc_status,
                "kyc_level": client.kyc_level,
                "risk_rating": client.risk_rating,
                "is_watchlist_flagged": client.is_watchlist_flagged,
            },
        )
        return response.Response(ClientDetailSerializer(client, context=self.get_serializer_context()).data)

    @decorators.action(detail=True, methods=["get"], url_path="status-history")
    def status_history(self, request, pk=None):
        client = self.get_object()
        queryset = client.status_history.select_related("changed_by").order_by("-created_at")
        page = self.paginate_queryset(queryset)
        serializer = ClientStatusHistorySerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return response.Response(serializer.data)

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
