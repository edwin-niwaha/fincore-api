from decimal import Decimal
from django.db import models
from apps.common.models import TimeStampedModel

class LoanProduct(TimeStampedModel):
    institution = models.ForeignKey("institutions.Institution", on_delete=models.PROTECT, related_name="loan_products")
    name = models.CharField(max_length=160)
    code = models.SlugField()
    min_amount = models.DecimalField(max_digits=14, decimal_places=2)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2)
    annual_interest_rate = models.DecimalField(max_digits=5, decimal_places=2)
    min_term_months = models.PositiveIntegerField(default=1)
    max_term_months = models.PositiveIntegerField(default=24)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("institution", "code")

class LoanApplication(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DISBURSED = "disbursed", "Disbursed"
        CLOSED = "closed", "Closed"
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="loan_applications")
    product = models.ForeignKey(LoanProduct, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    term_months = models.PositiveIntegerField()
    purpose = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    approved_by = models.ForeignKey("users.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_loans")
    rejected_reason = models.TextField(blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    principal_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    interest_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

class RepaymentSchedule(TimeStampedModel):
    loan = models.ForeignKey(LoanApplication, on_delete=models.CASCADE, related_name="schedule")
    due_date = models.DateField()
    principal_due = models.DecimalField(max_digits=14, decimal_places=2)
    interest_due = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    is_paid = models.BooleanField(default=False)

class LoanRepayment(TimeStampedModel):
    loan = models.ForeignKey(LoanApplication, on_delete=models.PROTECT, related_name="repayments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    principal_component = models.DecimalField(max_digits=14, decimal_places=2)
    interest_component = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    reference = models.CharField(max_length=80, unique=True)
    received_by = models.ForeignKey("users.User", null=True, blank=True, on_delete=models.SET_NULL)
