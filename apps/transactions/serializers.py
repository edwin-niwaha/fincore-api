from rest_framework import serializers

from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    client_member_number = serializers.CharField(source="client.member_number", read_only=True)
    client_name = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    category_label = serializers.SerializerMethodField()
    direction_label = serializers.CharField(source="get_direction_display", read_only=True)

    class Meta:
        model = Transaction
        fields = (
            "id",
            "institution",
            "institution_name",
            "branch",
            "branch_name",
            "client",
            "client_member_number",
            "client_name",
            "category",
            "category_label",
            "direction",
            "direction_label",
            "amount",
            "reference",
            "description",
            "created_by",
            "created_by_email",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_client_name(self, obj):
        if not obj.client_id:
            return ""
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    def get_category_label(self, obj):
        return obj.category_label
