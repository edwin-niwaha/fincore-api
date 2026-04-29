import calendar
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounting.services import AccountingPostingService
from apps.audit.services import AuditService
from apps.transactions.models import Transaction
from apps.transactions.services import TransactionLedgerService

from .models import LoanApplication, LoanRepayment, RepaymentSchedule

ZERO_DECIMAL = Decimal("0.00")
CENT = Decimal("0.01")


class LoanService:
    @staticmethod
    def _normalize_amount(amount):
        normalized_amount = Decimal(str(amount)).quantize(CENT)
        if normalized_amount <= ZERO_DECIMAL:
            raise ValidationError("Amount must be greater than zero.")
        return normalized_amount

    @staticmethod
    def _normalize_reference(reference):
        normalized_reference = str(reference or "").strip()
        if not normalized_reference:
            raise ValidationError({"reference": ["Reference is required."]})
        return normalized_reference

    @staticmethod
    def _duplicate_reference_error():
        return ValidationError({"reference": ["A transaction with this reference already exists."]})

    @classmethod
    def _ensure_reference_available(cls, reference):
        if LoanRepayment.objects.filter(reference__iexact=reference).exists():
            raise ValidationError(
                {"reference": ["A loan repayment with this reference already exists."]}
            )

        if Transaction.objects.filter(reference__iexact=reference).exists():
            raise ValidationError(
                {"reference": ["A transaction with this reference already exists."]}
            )

    @staticmethod
    def _add_months(start_date, months):
        month_index = start_date.month - 1 + months
        year = start_date.year + month_index // 12
        month = month_index % 12 + 1
        day = min(start_date.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @staticmethod
    def _split_evenly(total_amount, periods):
        if periods <= 0:
            raise ValidationError("Periods must be greater than zero.")

        total_amount = Decimal(str(total_amount)).quantize(CENT)
        base_amount = (total_amount / periods).quantize(CENT)
        amounts = [base_amount for _ in range(periods)]
        remainder = total_amount - sum(amounts, ZERO_DECIMAL)

        if remainder > ZERO_DECIMAL:
            amounts[-1] = (amounts[-1] + remainder).quantize(CENT)

        return amounts

    @classmethod
    def validate_application(cls, product, amount, term_months):
        amount = cls._normalize_amount(amount)
        term_months = int(term_months)

        if not product.is_active:
            raise ValidationError("Selected loan product is inactive.")
        if amount < product.min_amount or amount > product.max_amount:
            raise ValidationError("Loan amount is outside product limits.")
        if term_months < product.min_term_months or term_months > product.max_term_months:
            raise ValidationError("Loan term is outside product limits.")

    @classmethod
    def generate_repayment_schedule(cls, *, loan, start_date=None):
        start_date = start_date or timezone.localdate()
        principal_amounts = cls._split_evenly(loan.amount, loan.term_months)
        total_interest = (
            loan.amount
            * loan.product.annual_interest_rate
            / Decimal("100")
            * Decimal(loan.term_months)
            / Decimal("12")
        ).quantize(CENT)
        interest_amounts = cls._split_evenly(total_interest, loan.term_months)

        return [
            RepaymentSchedule(
                loan=loan,
                due_date=cls._add_months(start_date, installment_number),
                principal_due=principal_amounts[installment_number - 1],
                interest_due=interest_amounts[installment_number - 1],
            )
            for installment_number in range(1, loan.term_months + 1)
        ]

    @classmethod
    @transaction.atomic
    def approve(cls, *, loan, user):
        loan = LoanApplication.objects.select_for_update().select_related("product").get(pk=loan.pk)
        if loan.status != LoanApplication.Status.PENDING:
            raise ValidationError("Only pending loans can be approved.")
        cls.validate_application(loan.product, loan.amount, loan.term_months)

        loan.status = LoanApplication.Status.APPROVED
        loan.approved_by = user
        loan.rejected_reason = ""
        loan.save(update_fields=["status", "approved_by", "rejected_reason", "updated_at"])
        AuditService.log(
            user=user,
            action="loan.approve",
            target=str(loan.id),
            metadata={"status": loan.status},
        )
        return loan

    @classmethod
    @transaction.atomic
    def reject(cls, *, loan, user, reason=""):
        loan = LoanApplication.objects.select_for_update().get(pk=loan.pk)
        if loan.status != LoanApplication.Status.PENDING:
            raise ValidationError("Only pending loans can be rejected.")

        loan.status = LoanApplication.Status.REJECTED
        loan.approved_by = None
        loan.rejected_reason = str(reason).strip()
        loan.save(
            update_fields=["status", "approved_by", "rejected_reason", "updated_at"]
        )
        AuditService.log(
            user=user,
            action="loan.reject",
            target=str(loan.id),
            metadata={"reason": loan.rejected_reason},
        )
        return loan

    @classmethod
    @transaction.atomic
    def disburse(cls, *, loan, user, reference):
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related("client__institution", "client__branch", "product")
            .get(pk=loan.pk)
        )
        reference = cls._normalize_reference(reference)
        cls._ensure_reference_available(reference)

        if loan.status != LoanApplication.Status.APPROVED:
            raise ValidationError("Only approved loans can be disbursed.")
        if loan.schedule.exists():
            raise ValidationError("Repayment schedule already exists for this loan.")

        cls.validate_application(loan.product, loan.amount, loan.term_months)
        schedule_rows = cls.generate_repayment_schedule(
            loan=loan,
            start_date=timezone.localdate(),
        )
        total_interest = sum((row.interest_due for row in schedule_rows), ZERO_DECIMAL)

        RepaymentSchedule.objects.bulk_create(schedule_rows)

        loan.status = LoanApplication.Status.DISBURSED
        loan.disbursed_at = timezone.now()
        loan.principal_balance = loan.amount
        loan.interest_balance = total_interest
        loan.save(
            update_fields=[
                "status",
                "disbursed_at",
                "principal_balance",
                "interest_balance",
                "updated_at",
            ]
        )

        try:
            TransactionLedgerService.record(
                institution=loan.client.institution,
                branch=loan.client.branch,
                client=loan.client,
                category=Transaction.Category.LOAN_DISBURSEMENT,
                direction=Transaction.Direction.DEBIT,
                amount=loan.amount,
                reference=reference,
                description=f"Loan disbursement for {loan.client.member_number}",
                created_by=user,
            )
            AccountingPostingService.post_loan_disbursement(
                loan=loan,
                reference=reference,
                posted_by=user,
            )
        except IntegrityError as exc:
            raise cls._duplicate_reference_error() from exc

        AuditService.log(
            user=user,
            action="loan.disburse",
            target=str(loan.id),
            metadata={"reference": reference, "status": loan.status},
        )
        return loan

    @classmethod
    def _apply_repayment_to_schedule(cls, *, loan, amount):
        remaining_amount = amount
        schedule_rows = list(loan.schedule.select_for_update().order_by("due_date", "created_at"))

        for schedule_row in schedule_rows:
            if remaining_amount <= ZERO_DECIMAL:
                break

            outstanding = (
                schedule_row.principal_due + schedule_row.interest_due - schedule_row.paid_amount
            ).quantize(CENT)
            if outstanding <= ZERO_DECIMAL:
                if not schedule_row.is_paid:
                    schedule_row.is_paid = True
                    schedule_row.save(update_fields=["is_paid", "updated_at"])
                continue

            allocation = min(remaining_amount, outstanding).quantize(CENT)
            schedule_row.paid_amount = (schedule_row.paid_amount + allocation).quantize(CENT)
            schedule_row.is_paid = schedule_row.paid_amount >= (
                schedule_row.principal_due + schedule_row.interest_due
            )
            schedule_row.save(update_fields=["paid_amount", "is_paid", "updated_at"])
            remaining_amount = (remaining_amount - allocation).quantize(CENT)

    @classmethod
    @transaction.atomic
    def repay(cls, *, loan, amount, reference, received_by):
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related("client__institution", "client__branch")
            .get(pk=loan.pk)
        )
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        cls._ensure_reference_available(reference)

        if loan.status != LoanApplication.Status.DISBURSED:
            raise ValidationError("Only disbursed loans can receive repayments.")

        outstanding_total = (loan.principal_balance + loan.interest_balance).quantize(CENT)
        if outstanding_total <= ZERO_DECIMAL:
            raise ValidationError("This loan has no outstanding balance.")
        if amount > outstanding_total:
            raise ValidationError("Repayment amount cannot exceed the outstanding balance.")

        interest_component = min(amount, loan.interest_balance).quantize(CENT)
        principal_component = min(
            amount - interest_component,
            loan.principal_balance,
        ).quantize(CENT)
        loan.interest_balance = (loan.interest_balance - interest_component).quantize(CENT)
        loan.principal_balance = (loan.principal_balance - principal_component).quantize(CENT)

        if loan.principal_balance <= ZERO_DECIMAL and loan.interest_balance <= ZERO_DECIMAL:
            loan.status = LoanApplication.Status.CLOSED
            loan.principal_balance = ZERO_DECIMAL
            loan.interest_balance = ZERO_DECIMAL

        loan.save(
            update_fields=[
                "principal_balance",
                "interest_balance",
                "status",
                "updated_at",
            ]
        )

        try:
            repayment = LoanRepayment.objects.create(
                loan=loan,
                amount=amount,
                principal_component=principal_component,
                interest_component=interest_component,
                reference=reference,
                received_by=received_by,
            )
            TransactionLedgerService.record(
                institution=loan.client.institution,
                branch=loan.client.branch,
                client=loan.client,
                category=Transaction.Category.LOAN_REPAYMENT,
                direction=Transaction.Direction.CREDIT,
                amount=amount,
                reference=reference,
                description=f"Loan repayment for {loan.client.member_number}",
                created_by=received_by,
            )
            AccountingPostingService.post_loan_repayment(
                loan=loan,
                amount=amount,
                principal_component=principal_component,
                interest_component=interest_component,
                reference=reference,
                posted_by=received_by,
            )
        except IntegrityError as exc:
            raise cls._duplicate_reference_error() from exc

        cls._apply_repayment_to_schedule(loan=loan, amount=amount)

        AuditService.log(
            user=received_by,
            action="loan.repay",
            target=str(loan.id),
            metadata={"reference": reference, "amount": str(amount), "status": loan.status},
        )
        return repayment
