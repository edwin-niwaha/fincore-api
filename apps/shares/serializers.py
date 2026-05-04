from django.utils.text import slugify
from rest_framework import serializers

from apps.clients.models import ClientStatusChoices
from apps.common.models import StatusChoices

from .models import ShareAccount, ShareProduct, ShareTransaction


class ShareProductSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)

    class Meta:
        model = ShareProduct
        fields = (
            "id",
            "institution",
            "institution_name",
            "name",
            "code",
            "nominal_price",
            "minimum_shares",
            "maximum_shares",
            "allow_dividends",
            "status",
            "description",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "institution_name", "created_at", "updated_at")
        validators = []

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Share product name is required.")
        return name

    def validate_code(self, value):
        code = slugify(value).lower()
        if not code:
            raise serializers.ValidationError("Share product code is required.")
        return code

    def validate_nominal_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Nominal price must be greater than zero.")
        return value

    def validate_description(self, value):
        return value.strip()

    def validate(self, attrs):
        institution = attrs.get("institution") or getattr(self.instance, "institution", None)
        code = attrs.get("code") or getattr(self.instance, "code", None)
        minimum_shares = attrs.get(
            "minimum_shares",
            getattr(self.instance, "minimum_shares", 1),
        )
        maximum_shares = attrs.get(
            "maximum_shares",
            getattr(self.instance, "maximum_shares", None),
        )

        if not institution:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        queryset = ShareProduct.objects.filter(institution=institution, code__iexact=code)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {"code": ["A share product with this code already exists for that institution."]}
            )

        if maximum_shares is not None and maximum_shares < minimum_shares:
            raise serializers.ValidationError(
                {"maximum_shares": ["Maximum shares must be greater than or equal to minimum shares."]}
            )

        return attrs


class ShareAccountSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_member_number = serializers.CharField(source="client.member_number", read_only=True)
    branch_id = serializers.UUIDField(source="client.branch_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    nominal_price = serializers.DecimalField(source="product.nominal_price", max_digits=14, decimal_places=2, read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    institution_id = serializers.UUIDField(source="client.institution_id", read_only=True)
    branch_name = serializers.CharField(source="client.branch.name", read_only=True)
    institution_name = serializers.CharField(source="client.institution.name", read_only=True)
    transaction_count = serializers.SerializerMethodField()
    last_transaction_at = serializers.SerializerMethodField()

    class Meta:
        model = ShareAccount
        fields = (
            "id",
            "client",
            "client_name",
            "client_member_number",
            "branch_id",
            "branch_name",
            "institution_id",
            "institution_name",
            "product",
            "product_name",
            "product_code",
            "nominal_price",
            "account_number",
            "shares",
            "total_value",
            "status",
            "transaction_count",
            "last_transaction_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "client_name",
            "client_member_number",
            "branch_id",
            "branch_name",
            "institution_id",
            "institution_name",
            "product_name",
            "product_code",
            "nominal_price",
            "account_number",
            "shares",
            "total_value",
            "transaction_count",
            "last_transaction_at",
            "created_at",
            "updated_at",
        )
        validators = []

    def get_client_name(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    def get_transaction_count(self, obj):
        if hasattr(obj, "transaction_count"):
            return obj.transaction_count
        return obj.transactions.count()

    def get_last_transaction_at(self, obj):
        last_transaction_at = getattr(obj, "last_transaction_at", None)
        if last_transaction_at is not None:
            return last_transaction_at
        transaction = obj.transactions.order_by("-created_at").only("created_at").first()
        return getattr(transaction, "created_at", None)

    def validate(self, attrs):
        client = attrs.get("client") or getattr(self.instance, "client", None)
        product = attrs.get("product") or getattr(self.instance, "product", None)
        status = attrs.get("status", getattr(self.instance, "status", StatusChoices.ACTIVE))

        if not client:
            raise serializers.ValidationError({"client": ["Client is required."]})
        if not product:
            raise serializers.ValidationError({"product": ["Share product is required."]})

        client_changed = self.instance is None or (
            "client" in attrs and self.instance.client_id != client.id
        )
        product_changed = self.instance is None or (
            "product" in attrs and self.instance.product_id != product.id
        )

        if client_changed and client.status != ClientStatusChoices.ACTIVE:
            raise serializers.ValidationError(
                {"client": ["Only active clients can open share accounts."]}
            )

        if product_changed and product.status != StatusChoices.ACTIVE:
            raise serializers.ValidationError(
                {"product": ["Only active share products can be assigned to share accounts."]}
            )

        if client.institution_id != product.institution_id:
            raise serializers.ValidationError(
                {"product": ["Share product and client must belong to the same institution."]}
            )

        duplicate_account_qs = ShareAccount.objects.filter(client=client, product=product)
        if self.instance:
            duplicate_account_qs = duplicate_account_qs.exclude(pk=self.instance.pk)
        if duplicate_account_qs.exists():
            raise serializers.ValidationError(
                {"product": ["This client already has a share account for the selected product."]}
            )

        if self.instance and (client_changed or product_changed) and self.instance.transactions.exists():
            raise serializers.ValidationError(
                {"client": ["Share accounts with transaction history cannot be reassigned."]}
            )

        if self.instance is None and status == StatusChoices.CLOSED:
            raise serializers.ValidationError(
                {"status": ["Share accounts cannot be created in a closed status."]}
            )

        if self.instance and status == StatusChoices.CLOSED and self.instance.shares > 0:
            raise serializers.ValidationError(
                {"status": ["Share accounts with a positive share balance cannot be closed."]}
            )

        return attrs


class ShareAccountDetailSerializer(ShareAccountSerializer):
    recent_transactions = serializers.SerializerMethodField()

    class Meta(ShareAccountSerializer.Meta):
        fields = ShareAccountSerializer.Meta.fields + ("recent_transactions",)
        read_only_fields = fields

    def get_recent_transactions(self, obj):
        queryset = obj.transactions.select_related(
            "performed_by",
            "account__client__branch",
            "account__client__institution",
            "account__product",
        ).order_by("-created_at")[:10]
        return ShareTransactionSerializer(queryset, many=True).data


class ShareTransactionSerializer(serializers.ModelSerializer):
    client_id = serializers.UUIDField(source="account.client_id", read_only=True)
    account_number = serializers.CharField(source="account.account_number", read_only=True)
    client_name = serializers.SerializerMethodField()
    client_member_number = serializers.CharField(source="account.client.member_number", read_only=True)
    branch_name = serializers.CharField(source="account.client.branch.name", read_only=True)
    institution_name = serializers.CharField(source="account.client.institution.name", read_only=True)
    product = serializers.UUIDField(source="account.product_id", read_only=True)
    product_name = serializers.CharField(source="account.product.name", read_only=True)
    product_code = serializers.CharField(source="account.product.code", read_only=True)
    performed_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    recorded_by = serializers.UUIDField(source="performed_by_id", read_only=True)
    recorded_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = ShareTransaction
        fields = (
            "id",
            "account",
            "account_number",
            "client_id",
            "client_name",
            "client_member_number",
            "branch_name",
            "institution_name",
            "product",
            "product_name",
            "product_code",
            "type",
            "type_label",
            "status",
            "shares",
            "amount",
            "balance_after",
            "reference",
            "performed_by",
            "performed_by_email",
            "recorded_by",
            "recorded_by_email",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_client_name(self, obj):
        client = obj.account.client
        return f"{client.first_name} {client.last_name}".strip()

    def get_status(self, obj):
        return "posted"


class ShareOperationSerializer(serializers.Serializer):
    shares = serializers.IntegerField(min_value=1)
    reference = serializers.CharField(max_length=80)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_reference(self, value):
        reference = value.strip()
        if not reference:
            raise serializers.ValidationError("Reference is required.")
        return reference

    def validate_notes(self, value):
        return value.strip()
