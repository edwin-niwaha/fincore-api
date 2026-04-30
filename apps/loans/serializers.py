from decimal import Decimal

from rest_framework import serializers

from .models import (
    LoanApplication,
    LoanApplicationAction,
    LoanProduct,
    LoanRepayment,
    RepaymentSchedule,
)
from .services import LoanService

ZERO_DECIMAL = Decimal("0.00")


class LoanProductSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    application_count = serializers.SerializerMethodField()
    total_requested_amount = serializers.SerializerMethodField()

    class Meta:
        model = LoanProduct
        fields = (
            "id",
            "institution",
            "institution_name",
            "name",
            "code",
            "min_amount",
            "max_amount",
            "annual_interest_rate",
            "interest_method",
            "repayment_frequency",
            "min_term_months",
            "max_term_months",
            "default_term_months",
            "penalty_rate",
            "penalty_flat_amount",
            "penalty_grace_days",
            "is_active",
            "application_count",
            "total_requested_amount",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "institution_name",
            "application_count",
            "total_requested_amount",
            "created_at",
            "updated_at",
        )

    def get_application_count(self, obj):
        if hasattr(obj, "application_count"):
            return obj.application_count
        return obj.loanapplication_set.count()

    def get_total_requested_amount(self, obj):
        value = getattr(obj, "total_requested_amount", ZERO_DECIMAL)
        return f"{Decimal(str(value or ZERO_DECIMAL)):.2f}"

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Name is required.")
        return name

    def validate_code(self, value):
        code = value.strip().lower()
        if not code:
            raise serializers.ValidationError("Code is required.")
        return code

    def validate(self, attrs):
        min_amount = attrs.get("min_amount", getattr(self.instance, "min_amount", None))
        max_amount = attrs.get("max_amount", getattr(self.instance, "max_amount", None))
        annual_interest_rate = attrs.get(
            "annual_interest_rate",
            getattr(self.instance, "annual_interest_rate", None),
        )
        min_term = attrs.get(
            "min_term_months",
            getattr(self.instance, "min_term_months", None),
        )
        max_term = attrs.get(
            "max_term_months",
            getattr(self.instance, "max_term_months", None),
        )
        default_term = attrs.get(
            "default_term_months",
            getattr(self.instance, "default_term_months", None),
        )
        penalty_rate = attrs.get(
            "penalty_rate",
            getattr(self.instance, "penalty_rate", None),
        )
        penalty_flat_amount = attrs.get(
            "penalty_flat_amount",
            getattr(self.instance, "penalty_flat_amount", None),
        )
        penalty_grace_days = attrs.get(
            "penalty_grace_days",
            getattr(self.instance, "penalty_grace_days", None),
        )

        if min_amount is not None and min_amount <= ZERO_DECIMAL:
            raise serializers.ValidationError({"min_amount": ["Minimum amount must be positive."]})
        if max_amount is not None and max_amount <= ZERO_DECIMAL:
            raise serializers.ValidationError({"max_amount": ["Maximum amount must be positive."]})
        if min_amount is not None and max_amount is not None and max_amount < min_amount:
            raise serializers.ValidationError(
                {"max_amount": ["Maximum amount must be greater than or equal to minimum amount."]}
            )
        if annual_interest_rate is not None and annual_interest_rate < ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"annual_interest_rate": ["Interest rate cannot be negative."]}
            )
        if min_term is not None and min_term <= 0:
            raise serializers.ValidationError(
                {"min_term_months": ["Minimum term must be greater than zero."]}
            )
        if max_term is not None and max_term <= 0:
            raise serializers.ValidationError(
                {"max_term_months": ["Maximum term must be greater than zero."]}
            )
        if min_term is not None and max_term is not None and max_term < min_term:
            raise serializers.ValidationError(
                {
                    "max_term_months": [
                        "Maximum term must be greater than or equal to minimum term."
                    ]
                }
            )
        if default_term is not None:
            if default_term <= 0:
                raise serializers.ValidationError(
                    {"default_term_months": ["Default term must be greater than zero."]}
                )
            if min_term is not None and default_term < min_term:
                raise serializers.ValidationError(
                    {"default_term_months": ["Default term cannot be below the minimum term."]}
                )
            if max_term is not None and default_term > max_term:
                raise serializers.ValidationError(
                    {"default_term_months": ["Default term cannot exceed the maximum term."]}
                )
        if penalty_rate is not None and penalty_rate < ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"penalty_rate": ["Penalty rate cannot be negative."]}
            )
        if penalty_flat_amount is not None and penalty_flat_amount < ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"penalty_flat_amount": ["Penalty flat amount cannot be negative."]}
            )
        if penalty_grace_days is not None and penalty_grace_days < 0:
            raise serializers.ValidationError(
                {"penalty_grace_days": ["Penalty grace days cannot be negative."]}
            )

        return attrs


