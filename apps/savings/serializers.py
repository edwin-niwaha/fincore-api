from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from apps.clients.models import ClientStatusChoices
from apps.common.models import StatusChoices

from .models import SavingsAccount, SavingsPolicy, SavingsTransaction

ZERO_DECIMAL = Decimal("0.00")


class SavingsPolicySerializer(serializers.ModelSerializer):
    institution = serializers.UUIDField(source="institution_id", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True)

    class Meta:
        model = SavingsPolicy
        fields = (
            "id",
            "institution",
            "institution_name",
            "name",
            "minimum_balance",
            "withdrawal_charge",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "institution",
            "institution_name",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        )

    def validate_minimum_balance(self, value):
        if value < ZERO_DECIMAL:
            raise serializers.ValidationError("Minimum balance cannot be negative.")
        return value

    def validate_withdrawal_charge(self, value):
        if value < ZERO_DECIMAL:
            raise serializers.ValidationError("Withdrawal charge cannot be negative.")
        return value


class SavingsTransactionSerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(source="account.account_number", read_only=True)
    client_id = serializers.UUIDField(source="account.client_id", read_only=True)
    client_name = serializers.SerializerMethodField()
    client_phone = serializers.CharField(source="account.client.phone", read_only=True)
    branch_name = serializers.CharField(source="account.client.branch.name", read_only=True)
    institution_name = serializers.CharField(source="account.client.institution.name", read_only=True)
    performed_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    recorded_by = serializers.UUIDField(source="performed_by_id", read_only=True)
    recorded_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    recorded_at = serializers.DateTimeField(source="created_at", read_only=True)
    transaction_type = serializers.CharField(source="type", read_only=True)
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = SavingsTransaction
        fields = (
            "id",
            "account",
            "account_number",
            "client_id",
            "client_name",
            "client_phone",
            "branch_name",
            "institution_name",
            "type",
            "transaction_type",
            "type_label",
            "status",
            "transaction_date",
            "amount",
            "balance_after",
            "reference",
            "performed_by",
            "performed_by_email",
            "recorded_by",
            "recorded_by_email",
            "recorded_at",
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


class SavingsAccountSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_member_number = serializers.CharField(source="client.member_number", read_only=True)
    client_phone = serializers.CharField(source="client.phone", read_only=True)
    branch_id = serializers.UUIDField(source="client.branch_id", read_only=True)
    branch_name = serializers.CharField(source="client.branch.name", read_only=True)
    institution_id = serializers.UUIDField(source="client.institution_id", read_only=True)
    institution_name = serializers.CharField(source="client.institution.name", read_only=True)
    transaction_count = serializers.SerializerMethodField()
    last_transaction_at = serializers.SerializerMethodField()

    class Meta:
        model = SavingsAccount
        fields = (
            "id",
            "client",
            "client_name",
            "client_member_number",
            "client_phone",
            "branch_id",
            "branch_name",
            "institution_id",
            "institution_name",
            "account_number",
            "balance",
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
            "client_phone",
            "branch_id",
            "branch_name",
            "institution_id",
            "institution_name",
            "account_number",
            "balance",
            "transaction_count",
            "last_transaction_at",
            "created_at",
            "updated_at",
        )

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
        transaction = obj.transactions.order_by("-transaction_date", "-created_at").only(
            "transaction_date",
            "created_at",
        ).first()
        return getattr(transaction, "transaction_date", None) or getattr(transaction, "created_at", None)

    def validate(self, attrs):
        client = attrs.get("client") or getattr(self.instance, "client", None)
        status = attrs.get("status", getattr(self.instance, "status", StatusChoices.ACTIVE))

        if not client:
            raise serializers.ValidationError({"client": ["Client is required."]})

        client_changed = self.instance is None or (
            "client" in attrs and self.instance.client_id != client.id
        )
        if client_changed and client.status != ClientStatusChoices.ACTIVE:
            raise serializers.ValidationError(
                {"client": ["Only active clients can open savings accounts."]}
            )

        if self.instance is None and status == StatusChoices.CLOSED:
            raise serializers.ValidationError(
                {"status": ["Savings accounts cannot be created in a closed status."]}
            )

        if (
            self.instance
            and "client" in attrs
            and self.instance.client_id != client.id
            and self.instance.transactions.exists()
        ):
            raise serializers.ValidationError(
                {"client": ["Accounts with transaction history cannot be reassigned."]}
            )

        if self.instance and status == StatusChoices.CLOSED and self.instance.balance > ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"status": ["Accounts with a positive balance cannot be closed."]}
            )

        return attrs


class SavingsAccountDetailSerializer(SavingsAccountSerializer):
    recent_transactions = serializers.SerializerMethodField()

    class Meta(SavingsAccountSerializer.Meta):
        fields = SavingsAccountSerializer.Meta.fields + ("recent_transactions",)
        read_only_fields = fields

    def get_recent_transactions(self, obj):
        queryset = obj.transactions.select_related(
            "performed_by",
            "account__client__branch",
            "account__client__institution",
        ).order_by("-transaction_date", "-created_at")[:10]
        return SavingsTransactionSerializer(queryset, many=True).data


class SavingsOperationSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(max_length=80)
    transaction_date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= ZERO_DECIMAL:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_reference(self, value):
        reference = value.strip()
        if not reference:
            raise serializers.ValidationError("Reference is required.")
        return reference

    def validate_transaction_date(self, value):
        transaction_date = value or timezone.localdate()
        if transaction_date > timezone.localdate():
            raise serializers.ValidationError("Transaction date cannot be in the future.")
        return transaction_date

    def validate_notes(self, value):
        return value.strip()
