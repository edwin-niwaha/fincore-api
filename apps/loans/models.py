from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimeStampedModel


class LoanProduct(TimeStampedModel):
    class InterestMethod(models.TextChoices):
        FLAT = "flat", "Flat"
        REDUCING_BALANCE = "reducing_balance", "Reducing Balance"

    class RepaymentFrequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        BIWEEKLY = "biweekly", "Biweekly"
        WEEKLY = "weekly", "Weekly"

    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.PROTECT,
        related_name="loan_products",
    )
    name = models.CharField(max_length=160)
    code = models.SlugField()
    min_amount = models.DecimalField(max_digits=14, decimal_places=2)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2)
    annual_interest_rate = models.DecimalField(max_digits=5, decimal_places=2)
    interest_method = models.CharField(
        max_length=30,
        choices=InterestMethod.choices,
        default=InterestMethod.FLAT,
    )
    repayment_frequency = models.CharField(
        max_length=20,
        choices=RepaymentFrequency.choices,
        default=RepaymentFrequency.MONTHLY,
    )
    min_term_months = models.PositiveIntegerField(default=1)
    max_term_months = models.PositiveIntegerField(default=24)
    default_term_months = models.PositiveIntegerField(null=True, blank=True)
    penalty_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    penalty_flat_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    penalty_grace_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        unique_together = ("institution", "code")
        constraints = [
            models.CheckConstraint(
                condition=Q(min_amount__gt=0),
                name="loan_product_min_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(max_amount__gt=0),
                name="loan_product_max_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(max_amount__gte=models.F("min_amount")),
                name="loan_product_amount_range_valid",
            ),
            models.CheckConstraint(
                condition=Q(annual_interest_rate__gte=0),
                name="loan_product_interest_rate_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(min_term_months__gt=0),
                name="loan_product_min_term_positive",
            ),
            models.CheckConstraint(
                condition=Q(max_term_months__gte=models.F("min_term_months")),
                name="loan_product_term_range_valid",
            ),
            models.CheckConstraint(
                condition=Q(default_term_months__isnull=True)
                | Q(default_term_months__gt=0),
                name="loan_product_default_term_positive_or_null",
            ),
            models.CheckConstraint(
                condition=Q(penalty_rate__gte=0),
                name="loan_product_penalty_rate_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(penalty_flat_amount__gte=0),
                name="loan_product_penalty_flat_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["institution", "is_active"], name="loan_prod_inst_active_idx"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class LoanApplication(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        RECOMMENDED = "recommended", "Recommended"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DISBURSED = "disbursed", "Disbursed"
        CLOSED = "closed", "Closed"

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="loan_applications",
    )
    product = models.ForeignKey(LoanProduct, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    term_months = models.PositiveIntegerField()
    purpose = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_loan_applications",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_loan_applications",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    recommended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recommended_loan_applications",
    )
    recommended_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_loan_applications",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="disbursed_loan_applications",
    )
    disbursement_method = models.CharField(max_length=40, blank=True)
    disbursement_reference = models.CharField(max_length=80, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_loans",
    )
    rejected_reason = models.TextField(blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    principal_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    interest_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="loan_application_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(term_months__gt=0),
                name="loan_application_term_positive",
            ),
            models.CheckConstraint(
                condition=Q(principal_balance__gte=0),
                name="loan_application_principal_balance_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(interest_balance__gte=0),
                name="loan_application_interest_balance_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["client", "status"], name="loan_app_client_status_idx"),
            models.Index(fields=["product", "status"], name="loan_app_product_status_idx"),
        ]

    def __str__(self):
        return f"{self.client.member_number} - {self.amount:.2f}"

    @property
    def client_name(self):
        return f"{self.client.first_name} {self.client.last_name}".strip()

    @property
    def client_member_number(self):
        return self.client.member_number

    @property
    def branch_name(self):
        return self.client.branch.name

    @property
    def institution_name(self):
        return self.client.institution.name

    @property
    def product_name(self):
        return self.product.name

    @property
    def product_code(self):
        return self.product.code

    @property
    def outstanding_balance(self):
        return self.principal_balance + self.interest_balance


class RepaymentSchedule(TimeStampedModel):
    loan = models.ForeignKey(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="schedule",
    )
    due_date = models.DateField()
    principal_due = models.DecimalField(max_digits=14, decimal_places=2)
    interest_due = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    is_paid = models.BooleanField(default=False)

    class Meta(TimeStampedModel.Meta):
        ordering = ["due_date", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(principal_due__gte=0),
                name="repayment_schedule_principal_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(interest_due__gte=0),
                name="repayment_schedule_interest_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(paid_amount__gte=0),
                name="repayment_schedule_paid_amount_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["loan", "due_date"], name="loan_sched_loan_due_idx"),
            models.Index(fields=["loan", "is_paid"], name="loan_sched_loan_paid_idx"),
        ]

    def __str__(self):
        return f"{self.loan_id} due {self.due_date}"

    @property
    def total_due(self):
        return self.principal_due + self.interest_due

    @property
    def outstanding_amount(self):
        outstanding = self.total_due - self.paid_amount
        return outstanding if outstanding > 0 else Decimal("0.00")


class LoanRepayment(TimeStampedModel):
    loan = models.ForeignKey(
        LoanApplication,
        on_delete=models.PROTECT,
        related_name="repayments",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    principal_component = models.DecimalField(max_digits=14, decimal_places=2)
    interest_component = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    penalty_component = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    remaining_balance_after = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    payment_method = models.CharField(max_length=40, blank=True)
    reference = models.CharField(max_length=80, unique=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="loan_repayment_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(principal_component__gte=0),
                name="loan_repayment_principal_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(interest_component__gte=0),
                name="loan_repayment_interest_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(penalty_component__gte=0),
                name="loan_repayment_penalty_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(remaining_balance_after__gte=0),
                name="loan_repayment_remaining_balance_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["loan", "created_at"], name="loan_repay_loan_created_idx"),
        ]

    def __str__(self):
        return self.reference


class LoanApplicationAction(TimeStampedModel):
    class Action(models.TextChoices):
        CREATE = "create", "Create"
        SUBMIT = "submit", "Submit"
        START_REVIEW = "start_review", "Start Review"
        RECOMMEND = "recommend", "Recommend"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        DISBURSE = "disburse", "Disburse"
        REPAY = "repay", "Repay"

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="action_history",
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_application_actions",
    )
    comment = models.TextField(blank=True)
    reference = models.CharField(max_length=80, blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["application", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.application_id} - {self.action}"
