from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import serializers

from apps.common.models import StatusChoices
from apps.loans.models import LoanApplication
from apps.savings.models import SavingsTransaction
from apps.transactions.models import Transaction
from apps.users.models import CustomUser

from .models import (
    Client,
    ClientStatusChoices,
    ClientStatusHistory,
    GenderChoices,
    KycLevelChoices,
    KycStatusChoices,
    MembershipTypeChoices,
    RiskRatingChoices,
)

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
    client_number = serializers.CharField(source="member_number", read_only=True)
    full_name = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    membership_type_display = serializers.CharField(
        source="get_membership_type_display",
        read_only=True,
    )
    kyc_status_display = serializers.CharField(source="get_kyc_status_display", read_only=True)
    kyc_level_display = serializers.CharField(source="get_kyc_level_display", read_only=True)
    risk_rating_display = serializers.CharField(source="get_risk_rating_display", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    user_full_name = serializers.SerializerMethodField()
    profile_photo_url = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True)
    verified_by_email = serializers.EmailField(source="verified_by.email", read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "user",
            "user_email",
            "user_username",
            "user_full_name",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "member_number",
            "client_number",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "email",
            "national_id",
            "passport_number",
            "registration_number",
            "gender",
            "gender_display",
            "date_of_birth",
            "joining_date",
            "membership_type",
            "membership_type_display",
            "address",
            "occupation",
            "employer",
            "next_of_kin_name",
            "next_of_kin_phone",
            "next_of_kin_relationship",
            "profile_photo",
            "profile_photo_url",
            "status",
            "kyc_status",
            "kyc_status_display",
            "kyc_level",
            "kyc_level_display",
            "risk_rating",
            "risk_rating_display",
            "is_watchlist_flagged",
            "verification_comments",
            "verified_by",
            "verified_by_email",
            "verified_at",
            "created_by",
            "created_by_email",
            "updated_by",
            "updated_by_email",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "member_number",
            "client_number",
            "full_name",
            "institution_name",
            "institution_code",
            "branch_name",
            "branch_code",
            "user_email",
            "user_username",
            "user_full_name",
            "gender_display",
            "membership_type_display",
            "kyc_status_display",
            "kyc_level_display",
            "risk_rating_display",
            "profile_photo_url",
            "created_by",
            "created_by_email",
            "updated_by",
            "updated_by_email",
            "verified_by",
            "verified_by_email",
            "verified_at",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "user": {"required": False, "allow_null": True},
            "email": {"required": False, "allow_blank": True},
            "national_id": {"required": False, "allow_blank": True},
            "passport_number": {"required": False, "allow_blank": True},
            "registration_number": {"required": False, "allow_blank": True},
            "gender": {"required": False, "allow_blank": True},
            "address": {"required": False, "allow_blank": True},
            "occupation": {"required": False, "allow_blank": True},
            "employer": {"required": False, "allow_blank": True},
            "next_of_kin_name": {"required": False, "allow_blank": True},
            "next_of_kin_phone": {"required": False, "allow_blank": True},
            "next_of_kin_relationship": {"required": False, "allow_blank": True},
            "kyc_level": {"required": False, "allow_blank": True},
            "verification_comments": {"required": False, "allow_blank": True},
        }

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_profile_photo_url(self, obj):
        if not getattr(obj, "profile_photo", None):
            return None
        try:
            return obj.profile_photo.url
        except Exception:
            return None

    def get_user_full_name(self, obj):
        if not obj.user_id:
            return ""
        return obj.user.get_full_name().strip() or obj.user.username or obj.user.email

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

    def validate_passport_number(self, value):
        return value.strip()

    def validate_registration_number(self, value):
        return value.strip()

    def validate_gender(self, value):
        if not value:
            return ""

        gender = value.strip().lower()
        allowed_values = {choice for choice, _ in GenderChoices.choices}
        if gender not in allowed_values:
            raise serializers.ValidationError("Select a valid gender option.")
        return gender

    def validate_date_of_birth(self, value):
        if value and value > date.today():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def validate_joining_date(self, value):
        if value and value > date.today():
            raise serializers.ValidationError("Joining date cannot be in the future.")
        return value

    def validate_membership_type(self, value):
        membership_type = value.strip().lower()
        allowed_values = {choice for choice, _ in MembershipTypeChoices.choices}
        if membership_type not in allowed_values:
            raise serializers.ValidationError("Select a valid membership type.")
        return membership_type

    def validate_address(self, value):
        return value.strip()

    def validate_occupation(self, value):
        return value.strip()

    def validate_employer(self, value):
        return value.strip()

    def validate_next_of_kin_name(self, value):
        return value.strip()

    def validate_next_of_kin_phone(self, value):
        return value.strip()

    def validate_next_of_kin_relationship(self, value):
        return value.strip()

    def validate_kyc_status(self, value):
        kyc_status = value.strip().lower()
        allowed_values = {choice for choice, _ in KycStatusChoices.choices}
        if kyc_status not in allowed_values:
            raise serializers.ValidationError("Select a valid KYC status.")
        return kyc_status

    def validate_kyc_level(self, value):
        if not value:
            return ""
        kyc_level = value.strip().lower()
        allowed_values = {choice for choice, _ in KycLevelChoices.choices}
        if kyc_level not in allowed_values:
            raise serializers.ValidationError("Select a valid KYC level.")
        return kyc_level

    def validate_risk_rating(self, value):
        risk_rating = value.strip().lower()
        allowed_values = {choice for choice, _ in RiskRatingChoices.choices}
        if risk_rating not in allowed_values:
            raise serializers.ValidationError("Select a valid risk rating.")
        return risk_rating

    def validate_verification_comments(self, value):
        return value.strip()

    def validate(self, attrs):
        institution = attrs.get("institution") or getattr(self.instance, "institution", None)
        branch = attrs.get("branch") or getattr(self.instance, "branch", None)
        user = attrs.get("user", getattr(self.instance, "user", None))
        current_status = attrs.get("status", getattr(self.instance, "status", None))
        kyc_status = attrs.get("kyc_status", getattr(self.instance, "kyc_status", None))

        if not institution:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        if not branch:
            raise serializers.ValidationError({"branch": ["Branch is required."]})

        if branch.institution_id != institution.id:
            raise serializers.ValidationError(
                {"branch": ["Selected branch does not belong to the selected institution."]}
            )

        if user:
            if user.role != CustomUser.Role.CLIENT:
                raise serializers.ValidationError(
                    {"user": ["Only self-service users with the client role can be linked."]}
                )

            if not user.is_active:
                raise serializers.ValidationError(
                    {"user": ["Inactive user accounts cannot be linked to a client."]}
                )

            linked_client_exists = Client.objects.filter(user=user).exclude(
                pk=getattr(self.instance, "pk", None)
            )
            if linked_client_exists.exists():
                raise serializers.ValidationError(
                    {"user": ["This user account is already linked to another client."]}
                )

            if user.institution_id and user.institution_id != institution.id:
                raise serializers.ValidationError(
                    {
                        "user": [
                            "The selected user belongs to a different institution."
                        ]
                    }
                )

            if user.branch_id and user.branch_id != branch.id:
                raise serializers.ValidationError(
                    {"user": ["The selected user belongs to a different branch."]}
                )

        if self.instance is None and "status" not in attrs:
            attrs["status"] = ClientStatusChoices.PENDING

        if current_status == ClientStatusChoices.ACTIVE and kyc_status == KycStatusChoices.REJECTED:
            raise serializers.ValidationError(
                {"status": ["KYC-rejected members cannot remain active."]}
            )

        if current_status == ClientStatusChoices.BLACKLISTED:
            attrs["is_watchlist_flagged"] = True

        return attrs

    def _sync_linked_user_scope(self, client):
        user = client.user
        if not user:
            return

        fields_to_update = []
        if user.institution_id != client.institution_id:
            user.institution = client.institution
            fields_to_update.append("institution")
        if user.branch_id != client.branch_id:
            user.branch = client.branch
            fields_to_update.append("branch")
        if fields_to_update:
            user.save(update_fields=fields_to_update)

    def create(self, validated_data):
        client = super().create(validated_data)
        self._sync_linked_user_scope(client)
        return client

    def update(self, instance, validated_data):
        client = super().update(instance, validated_data)
        self._sync_linked_user_scope(client)
        return client


class ClientSelfServiceUpdateSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        unexpected_fields = sorted(set(data.keys()) - set(self.fields.keys()))
        if unexpected_fields:
            raise serializers.ValidationError(
                {
                    field_name: ["This field is not allowed."]
                    for field_name in unexpected_fields
                }
            )
        return super().to_internal_value(data)

    class Meta:
        model = Client
        fields = (
            "phone",
            "email",
            "address",
        )
        extra_kwargs = {
            "email": {"required": False, "allow_blank": True},
            "address": {"required": False, "allow_blank": True},
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


class ClientStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.EmailField(source="changed_by.email", read_only=True)

    class Meta:
        model = ClientStatusHistory
        fields = (
            "id",
            "from_status",
            "to_status",
            "changed_by",
            "changed_by_email",
            "reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ClientDetailSerializer(ClientSerializer):
    savings_summary = serializers.SerializerMethodField()
    loans_summary = serializers.SerializerMethodField()
    transactions_summary = serializers.SerializerMethodField()
    recent_savings_transactions = serializers.SerializerMethodField()
    recent_loans = serializers.SerializerMethodField()
    recent_transactions = serializers.SerializerMethodField()
    status_history = serializers.SerializerMethodField()

    class Meta(ClientSerializer.Meta):
        fields = ClientSerializer.Meta.fields + (
            "savings_summary",
            "loans_summary",
            "transactions_summary",
            "recent_savings_transactions",
            "recent_loans",
            "recent_transactions",
            "status_history",
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
            LoanApplication.Status.SUBMITTED,
            LoanApplication.Status.UNDER_REVIEW,
            LoanApplication.Status.RECOMMENDED,
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

    def get_status_history(self, obj):
        history_rows = obj.status_history.select_related("changed_by").order_by("-created_at")[:10]
        return ClientStatusHistorySerializer(history_rows, many=True).data


class ClientKycVerificationSerializer(serializers.Serializer):
    kyc_status = serializers.ChoiceField(choices=KycStatusChoices.choices)
    kyc_level = serializers.ChoiceField(
        choices=KycLevelChoices.choices,
        required=False,
        allow_blank=True,
    )
    risk_rating = serializers.ChoiceField(
        choices=RiskRatingChoices.choices,
        required=False,
        default=RiskRatingChoices.LOW,
    )
    is_watchlist_flagged = serializers.BooleanField(required=False, default=False)
    verification_comments = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        kyc_status = attrs.get("kyc_status")
        kyc_level = attrs.get("kyc_level", "")
        verification_comments = (attrs.get("verification_comments") or "").strip()

        if kyc_status == KycStatusChoices.VERIFIED and not kyc_level:
            raise serializers.ValidationError(
                {"kyc_level": ["Select a KYC level when verification succeeds."]}
            )

        if kyc_status == KycStatusChoices.REJECTED and not verification_comments:
            raise serializers.ValidationError(
                {"verification_comments": ["Provide verification comments when rejecting KYC."]}
            )

        attrs["verification_comments"] = verification_comments
        return attrs


class ClientStatusChangeSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate_reason(self, value):
        return value.strip()


class LinkableClientUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    linked_client_id = serializers.UUIDField(source="client_profile.id", read_only=True)
    linked_client_member_number = serializers.CharField(
        source="client_profile.member_number",
        read_only=True,
    )

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "email",
            "username",
            "full_name",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "is_active",
            "is_email_verified",
            "linked_client_id",
            "linked_client_member_number",
        )
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name().strip() or obj.username or obj.email
