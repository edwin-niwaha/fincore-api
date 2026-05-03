from django.db.models import Count, Q
from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.common.models import StatusChoices
from apps.common.permissions import IsAdminRole
from apps.users.models import CustomUser

from .models import Branch, Institution
from .serializers import (
    BranchSerializer,
    InstitutionSerializer,
    InstitutionStatementProfileSerializer,
)


def is_super_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or getattr(user, "role", None) == CustomUser.Role.SUPER_ADMIN
        )
    )


def is_institution_admin(user):
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "role", None) == CustomUser.Role.INSTITUTION_ADMIN
    )


class InstitutionViewSet(viewsets.ModelViewSet):
    serializer_class = InstitutionSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["status", "currency"]
    search_fields = [
        "name",
        "code",
        "email",
        "phone",
        "postal_address",
        "physical_address",
        "website",
    ]
    ordering_fields = ["name", "code", "created_at", "status"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = Institution.objects.annotate(
            branch_count=Count("branches", distinct=True),
            active_branch_count=Count(
                "branches",
                filter=Q(branches__status=StatusChoices.ACTIVE),
                distinct=True,
            ),
        ).order_by("name")

        user = self.request.user

        if is_super_admin(user):
            return queryset

        if is_institution_admin(user) and user.institution_id:
            return queryset.filter(pk=user.institution_id)

        return queryset.none()

    def get_permissions(self):
        if self.action == "statement_profile":
            return [IsAuthenticated()]
        return [permission() for permission in self.permission_classes]

    def create(self, request, *args, **kwargs):
        if not is_super_admin(request.user):
            raise PermissionDenied("Only super admins can create institutions.")
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not is_super_admin(request.user):
            raise PermissionDenied("Only super admins can delete institutions.")
        return super().destroy(request, *args, **kwargs)

    @decorators.action(
        detail=False,
        methods=["get"],
        url_path="statement-profile",
    )
    def statement_profile(self, request):
        institution = (
            getattr(request.user, "institution", None)
            or getattr(getattr(request.user, "client_profile", None), "institution", None)
        )

        if not institution and is_super_admin(request.user):
            institution = Institution.objects.filter(
                status=StatusChoices.ACTIVE,
            ).order_by("name").first()

        if not institution:
            return response.Response({"detail": "No institution found."}, status=404)

        serializer = InstitutionStatementProfileSerializer(
            institution,
            context={"request": request},
        )
        return response.Response(serializer.data)


class BranchViewSet(viewsets.ModelViewSet):
    serializer_class = BranchSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["institution", "status"]
    search_fields = ["name", "code", "institution__name", "institution__code", "address"]
    ordering_fields = ["name", "code", "created_at", "status"]
    ordering = ["institution__name", "name"]

    def get_queryset(self):
        queryset = Branch.objects.select_related("institution").order_by(
            "institution__name",
            "name",
        )
        user = self.request.user

        if is_super_admin(user):
            return queryset

        if is_institution_admin(user) and user.institution_id:
            return queryset.filter(institution_id=user.institution_id)

        return queryset.none()

    def perform_create(self, serializer):
        institution = serializer.validated_data["institution"]
        user = self.request.user

        if is_institution_admin(user) and institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage branches outside your institution.")

        serializer.save()

    def perform_update(self, serializer):
        institution = serializer.validated_data.get(
            "institution",
            serializer.instance.institution,
        )
        user = self.request.user

        if is_institution_admin(user) and institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage branches outside your institution.")

        serializer.save()