from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.audit.services import AuditService
from apps.transactions.models import Transaction
from .models import LoanRepayment, RepaymentSchedule

class LoanService:
    @staticmethod
    def validate_application(product, amount, term_months):
        amount = Decimal(str(amount))
        if amount < product.min_amount or amount > product.max_amount:
            raise ValidationError("Loan amount is outside product limits.")
        if term_months < product.min_term_months or term_months > product.max_term_months:
            raise ValidationError("Loan term is outside product limits.")

    @staticmethod
    @transaction.atomic
    def approve(*, loan, user):
        if loan.status != "pending":
            raise ValidationError("Only pending loans can be approved.")
        loan.status = "approved"
        loan.approved_by = user
        loan.save(update_fields=["status", "approved_by", "updated_at"])
        AuditService.log(user=user, action="loan.approve", target=str(loan.id))
        return loan

    @staticmethod
    @transaction.atomic
    def reject(*, loan, user, reason=""):
        if loan.status != "pending":
            raise ValidationError("Only pending loans can be rejected.")
        loan.status = "rejected"
        loan.rejected_reason = reason
        loan.save(update_fields=["status", "rejected_reason", "updated_at"])
        AuditService.log(user=user, action="loan.reject", target=str(loan.id), metadata={"reason": reason})
        return loan

    @staticmethod
    @transaction.atomic
    def disburse(*, loan, user, reference):
        loan = type(loan).objects.select_for_update().select_related("client__institution", "client__branch", "product").get(pk=loan.pk)
        if loan.status != "approved":
            raise ValidationError("Only approved loans can be disbursed.")
        monthly_principal = (loan.amount / Decimal(loan.term_months)).quantize(Decimal("0.01"))
        monthly_interest = ((loan.amount * loan.product.annual_interest_rate / Decimal("100")) / Decimal("12")).quantize(Decimal("0.01"))
        for month in range(1, loan.term_months + 1):
            RepaymentSchedule.objects.create(
                loan=loan,
                due_date=(timezone.localdate() + timezone.timedelta(days=30 * month)),
                principal_due=monthly_principal,
                interest_due=monthly_interest,
            )
        loan.status = "disbursed"
        loan.disbursed_at = timezone.now()
        loan.principal_balance = loan.amount
        loan.interest_balance = monthly_interest * Decimal(loan.term_months)
        loan.save(update_fields=["status", "disbursed_at", "principal_balance", "interest_balance", "updated_at"])
        Transaction.objects.create(institution=loan.client.institution, branch=loan.client.branch, client=loan.client, category="loan_disbursement", direction="debit", amount=loan.amount, reference=reference, description="Loan disbursement", created_by=user)
        AuditService.log(user=user, action="loan.disburse", target=str(loan.id), metadata={"reference": reference})
        return loan

    @staticmethod
    @transaction.atomic
    def repay(*, loan, amount, reference, received_by):
        loan = type(loan).objects.select_for_update().select_related("client__institution", "client__branch").get(pk=loan.pk)
        amount = Decimal(str(amount))
        if loan.status != "disbursed":
            raise ValidationError("Only disbursed loans can receive repayments.")
        if amount <= 0:
            raise ValidationError("Repayment amount must be positive.")
        interest_component = min(amount, loan.interest_balance)
        principal_component = min(amount - interest_component, loan.principal_balance)
        loan.interest_balance -= interest_component
        loan.principal_balance -= principal_component
        if loan.principal_balance <= 0 and loan.interest_balance <= 0:
            loan.status = "closed"
        loan.save(update_fields=["principal_balance", "interest_balance", "status", "updated_at"])
        repayment = LoanRepayment.objects.create(loan=loan, amount=amount, principal_component=principal_component, interest_component=interest_component, reference=reference, received_by=received_by)
        Transaction.objects.create(institution=loan.client.institution, branch=loan.client.branch, client=loan.client, category="loan_repayment", direction="credit", amount=amount, reference=reference, description="Loan repayment", created_by=received_by)
        AuditService.log(user=received_by, action="loan.repay", target=str(loan.id), metadata={"reference": reference, "amount": str(amount)})
        return repayment
