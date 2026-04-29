from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import serializers

from apps.common.models import StatusChoices
from apps.loans.models import LoanApplication
from apps.savings.models import SavingsTransaction
from apps.transactions.models import Transaction
from apps.users.models import CustomUser

from .models import Client

ZERO_DECIMAL = Decimal("0.00")


def format_decimal(value):
    if value is None:
        value = ZERO_DECIMAL
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return f"{value:.2f}"


def coalesced_sum(field_name, *, filter_condition=None):
    return Coalesce(
        Sum(field_name, filter=filter_condition),
        Value(ZERO_DECIMAL),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


class ClientSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "user",
            "user_email",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "member_number",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "email",
            "national_id",
            "date_of_birth",
            "address",
            "occupation",
            "next_of_kin_name",
            "next_of_kin_phone",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "member_number",
            "full_name",
            "institution_name",
            "institution_code",
            "branch_name",
            "branch_code",
            "user_email",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "user": {"required": False, "allow_null": True},
            "email": {"required": False, "allow_blank": True},
            "national_id": {"required": False, "allow_blank": True},
            "address": {"required": False, "allow_blank": True},
            "occupation": {"required": False, "allow_blank": True},
            "next_of_kin_name": {"required": False, "allow_blank": True},
            "next_of_kin_phone": {"required": False, "allow_blank": True},
        }

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def validate_first_name(self, value):
        first_name = value.strip()
        if not first_name:
            raise serializers.ValidationError("First name is required.")
        return first_name

    def validate_last_name(self, value):
        last_name = value.strip()
        if not last_name:
            raise serializers.ValidationError("Last name is required.")
        return last_name

    def validate_phone(self, value):
        phone = value.strip()
        if not phone:
            raise serializers.ValidationError("Phone number is required.")
        return phone

    def validate_email(self, value):
        return value.strip().lower()

    def validate_national_id(self, value):
        return value.strip()

    def validate_address(self, value):
        return value.strip()

    def validate_occupation(self, value):
        return value.strip()

    def validate_next_of_kin_name(self, value):
        return value.strip()

    def validate_next_of_kin_phone(self, value):
        return value.strip()

    def validate(self, attrs):
        institution = attrs.get("institution") or getattr(self.instance, "institution", None)
        branch = attrs.get("branch") or getattr(self.instance, "branch", None)
        user = attrs.get("user", getattr(self.instance, "user", None))

        if not institution:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        if not branch:
            raise serializers.ValidationError({"branch": ["Branch is required."]})

        if branch.institution_id != institution.id:
            raise serializers.ValidationError(
                {"branch": ["Selected branch does not belong to the selected institution."]}
            )

        if user and user.role != CustomUser.Role.CLIENT:
            raise serializers.ValidationError(
                {"user": ["Only self-service users with the client role can be linked."]}
            )

        return attrs


class ClientSelfServiceUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = (
            "phone",
            "email",
            "date_of_birth",
            "address",
            "occupation",
            "next_of_kin_name",
            "next_of_kin_phone",
        )
        extra_kwargs = {
            "email": {"required": False, "allow_blank": True},
            "address": {"required": False, "allow_blank": True},
            "occupation": {"required": False, "allow_blank": True},
            "next_of_kin_name": {"required": False, "allow_blank": True},
            "next_of_kin_phone": {"required": False, "allow_blank": True},
        }

    def validate_phone(self, value):
        phone = value.strip()
        if not phone:
            raise serializers.ValidationError("Phone number is required.")
        return phone

    def validate_email(self, value):
        return value.strip().lower()

    def validate_address(self, value):
        return value.strip()

    def validate_occupation(self, value):
        return value.strip()

    def validate_next_of_kin_name(self, value):
        return value.strip()

    def validate_next_of_kin_phone(self, value):
        return value.strip()


