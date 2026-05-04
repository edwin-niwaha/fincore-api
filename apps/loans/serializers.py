from decimal import Decimal

from rest_framework import serializers

from apps.clients.models import Client, ClientStatusChoices

from .models import (
    LoanApplication,
    LoanApplicationAction,
    LoanAppraisal,
    LoanProduct,
    LoanRepayment,
    RepaymentSchedule,
)
from .services import LoanService

ZERO_DECIMAL = Decimal("0.00")


def normalize_loan_eligibility_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return None

    raw_checks = snapshot.get("checks")
    normalized_checks = []
    if isinstance(raw_checks, list):
        for check in raw_checks:
            if not isinstance(check, dict) or "code" not in check:
                continue

            normalized_checks.append(
                {
                    "code": str(check.get("code", "")).strip(),
                    "label": check.get("label"),
                    "passed": bool(check.get("passed")),
                    "message": check.get("message", ""),
                    "value": check.get("value"),
                    "threshold": check.get("threshold"),
                }
            )

    raw_summary = snapshot.get("summary")
    normalized_summary = raw_summary if isinstance(raw_summary, dict) else {}

    raw_errors = snapshot.get("errors")
    if isinstance(raw_errors, list):
        normalized_errors = [str(item) for item in raw_errors if item not in (None, "")]
    elif isinstance(raw_errors, str) and raw_errors.strip():
        normalized_errors = [raw_errors.strip()]
    else:
        normalized_errors = []

    if (
        "eligible" not in snapshot
        and not normalized_checks
        and not normalized_summary
        and not normalized_errors
    ):
        return None

    return {
        "eligible": bool(snapshot.get("eligible", False)),
        "checks": normalized_checks,
        "summary": normalized_summary,
        "errors": normalized_errors,
    }


class LoanProductSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    application_count = serializers.SerializerMethodField()
    total_requested_amount = serializers.SerializerMethodField()
    receivable_account_name = serializers.CharField(
        source="receivable_account.name",
        read_only=True,
    )
    funding_account_name = serializers.CharField(
        source="funding_account.name",
        read_only=True,
    )
    interest_income_account_name = serializers.CharField(
        source="interest_income_account.name",
        read_only=True,
    )

    class Meta:
        model = LoanProduct
        fields = (
            "id",
            "institution",
            "institution_name",
            "name",
            "code",
            "description",
            "min_amount",
            "max_amount",
            "annual_interest_rate",
            "interest_method",
            "repayment_frequency",
            "min_term_months",
            "max_term_months",
            "default_term_months",
            "grace_period_days",
            "penalty_rate",
            "penalty_flat_amount",
            "penalty_grace_days",
            "minimum_savings_balance",
            "minimum_share_capital",
            "max_outstanding_loans",
            "max_amount_to_savings_ratio",
            "max_amount_to_share_ratio",
            "debt_to_income_limit",
            "receivable_account",
            "receivable_account_name",
            "funding_account",
            "funding_account_name",
            "interest_income_account",
            "interest_income_account_name",
            "is_active",
            "application_count",
            "total_requested_amount",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "institution_name",
            "receivable_account_name",
            "funding_account_name",
            "interest_income_account_name",
            "application_count",
            "total_requested_amount",
            "created_at",
            "updated_at",
        )
        validators = []

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

    def validate_description(self, value):
        return value.strip()

    def _validate_account_mapping(self, *, account, institution, field_name):
        if account is None:
            return

        if institution is None:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        if account.institution_id != institution.id:
            raise serializers.ValidationError(
                {field_name: ["Selected ledger account must belong to the same institution."]}
            )

        if not account.is_active:
            raise serializers.ValidationError(
                {field_name: ["Selected ledger account must be active."]}
            )

    def validate(self, attrs):
        institution = attrs.get("institution", getattr(self.instance, "institution", None))
        code = attrs.get("code", getattr(self.instance, "code", ""))
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
        grace_period_days = attrs.get(
            "grace_period_days",
            getattr(self.instance, "grace_period_days", 0),
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
        minimum_savings_balance = attrs.get(
            "minimum_savings_balance",
            getattr(self.instance, "minimum_savings_balance", ZERO_DECIMAL),
        )
        minimum_share_capital = attrs.get(
            "minimum_share_capital",
            getattr(self.instance, "minimum_share_capital", ZERO_DECIMAL),
        )
        max_outstanding_loans = attrs.get(
            "max_outstanding_loans",
            getattr(self.instance, "max_outstanding_loans", None),
        )
        max_amount_to_savings_ratio = attrs.get(
            "max_amount_to_savings_ratio",
            getattr(self.instance, "max_amount_to_savings_ratio", None),
        )
        max_amount_to_share_ratio = attrs.get(
            "max_amount_to_share_ratio",
            getattr(self.instance, "max_amount_to_share_ratio", None),
        )
        debt_to_income_limit = attrs.get(
            "debt_to_income_limit",
            getattr(self.instance, "debt_to_income_limit", None),
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
        if grace_period_days is not None and grace_period_days < 0:
            raise serializers.ValidationError(
                {"grace_period_days": ["Grace period days cannot be negative."]}
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
        if minimum_savings_balance is not None and minimum_savings_balance < ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"minimum_savings_balance": ["Minimum savings balance cannot be negative."]}
            )
        if minimum_share_capital is not None and minimum_share_capital < ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"minimum_share_capital": ["Minimum share capital cannot be negative."]}
            )
        if max_outstanding_loans is not None and max_outstanding_loans <= 0:
            raise serializers.ValidationError(
                {"max_outstanding_loans": ["Maximum outstanding loans must be greater than zero."]}
            )
        if (
            max_amount_to_savings_ratio is not None
            and max_amount_to_savings_ratio <= ZERO_DECIMAL
        ):
            raise serializers.ValidationError(
                {"max_amount_to_savings_ratio": ["Savings ratio must be greater than zero."]}
            )
        if max_amount_to_share_ratio is not None and max_amount_to_share_ratio <= ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"max_amount_to_share_ratio": ["Share ratio must be greater than zero."]}
            )
        if debt_to_income_limit is not None and debt_to_income_limit <= ZERO_DECIMAL:
            raise serializers.ValidationError(
                {"debt_to_income_limit": ["Debt-to-income limit must be greater than zero."]}
            )

        if institution is None:
            raise serializers.ValidationError({"institution": ["Institution is required."]})

        product_qs = LoanProduct.objects.filter(institution=institution, code__iexact=code)
        if self.instance:
            product_qs = product_qs.exclude(pk=self.instance.pk)
        if product_qs.exists():
            raise serializers.ValidationError(
                {"code": ["A loan product with this code already exists for that institution."]}
            )

        self._validate_account_mapping(
            account=attrs.get("receivable_account", getattr(self.instance, "receivable_account", None)),
            institution=institution,
            field_name="receivable_account",
        )
        self._validate_account_mapping(
            account=attrs.get("funding_account", getattr(self.instance, "funding_account", None)),
            institution=institution,
            field_name="funding_account",
        )
        self._validate_account_mapping(
            account=attrs.get(
                "interest_income_account",
                getattr(self.instance, "interest_income_account", None),
            ),
            institution=institution,
            field_name="interest_income_account",
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


class LoanAppraisalSerializer(serializers.ModelSerializer):
    performed_by_email = serializers.EmailField(source="performed_by.email", read_only=True)
    recommendation_label = serializers.CharField(
        source="get_recommendation_display",
        read_only=True,
    )

    class Meta:
        model = LoanAppraisal
        fields = (
            "id",
            "application",
            "performed_by",
            "performed_by_email",
            "recommendation",
            "recommendation_label",
            "recommended_amount",
            "recommended_term_months",
            "monthly_income",
            "monthly_expenses",
            "existing_debt_payments",
            "affordability_amount",
            "estimated_installment",
            "risk_score",
            "savings_balance_snapshot",
            "share_capital_snapshot",
            "outstanding_loans_snapshot",
            "overdue_loans_snapshot",
            "eligibility_passed",
            "collateral_notes",
            "guarantor_notes",
            "credit_comments",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


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
    appraised_by_email = serializers.EmailField(source="appraised_by.email", read_only=True)
    recommended_by_email = serializers.EmailField(
        source="recommended_by.email",
        read_only=True,
    )
    approved_by_email = serializers.EmailField(source="approved_by.email", read_only=True)
    rejected_by_email = serializers.EmailField(source="rejected_by.email", read_only=True)
    withdrawn_by_email = serializers.EmailField(source="withdrawn_by.email", read_only=True)
    disbursed_by_email = serializers.EmailField(source="disbursed_by.email", read_only=True)
    repayment_count = serializers.SerializerMethodField()
    schedule_count = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()
    eligibility_snapshot = serializers.SerializerMethodField()

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
            "repayment_source",
            "status",
            "created_by",
            "created_by_email",
            "submitted_by",
            "submitted_by_email",
            "submitted_at",
            "reviewed_at",
            "appraised_by",
            "appraised_by_email",
            "appraised_at",
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
            "withdrawn_by",
            "withdrawn_by_email",
            "withdrawn_at",
            "withdrawal_reason",
            "disbursed_at",
            "disbursed_by",
            "disbursed_by_email",
            "disbursement_method",
            "disbursement_reference",
            "eligibility_snapshot",
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
            "appraised_by",
            "appraised_by_email",
            "appraised_at",
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
            "withdrawn_by",
            "withdrawn_by_email",
            "withdrawn_at",
            "withdrawal_reason",
            "disbursed_at",
            "disbursed_by",
            "disbursed_by_email",
            "disbursement_method",
            "disbursement_reference",
            "eligibility_snapshot",
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

    def get_eligibility_snapshot(self, obj):
        return normalize_loan_eligibility_snapshot(obj.eligibility_snapshot)

    def validate_purpose(self, value):
        return value.strip()

    def validate_repayment_source(self, value):
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
        if client.status != ClientStatusChoices.ACTIVE:
            raise serializers.ValidationError(
                {"client": ["Only active clients can submit or save loan applications."]}
            )

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
                LoanApplication.Status.WITHDRAWN,
                LoanApplication.Status.DISBURSED,
                LoanApplication.Status.CLOSED,
                LoanApplication.Status.WRITTEN_OFF,
            } and restricted_fields:
                raise serializers.ValidationError(
                    "Approved, rejected, withdrawn, disbursed, closed, or written-off applications cannot be edited."
                )

            if self.instance.status in {
                LoanApplication.Status.UNDER_REVIEW,
                LoanApplication.Status.APPRAISED,
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
    appraisals = serializers.SerializerMethodField()

    class Meta(LoanApplicationSerializer.Meta):
        fields = LoanApplicationSerializer.Meta.fields + (
            "schedule",
            "repayments",
            "action_history",
            "appraisals",
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

    def get_appraisals(self, obj):
        history = obj.appraisals.select_related("performed_by").order_by("-created_at", "-id")
        return LoanAppraisalSerializer(history, many=True).data


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


class LoanEligibilityCheckSerializer(serializers.Serializer):
    client = serializers.PrimaryKeyRelatedField(queryset=Client.objects.all(), required=False)
    product = serializers.PrimaryKeyRelatedField(queryset=LoanProduct.objects.all())
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    term_months = serializers.IntegerField(min_value=1)
    monthly_income = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
    )
    monthly_expenses = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
    )
    existing_debt_payments = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
    )

    def validate(self, attrs):
        request = self.context.get("request")
        client_id = attrs.get("client")

        if request and request.user.is_authenticated and request.user.role == LoanService.CLIENT_ROLE:
            if hasattr(request.user, "client_profile"):
                attrs["client"] = request.user.client_profile
            else:
                raise serializers.ValidationError(
                    {"client": ["Your user account is not linked to a client profile."]}
                )
        else:
            if not client_id:
                raise serializers.ValidationError({"client": ["Client is required."]})
            attrs["client"] = client_id

        return attrs


