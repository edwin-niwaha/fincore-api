from django.db.models import Count
from rest_framework import decorators, response, viewsets
from rest_framework.exceptions import PermissionDenied

from apps.common.permissions import IsAccountingRole
from apps.institutions.models import Institution
from apps.users.access import is_super_admin

from .models import JournalEntry
from .selectors import journal_entries_for_user, ledger_accounts_for_user
from .serializers import JournalEntrySerializer, LedgerAccountSerializer
from .services import ChartOfAccountsService, JournalService


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = LedgerAccountSerializer
    permission_classes = [IsAccountingRole]
    filterset_fields = ["institution", "type", "normal_balance", "is_active"]
    search_fields = ["code", "name", "description"]
    ordering_fields = ["code", "name", "type", "created_at", "updated_at"]
    ordering = ["code", "name"]

    def get_queryset(self):
        queryset = ledger_accounts_for_user(self.request.user).annotate(
            journal_line_count=Count("journal_lines", distinct=True)
        )
        user = self.request.user

        if user and user.is_authenticated and user.institution_id:
            ChartOfAccountsService.ensure_default_accounts(user.institution)

        institution_id = self.request.query_params.get("institution")
        if institution_id and is_super_admin(user):
            institution = Institution.objects.filter(pk=institution_id).first()
            if institution:
                ChartOfAccountsService.ensure_default_accounts(institution)

        return queryset

    def _validate_scope(self, serializer):
        user = self.request.user
        institution = serializer.validated_data.get(
            "institution",
            getattr(serializer.instance, "institution", None),
        )

        if is_super_admin(user):
            return

        if user.institution_id and institution and institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage ledger accounts outside your institution.")

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        serializer.save()

    def perform_update(self, serializer):
        if getattr(serializer.instance, "system_code", ""):
            raise PermissionDenied("System ledger accounts cannot be edited.")
        self._validate_scope(serializer)
        serializer.save()

    def perform_destroy(self, instance):
        if instance.is_system:
            raise PermissionDenied("System ledger accounts cannot be deleted.")
        if instance.journal_lines.exists():
            raise PermissionDenied("Ledger accounts with journal activity cannot be deleted.")
        instance.delete()


class JournalEntryViewSet(viewsets.ModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAccountingRole]
    filterset_fields = ["institution", "branch", "status", "source", "entry_date"]
    search_fields = ["reference", "source_reference", "description"]
    ordering_fields = ["entry_date", "created_at", "posted_at", "reference"]
    ordering = ["-entry_date", "-created_at"]

    def get_queryset(self):
        return journal_entries_for_user(self.request.user)

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

        if is_super_admin(user):
            return

        if user.institution_id and institution and institution.pk != user.institution_id:
            raise PermissionDenied("You cannot manage journal entries outside your institution.")

        if user.branch_id and branch and branch.pk != user.branch_id:
            raise PermissionDenied("You cannot manage journal entries outside your branch.")

        if user.branch_id and branch is None:
            raise PermissionDenied("Branch-scoped users must post journal entries to their branch.")

    def perform_create(self, serializer):
        self._validate_scope(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._validate_scope(serializer)
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status == JournalEntry.Status.POSTED:
            raise PermissionDenied("Posted journal entries cannot be deleted.")
        instance.delete()

    @decorators.action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        entry = JournalService.post_existing_entry(
            entry=self.get_object(),
            posted_by=request.user,
        )
        return response.Response(self.get_serializer(entry).data)