class ClientRecentSavingsTransactionSerializer(serializers.ModelSerializer):
    account_number = serializers.CharField(source="account.account_number", read_only=True)

    class Meta:
        model = SavingsTransaction
        fields = (
            "id",
            "account",
            "account_number",
            "type",
            "amount",
            "balance_after",
            "reference",
            "notes",
            "created_at",
        )
        read_only_fields = fields


class ClientRecentLoanSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "product",
            "product_name",
            "amount",
            "term_months",
            "status",
            "principal_balance",
            "interest_balance",
            "disbursed_at",
            "created_at",
        )
        read_only_fields = fields


class ClientRecentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "id",
            "category",
            "direction",
            "amount",
            "reference",
            "description",
            "created_at",
        )
        read_only_fields = fields


class ClientDetailSerializer(ClientSerializer):
    savings_summary = serializers.SerializerMethodField()
    loans_summary = serializers.SerializerMethodField()
    transactions_summary = serializers.SerializerMethodField()
    recent_savings_transactions = serializers.SerializerMethodField()
    recent_loans = serializers.SerializerMethodField()
    recent_transactions = serializers.SerializerMethodField()

    class Meta(ClientSerializer.Meta):
        fields = ClientSerializer.Meta.fields + (
            "savings_summary",
            "loans_summary",
            "transactions_summary",
            "recent_savings_transactions",
            "recent_loans",
            "recent_transactions",
        )

    def get_savings_summary(self, obj):
        accounts = obj.savings_accounts.all()
        summary = accounts.aggregate(
            account_count=Count("id"),
            active_account_count=Count("id", filter=Q(status=StatusChoices.ACTIVE)),
            total_balance=coalesced_sum("balance"),
        )
        summary["transaction_count"] = SavingsTransaction.objects.filter(
            account__client=obj
        ).count()
        summary["total_balance"] = format_decimal(summary["total_balance"])
        return summary

    def get_loans_summary(self, obj):
        open_statuses = [
            LoanApplication.Status.PENDING,
            LoanApplication.Status.APPROVED,
            LoanApplication.Status.DISBURSED,
        ]
        summary = obj.loan_applications.aggregate(
            application_count=Count("id"),
            open_application_count=Count("id", filter=Q(status__in=open_statuses)),
            disbursed_loan_count=Count(
                "id",
                filter=Q(status=LoanApplication.Status.DISBURSED),
            ),
            total_requested_amount=coalesced_sum("amount"),
            outstanding_principal_balance=coalesced_sum("principal_balance"),
            outstanding_interest_balance=coalesced_sum("interest_balance"),
        )
        summary["total_requested_amount"] = format_decimal(summary["total_requested_amount"])
        summary["outstanding_principal_balance"] = format_decimal(
            summary["outstanding_principal_balance"]
        )
        summary["outstanding_interest_balance"] = format_decimal(
            summary["outstanding_interest_balance"]
        )
        return summary

    def get_transactions_summary(self, obj):
        summary = Transaction.objects.filter(client=obj).aggregate(
            count=Count("id"),
            total_credits=coalesced_sum("amount", filter_condition=Q(direction="credit")),
            total_debits=coalesced_sum("amount", filter_condition=Q(direction="debit")),
        )
        net_flow = summary["total_credits"] - summary["total_debits"]
        return {
            "count": summary["count"],
            "total_credits": format_decimal(summary["total_credits"]),
            "total_debits": format_decimal(summary["total_debits"]),
            "net_flow": format_decimal(net_flow),
        }

    def get_recent_savings_transactions(self, obj):
        transactions = (
            SavingsTransaction.objects.filter(account__client=obj)
            .select_related("account")
            .order_by("-created_at")[:5]
        )
        return ClientRecentSavingsTransactionSerializer(transactions, many=True).data

    def get_recent_loans(self, obj):
        loans = obj.loan_applications.select_related("product").order_by("-created_at")[:5]
        return ClientRecentLoanSerializer(loans, many=True).data

    def get_recent_transactions(self, obj):
        transactions = Transaction.objects.filter(client=obj).order_by("-created_at")[:5]
        return ClientRecentTransactionSerializer(transactions, many=True).data
