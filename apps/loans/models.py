from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimeStampedModel


class LoanProduct(TimeStampedModel):
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
    min_term_months = models.PositiveIntegerField(default=1)
    max_term_months = models.PositiveIntegerField(default=24)
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
        ]
        indexes = [
            models.Index(fields=["institution", "is_active"], name="loan_prod_inst_active_idx"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class LoanApplication(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
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
        default=Status.PENDING,
    )
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
        ]
        indexes = [
            models.Index(fields=["loan", "created_at"], name="loan_repay_loan_created_idx"),
        ]

    def __str__(self):
        return self.reference
