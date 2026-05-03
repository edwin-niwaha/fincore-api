from rest_framework import serializers

from .models import ShareAccount, ShareProduct, ShareTransaction


class ShareProductSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)

    class Meta:
        model = ShareProduct
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class ShareAccountSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_member_number = serializers.CharField(source="client.member_number", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    nominal_price = serializers.DecimalField(source="product.nominal_price", max_digits=14, decimal_places=2, read_only=True)
    branch_name = serializers.CharField(source="client.branch.name", read_only=True)
    institution_name = serializers.CharField(source="client.institution.name", read_only=True)

    class Meta:
        model = ShareAccount
        fields = (
            "id", "client", "client_name", "client_member_number", "product", "product_name",
            "nominal_price", "branch_name", "institution_name", "account_number", "shares",
            "total_value", "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "account_number", "shares", "total_value", "created_at", "updated_at")

    def get_client_name(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()


class ShareTransactionSerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(source="account.account_number", read_only=True)
    client_name = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="account.product.name", read_only=True)
    performed_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    type_label = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = ShareTransaction
        fields = "__all__"
        read_only_fields = ("id", "balance_after", "performed_by", "created_at", "updated_at")

    def get_client_name(self, obj):
        client = obj.account.client
        return f"{client.first_name} {client.last_name}".strip()


class ShareOperationSerializer(serializers.Serializer):
    shares = serializers.IntegerField(min_value=1)
    reference = serializers.CharField(max_length=80)
    notes = serializers.CharField(required=False, allow_blank=True)
