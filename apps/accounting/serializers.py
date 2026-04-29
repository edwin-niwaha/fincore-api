from rest_framework import serializers

from .models import JournalEntry, JournalEntryLine, LedgerAccount
from .services import JournalService


class LedgerAccountSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    is_system = serializers.SerializerMethodField()
    journal_line_count = serializers.SerializerMethodField()

    class Meta:
        model = LedgerAccount
        fields = (
            "id",
            "institution",
            "institution_name",
            "code",
            "name",
            "type",
            "normal_balance",
            "description",
            "system_code",
            "is_system",
            "is_active",
            "allow_manual_entries",
            "journal_line_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "institution_name",
            "normal_balance",
            "system_code",
            "is_system",
            "journal_line_count",
            "created_at",
            "updated_at",
        )

    def get_is_system(self, obj):
        return obj.is_system

    def get_journal_line_count(self, obj):
        return getattr(obj, "journal_line_count", obj.journal_lines.count())

    def validate_code(self, value):
        code = value.strip().upper()
        if not code:
            raise serializers.ValidationError("Account code is required.")
        return code

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Account name is required.")
        return name

    def validate_description(self, value):
        return value.strip()

    def validate(self, attrs):
        institution = attrs.get("institution") or getattr(self.instance, "institution", None)
        code = attrs.get("code") or getattr(self.instance, "code", None)

        if not institution:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        if code:
            queryset = LedgerAccount.objects.filter(institution=institution, code__iexact=code)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError(
                    {"code": ["A ledger account with this code already exists."]}
                )

        return attrs


class JournalEntryLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalEntryLine
        fields = (
            "id",
            "account",
            "account_code",
            "account_name",
            "description",
            "debit",
            "credit",
        )
        read_only_fields = ("id", "account_code", "account_name")

    def validate_description(self, value):
        return value.strip()


class JournalEntrySerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    posted_by_email = serializers.EmailField(source="posted_by.email", read_only=True)
    total_debit = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()
    is_balanced = serializers.SerializerMethodField()
    lines = JournalEntryLineSerializer(many=True, required=False)

    class Meta:
        model = JournalEntry
        fields = (
            "id",
            "institution",
            "institution_name",
            "branch",
            "branch_name",
            "reference",
            "source_reference",
            "description",
            "entry_date",
            "status",
            "source",
            "posted_by",
            "posted_by_email",
            "posted_at",
            "total_debit",
            "total_credit",
            "is_balanced",
            "lines",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "institution_name",
            "branch_name",
            "source_reference",
            "source",
            "posted_by",
            "posted_by_email",
            "posted_at",
            "total_debit",
            "total_credit",
            "is_balanced",
            "created_at",
            "updated_at",
        )

    def get_total_debit(self, obj):
        return obj.total_debit

    def get_total_credit(self, obj):
        return obj.total_credit

    def get_is_balanced(self, obj):
        return obj.is_balanced

    def validate_reference(self, value):
        reference = value.strip()
        if not reference:
            raise serializers.ValidationError("Reference is required.")
        return reference

    def validate_description(self, value):
        return value.strip()

    def validate(self, attrs):
        institution = attrs.get("institution") or getattr(self.instance, "institution", None)
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        reference = attrs.get("reference") or getattr(self.instance, "reference", None)

        if not institution:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        if branch and branch.institution_id != institution.id:
            raise serializers.ValidationError(
                {"branch": ["Selected branch does not belong to the selected institution."]}
            )

        if reference:
            queryset = JournalEntry.objects.filter(
                institution=institution,
                reference__iexact=reference,
            )
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError(
                    {"reference": ["A journal entry with this reference already exists."]}
                )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        lines = validated_data.pop("lines", [])
        status = validated_data.pop("status", JournalEntry.Status.DRAFT)
        return JournalService.create_entry(
            lines=lines,
            posted_by=getattr(request, "user", None),
            status=status,
            source=JournalEntry.Source.MANUAL,
            **validated_data,
        )

    def update(self, instance, validated_data):
        request = self.context.get("request")
        lines = validated_data.pop("lines", None)
        status = validated_data.pop("status", None)
        return JournalService.update_draft_entry(
            entry=instance,
            lines=lines,
            status=status,
            posted_by=getattr(request, "user", None),
            **validated_data,
        )