class RepaymentScheduleSerializer(serializers.ModelSerializer):
    total_due = serializers.SerializerMethodField()
    outstanding_amount = serializers.SerializerMethodField()

    class Meta:
        model = RepaymentSchedule
        fields = (
            "id",
            "loan",
            "due_date",
            "principal_due",
            "interest_due",
            "paid_amount",
            "is_paid",
            "total_due",
            "outstanding_amount",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_total_due(self, obj):
        return f"{obj.total_due:.2f}"

    def get_outstanding_amount(self, obj):
        return f"{obj.outstanding_amount:.2f}"


class LoanRepaymentSerializer(serializers.ModelSerializer):
    loan_client_name = serializers.CharField(source="loan.client_name", read_only=True)
    loan_client_member_number = serializers.CharField(
        source="loan.client_member_number",
        read_only=True,
    )
    received_by_email = serializers.EmailField(source="received_by.email", read_only=True)

    class Meta:
        model = LoanRepayment
        fields = (
            "id",
            "loan",
            "loan_client_name",
            "loan_client_member_number",
            "amount",
            "principal_component",
            "interest_component",
            "penalty_component",
            "remaining_balance_after",
            "payment_method",
            "reference",
            "received_by",
            "received_by_email",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "principal_component",
            "interest_component",
            "penalty_component",
            "remaining_balance_after",
            "received_by",
            "received_by_email",
            "created_at",
            "updated_at",
        )


class LoanApplicationSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_member_number = serializers.CharField(source="client.member_number", read_only=True)
    branch_name = serializers.CharField(source="client.branch.name", read_only=True)
    institution_id = serializers.UUIDField(source="client.institution_id", read_only=True)
    institution_name = serializers.CharField(source="client.institution.name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    annual_interest_rate = serializers.DecimalField(
        source="product.annual_interest_rate",
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )
    interest_method = serializers.CharField(source="product.interest_method", read_only=True)
    repayment_frequency = serializers.CharField(
        source="product.repayment_frequency",
        read_only=True,
    )
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)
    submitted_by_email = serializers.EmailField(source="submitted_by.email", read_only=True)
    recommended_by_email = serializers.EmailField(
        source="recommended_by.email",
        read_only=True,
    )
    approved_by_email = serializers.EmailField(source="approved_by.email", read_only=True)
    rejected_by_email = serializers.EmailField(source="rejected_by.email", read_only=True)
    disbursed_by_email = serializers.EmailField(source="disbursed_by.email", read_only=True)
    repayment_count = serializers.SerializerMethodField()
    schedule_count = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()

    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "client",
            "client_name",
            "client_member_number",
            "branch_name",
            "institution_id",
            "institution_name",
            "product",
            "product_name",
            "product_code",
            "annual_interest_rate",
            "interest_method",
            "repayment_frequency",
            "amount",
            "term_months",
            "purpose",
            "status",
            "created_by",
            "created_by_email",
            "submitted_by",
            "submitted_by_email",
            "submitted_at",
            "reviewed_at",
            "recommended_by",
            "recommended_by_email",
            "recommended_at",
            "approved_by",
            "approved_by_email",
            "approved_at",
            "rejected_by",
            "rejected_by_email",
            "rejected_at",
            "rejected_reason",
            "disbursed_at",
            "disbursed_by",
            "disbursed_by_email",
            "disbursement_method",
            "disbursement_reference",
            "principal_balance",
            "interest_balance",
            "outstanding_balance",
            "next_due_date",
            "repayment_count",
            "schedule_count",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "client": {"required": False},
        }
        read_only_fields = (
            "id",
            "client_name",
            "client_member_number",
            "branch_name",
            "institution_id",
            "institution_name",
            "product_name",
            "product_code",
            "annual_interest_rate",
            "interest_method",
            "repayment_frequency",
            "status",
            "created_by",
            "created_by_email",
            "submitted_by",
            "submitted_by_email",
            "submitted_at",
            "reviewed_at",
            "recommended_by",
            "recommended_by_email",
            "recommended_at",
            "approved_by",
            "approved_by_email",
            "approved_at",
            "rejected_by",
            "rejected_by_email",
            "rejected_at",
            "rejected_reason",
            "disbursed_at",
            "disbursed_by",
            "disbursed_by_email",
            "disbursement_method",
            "disbursement_reference",
            "principal_balance",
            "interest_balance",
            "outstanding_balance",
            "next_due_date",
            "repayment_count",
            "schedule_count",
            "created_at",
            "updated_at",
        )

    def get_client_name(self, obj):
        return f"{obj.client.first_name} {obj.client.last_name}".strip()

    def get_repayment_count(self, obj):
        if hasattr(obj, "repayment_count"):
            return obj.repayment_count
        return obj.repayments.count()

    def get_schedule_count(self, obj):
        if hasattr(obj, "schedule_count"):
            return obj.schedule_count
        return obj.schedule.count()

    def get_outstanding_balance(self, obj):
        return f"{(obj.principal_balance + obj.interest_balance):.2f}"

    def get_next_due_date(self, obj):
        next_schedule = (
            obj.schedule.filter(is_paid=False).order_by("due_date", "created_at").first()
        )
        if next_schedule is None:
            return None
        return next_schedule.due_date

    def validate_purpose(self, value):
        return value.strip()

    def validate(self, attrs):
        request = self.context.get("request")
        product = attrs.get("product") or getattr(self.instance, "product", None)
        client = attrs.get("client") or getattr(self.instance, "client", None)
        amount = attrs.get("amount") or getattr(self.instance, "amount", None)
        term = attrs.get("term_months") or getattr(self.instance, "term_months", None)

        if (
            request
            and request.user.is_authenticated
            and request.user.role == LoanService.CLIENT_ROLE
        ):
            if not client and hasattr(request.user, "client_profile"):
                client = request.user.client_profile
                attrs["client"] = client
            elif client and client.user_id != request.user.id:
                raise serializers.ValidationError(
                    {"client": ["Client users can only apply using their own client profile."]}
                )

        if not client:
            raise serializers.ValidationError({"client": ["Client is required."]})

        if not product:
            raise serializers.ValidationError({"product": ["Loan product is required."]})

        if client.institution_id != product.institution_id:
            raise serializers.ValidationError(
                {"product": ["Loan product must belong to the same institution as the client."]}
            )

        if not product.is_active:
            raise serializers.ValidationError({"product": ["Selected loan product is inactive."]})

        if amount is not None and term is not None:
            LoanService.validate_application(product, amount, term)

        if self.instance:
            restricted_fields = set(attrs.keys()) - {"purpose"}
            if self.instance.status in {
                LoanApplication.Status.APPROVED,
                LoanApplication.Status.REJECTED,
                LoanApplication.Status.DISBURSED,
                LoanApplication.Status.CLOSED,
            } and restricted_fields:
                raise serializers.ValidationError(
                    "Approved, rejected, disbursed, or closed applications cannot be edited."
                )

            if self.instance.status in {
                LoanApplication.Status.UNDER_REVIEW,
                LoanApplication.Status.RECOMMENDED,
            } and restricted_fields:
                raise serializers.ValidationError(
                    "Only the purpose can be updated after an application enters review."
                )

        return attrs


