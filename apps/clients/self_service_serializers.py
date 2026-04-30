from rest_framework import serializers

from apps.loans.models import LoanRepayment
from apps.notifications.models import Notification
from apps.savings.models import SavingsTransaction
from apps.transactions.models import Transaction

from .models import Client


class SelfServiceProfileSerializer(serializers.ModelSerializer):
    client_number = serializers.CharField(source="member_number", read_only=True)
    full_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "client_number",
            "member_number",
            "full_name",
            "first_name",
            "last_name",
            "phone",
            "email",
            "gender",
            "gender_display",
            "date_of_birth",
            "address",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "occupation",
            "next_of_kin_name",
            "next_of_kin_phone",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


class SelfServiceNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            "id",
            "title",
            "message",
            "category",
            "is_read",
            "data",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class SelfServiceSavingsStatementEntrySerializer(serializers.ModelSerializer):
    date = serializers.DateTimeField(source="created_at", read_only=True)
    transaction_type = serializers.CharField(source="type", read_only=True)
    transaction_type_label = serializers.CharField(source="get_type_display", read_only=True)
    balance = serializers.DecimalField(
        source="balance_after",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    status = serializers.SerializerMethodField()
    recorded_by = serializers.UUIDField(source="performed_by_id", read_only=True)
    recorded_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    account = serializers.UUIDField(source="account_id", read_only=True)
    account_number = serializers.CharField(source="account.account_number", read_only=True)

    class Meta:
        model = SavingsTransaction
        fields = (
            "id",
            "date",
            "reference",
            "transaction_type",
            "transaction_type_label",
            "amount",
            "balance",
            "status",
            "recorded_by",
            "recorded_by_email",
            "account",
            "account_number",
            "notes",
        )
        read_only_fields = fields

    def get_status(self, obj):
        return "posted"


class SelfServiceLoanStatementRepaymentSerializer(serializers.ModelSerializer):
    date = serializers.DateTimeField(source="created_at", read_only=True)
    principal = serializers.DecimalField(
        source="principal_component",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    interest = serializers.DecimalField(
        source="interest_component",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    penalty = serializers.DecimalField(
        source="penalty_component",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    remaining_balance = serializers.DecimalField(
        source="remaining_balance_after",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    received_by_email = serializers.EmailField(source="received_by.email", read_only=True)

    class Meta:
        model = LoanRepayment
        fields = (
            "id",
            "loan",
            "date",
            "amount",
            "principal",
            "interest",
            "penalty",
            "payment_method",
            "reference",
            "remaining_balance",
            "received_by",
            "received_by_email",
        )
        read_only_fields = fields


class SelfServiceUnifiedTransactionSerializer(serializers.ModelSerializer):
    date = serializers.DateTimeField(source="created_at", read_only=True)
    type = serializers.CharField(source="category", read_only=True)
    type_label = serializers.CharField(source="category_label", read_only=True)
    direction_label = serializers.CharField(source="get_direction_display", read_only=True)
    source = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    running_balance = serializers.SerializerMethodField()
    account_number = serializers.SerializerMethodField()
    loan_id = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = (
            "id",
            "date",
            "created_at",
            "reference",
            "type",
            "type_label",
            "category",
            "source",
            "direction",
            "direction_label",
            "amount",
            "status",
            "running_balance",
            "account_number",
            "loan_id",
            "description",
        )
        read_only_fields = fields

    def _savings_transaction(self, obj):
        return self.context.get("savings_by_reference", {}).get(obj.reference)

    def _loan_repayment(self, obj):
        return self.context.get("repayments_by_reference", {}).get(obj.reference)

    def _loan_disbursement(self, obj):
        return self.context.get("loans_by_reference", {}).get(obj.reference)

    def get_source(self, obj):
        if obj.category.startswith("savings_"):
            return "savings"
        if obj.category.startswith("loan_"):
            return "loans"
        return "transactions"

    def get_status(self, obj):
        return "posted"

    def get_running_balance(self, obj):
        savings_transaction = self._savings_transaction(obj)
        if savings_transaction is not None:
            return f"{savings_transaction.balance_after:.2f}"

        loan_repayment = self._loan_repayment(obj)
        if loan_repayment is not None:
            return f"{loan_repayment.remaining_balance_after:.2f}"

        return None

    def get_account_number(self, obj):
        savings_transaction = self._savings_transaction(obj)
        if savings_transaction is None:
            return None
        return savings_transaction.account.account_number

    def get_loan_id(self, obj):
        loan_repayment = self._loan_repayment(obj)
        if loan_repayment is not None:
            return str(loan_repayment.loan_id)

        loan_disbursement = self._loan_disbursement(obj)
        if loan_disbursement is not None:
            return str(loan_disbursement.id)

        return None
