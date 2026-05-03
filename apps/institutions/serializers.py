from django.utils.text import slugify
from rest_framework import serializers

from apps.common.models import StatusChoices

from .models import Branch, Institution


class InstitutionSerializer(serializers.ModelSerializer):
    code = serializers.CharField()
    display_name = serializers.SerializerMethodField()
    branch_count = serializers.SerializerMethodField()
    active_branch_count = serializers.SerializerMethodField()
    logo = serializers.ImageField(required=False, allow_null=True)
    postal_address = serializers.CharField(required=False, allow_blank=True)
    physical_address = serializers.CharField(required=False, allow_blank=True)
    website = serializers.CharField(required=False, allow_blank=True)
    statement_title = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Institution
        fields = (
            "id",
            "name",
            "code",
            "email",
            "phone",
            "currency",
            "logo",
            "postal_address",
            "physical_address",
            "website",
            "statement_title",
            "status",
            "display_name",
            "branch_count",
            "active_branch_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_display_name(self, obj):
        return f"{obj.name} ({obj.code.upper()})"

    def get_branch_count(self, obj):
        return getattr(obj, "branch_count", obj.branches.count())

    def get_active_branch_count(self, obj):
        return getattr(
            obj,
            "active_branch_count",
            obj.branches.filter(status=StatusChoices.ACTIVE).count(),
        )

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Institution name is required.")
        return name

    def validate_code(self, value):
        code = slugify(value).lower()
        if not code:
            raise serializers.ValidationError("Institution code is required.")

        queryset = Institution.objects.filter(code__iexact=code)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("An institution with this code already exists.")
        return code


class BranchSerializer(serializers.ModelSerializer):
    code = serializers.CharField()
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = (
            "id",
            "institution",
            "institution_name",
            "institution_code",
            "name",
            "code",
            "address",
            "status",
            "display_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
        validators = []

    def get_display_name(self, obj):
        return f"{obj.institution.code.upper()} / {obj.name}"

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Branch name is required.")
        return name

    def validate_code(self, value):
        code = slugify(value).lower()
        if not code:
            raise serializers.ValidationError("Branch code is required.")
        return code

    def validate(self, attrs):
        institution = attrs.get("institution") or getattr(self.instance, "institution", None)
        code = attrs.get("code") or getattr(self.instance, "code", None)

        if not institution:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        if code:
            queryset = Branch.objects.filter(institution=institution, code__iexact=code)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError(
                    {"code": ["A branch with this code already exists for that institution."]}
                )

        return attrs


class InstitutionStatementProfileSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Institution
        fields = (
            "name",
            "logo_url",
            "postal_address",
            "physical_address",
            "phone",
            "email",
            "website",
            "statement_title",
            "currency",
        )

    def get_logo_url(self, obj):
        if obj.logo:
            return obj.logo.url  # Cloudinary auto full URL
        return ""