class LoanAppraisalCreateSerializer(serializers.Serializer):
    recommendation = serializers.ChoiceField(choices=LoanAppraisal.Recommendation.choices)
    recommended_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    recommended_term_months = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
    )
    monthly_income = serializers.DecimalField(max_digits=14, decimal_places=2)
    monthly_expenses = serializers.DecimalField(max_digits=14, decimal_places=2, default=ZERO_DECIMAL)
    existing_debt_payments = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=ZERO_DECIMAL,
    )
    risk_score = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100)
    collateral_notes = serializers.CharField(required=False, allow_blank=True)
    guarantor_notes = serializers.CharField(required=False, allow_blank=True)
    credit_comments = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_recommended_amount(self, value):
        if value is not None and value <= ZERO_DECIMAL:
            raise serializers.ValidationError("Recommended amount must be greater than zero.")
        return value

    def validate_monthly_income(self, value):
        if value < ZERO_DECIMAL:
            raise serializers.ValidationError("Monthly income cannot be negative.")
        return value

    def validate_monthly_expenses(self, value):
        if value < ZERO_DECIMAL:
            raise serializers.ValidationError("Monthly expenses cannot be negative.")
        return value

    def validate_existing_debt_payments(self, value):
        if value < ZERO_DECIMAL:
            raise serializers.ValidationError("Existing debt payments cannot be negative.")
        return value

    def validate_collateral_notes(self, value):
        return value.strip()

    def validate_guarantor_notes(self, value):
        return value.strip()

    def validate_credit_comments(self, value):
        return value.strip()

    def validate_notes(self, value):
        return value.strip()

    def validate(self, attrs):
        if (
            attrs.get("recommendation") == LoanAppraisal.Recommendation.MODIFY
            and attrs.get("recommended_amount") in (None, "")
            and attrs.get("recommended_term_months") in (None, "")
        ):
            raise serializers.ValidationError(
                "Modification appraisals must include a recommended amount or recommended term."
            )
        return attrs


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
