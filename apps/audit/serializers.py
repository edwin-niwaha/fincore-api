from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.SerializerMethodField()
    user_role = serializers.CharField(source="user.role", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    metadata_size = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "user",
            "user_email",
            "user_full_name",
            "user_role",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "action",
            "module",
            "resource",
            "event",
            "target",
            "metadata",
            "metadata_size",
            "ip_address",
            "request_path",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_user_full_name(self, obj):
        if not obj.user_id:
            return ""

        full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return full_name or getattr(obj.user, "username", "") or getattr(obj.user, "email", "")

    def get_metadata_size(self, obj):
        if isinstance(obj.metadata, dict):
            return len(obj.metadata)
        return 0