class LoanApplicationActionSerializer(serializers.ModelSerializer):
    acted_by_email = serializers.EmailField(source="acted_by.email", read_only=True)
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = LoanApplicationAction
        fields = (
            "id",
            "application",
            "action",
            "action_label",
            "from_status",
            "to_status",
            "acted_by",
            "acted_by_email",
            "comment",
            "reference",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class LoanApplicationDetailSerializer(LoanApplicationSerializer):
    schedule = serializers.SerializerMethodField()
    repayments = serializers.SerializerMethodField()
    action_history = serializers.SerializerMethodField()

    class Meta(LoanApplicationSerializer.Meta):
        fields = LoanApplicationSerializer.Meta.fields + (
            "schedule",
            "repayments",
            "action_history",
        )
        read_only_fields = fields

    def get_schedule(self, obj):
        schedule_rows = obj.schedule.order_by("due_date", "created_at")
        return RepaymentScheduleSerializer(schedule_rows, many=True).data

    def get_repayments(self, obj):
        repayments = obj.repayments.select_related("received_by").order_by("-created_at")
        return LoanRepaymentSerializer(repayments, many=True).data

    def get_action_history(self, obj):
        history = obj.action_history.select_related("acted_by").order_by("created_at", "id")
        return LoanApplicationActionSerializer(history, many=True).data


class LoanActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
    comment = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)
    disbursement_method = serializers.CharField(required=False, allow_blank=True)
    override = serializers.BooleanField(required=False, default=False)

    def validate_reason(self, value):
        return value.strip()

    def validate_comment(self, value):
        return value.strip()

    def validate_reference(self, value):
        return value.strip()

    def validate_disbursement_method(self, value):
        return value.strip()


class LoanRepaymentCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(max_length=80)
    payment_method = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= ZERO_DECIMAL:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_reference(self, value):
        reference = value.strip()
        if not reference:
            raise serializers.ValidationError("Reference is required.")
        return reference

    def validate_payment_method(self, value):
        return value.strip()
