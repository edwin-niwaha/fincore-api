import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounting.services import AccountingPostingService
from apps.audit.services import AuditService
from apps.notifications.services import NotificationService
from apps.transactions.models import Transaction
from apps.transactions.services import TransactionLedgerService
from apps.users.models import CustomUser

from .models import LoanApplication, LoanApplicationAction, LoanRepayment, RepaymentSchedule

ZERO_DECIMAL = Decimal("0.00")
CENT = Decimal("0.01")


class LoanService:
    CLIENT_ROLE = CustomUser.Role.CLIENT
    LOAN_OFFICER_ROLES = {
        CustomUser.Role.LOAN_OFFICER,
        CustomUser.Role.INSTITUTION_ADMIN,
        CustomUser.Role.SUPER_ADMIN,
    }
    APPROVER_ROLES = {
        CustomUser.Role.BRANCH_MANAGER,
        CustomUser.Role.INSTITUTION_ADMIN,
        CustomUser.Role.SUPER_ADMIN,
    }

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
    def _normalize_comment(value):
        return str(value or "").strip()

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
    def _loan_context_data(cls, loan):
        return {
            "loan_id": str(loan.id),
            "client_id": str(loan.client_id),
            "client_member_number": loan.client.member_number,
            "status": loan.status,
            "amount": f"{loan.amount:.2f}",
        }

    @classmethod
    def _record_action(
        cls,
        *,
        loan,
        action,
        acted_by=None,
        from_status="",
        to_status="",
        comment="",
        reference="",
    ):
        return LoanApplicationAction.objects.create(
            application=loan,
            action=action,
            from_status=from_status,
            to_status=to_status,
            acted_by=acted_by,
            comment=cls._normalize_comment(comment),
            reference=str(reference or "").strip(),
        )

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
    def _schedule_due_date(cls, *, start_date, frequency, installment_number):
        if frequency == "weekly":
            return start_date + timedelta(days=7 * installment_number)
        if frequency == "biweekly":
            return start_date + timedelta(days=14 * installment_number)
        return cls._add_months(start_date, installment_number)

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
                due_date=cls._schedule_due_date(
                    start_date=start_date,
                    frequency=loan.product.repayment_frequency,
                    installment_number=installment_number,
                ),
                principal_due=principal_amounts[installment_number - 1],
                interest_due=interest_amounts[installment_number - 1],
            )
            for installment_number in range(1, loan.term_months + 1)
        ]

    @classmethod
    @transaction.atomic
    def initialize_new_application(cls, *, loan, created_by, submit=False):
        loan = LoanApplication.objects.select_for_update().get(pk=loan.pk)
        loan.created_by = created_by
        loan.status = LoanApplication.Status.DRAFT
        loan.save(update_fields=["created_by", "status", "updated_at"])

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.CREATE,
            acted_by=created_by,
            from_status="",
            to_status=loan.status,
            comment="Loan application created.",
        )

        AuditService.log(
            user=created_by,
            action="loan.application.create",
            target=str(loan.id),
            metadata={
                "client_id": str(loan.client_id),
                "product_id": str(loan.product_id),
                "amount": str(loan.amount),
                "status": loan.status,
            },
        )

        if submit:
            return cls.submit(loan=loan, user=created_by)

        return loan

    @classmethod
    @transaction.atomic
    def submit(cls, *, loan, user, comment=""):
        loan = LoanApplication.objects.select_for_update().select_related("client__branch").get(pk=loan.pk)

        if user.role == CustomUser.Role.CLIENT and loan.client.user_id != user.id:
            raise PermissionDenied("You can only submit your own loan application.")

        if loan.status != LoanApplication.Status.DRAFT:
            raise ValidationError("Only draft loan applications can be submitted.")

        from_status = loan.status
        loan.status = LoanApplication.Status.SUBMITTED
        loan.submitted_by = user
        loan.submitted_at = timezone.now()
        loan.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.SUBMIT,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=comment or "Loan application submitted.",
        )

        NotificationService.notify_client(
            client=loan.client,
            title="Loan application submitted",
            message=(
                f"Your application for {loan.amount:.2f} has been submitted "
                f"and is awaiting review."
            ),
            category="loan_application_submitted",
            data=cls._loan_context_data(loan),
        )
        NotificationService.notify_branch_roles(
            branch=loan.client.branch,
            roles=[CustomUser.Role.LOAN_OFFICER, CustomUser.Role.BRANCH_MANAGER],
            title="New loan application",
            message=(
                f"{loan.client.member_number} submitted a loan application for "
                f"{loan.amount:.2f}."
            ),
            category="loan_application_submitted",
            data=cls._loan_context_data(loan),
            exclude_user_id=user.id if user else None,
        )

        AuditService.log(
            user=user,
            action="loan.submit",
            target=str(loan.id),
            metadata={"status": loan.status},
        )
        return loan

    @classmethod
    @transaction.atomic
    def start_review(cls, *, loan, user, comment=""):
        loan = LoanApplication.objects.select_for_update().get(pk=loan.pk)

        if loan.status != LoanApplication.Status.SUBMITTED:
            raise ValidationError("Only submitted loans can be moved into review.")

        from_status = loan.status
        loan.status = LoanApplication.Status.UNDER_REVIEW
        loan.reviewed_at = timezone.now()
        loan.save(update_fields=["status", "reviewed_at", "updated_at"])

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.START_REVIEW,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=comment or "Loan application review started.",
        )

        AuditService.log(
            user=user,
            action="loan.start_review",
            target=str(loan.id),
            metadata={"status": loan.status},
        )
        return loan

    @classmethod
    @transaction.atomic
    def recommend(cls, *, loan, user, comment=""):
        loan = LoanApplication.objects.select_for_update().select_related("product", "client__branch").get(pk=loan.pk)

        if loan.status not in {
            LoanApplication.Status.SUBMITTED,
            LoanApplication.Status.UNDER_REVIEW,
        }:
            raise ValidationError("Only submitted or under-review loans can be recommended.")

        cls.validate_application(loan.product, loan.amount, loan.term_months)

        from_status = loan.status
        loan.status = LoanApplication.Status.RECOMMENDED
        if not loan.reviewed_at:
            loan.reviewed_at = timezone.now()
        loan.recommended_by = user
        loan.recommended_at = timezone.now()
        loan.rejected_reason = ""
        loan.save(
            update_fields=[
                "status",
                "reviewed_at",
                "recommended_by",
                "recommended_at",
                "rejected_reason",
                "updated_at",
            ]
        )

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.RECOMMEND,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=comment or "Loan application recommended.",
        )

        NotificationService.notify_client(
            client=loan.client,
            title="Loan under recommendation",
            message=(
                f"Your application for {loan.amount:.2f} has been recommended "
                "and is awaiting approval."
            ),
            category="loan_recommended",
            data=cls._loan_context_data(loan),
        )
        NotificationService.notify_branch_roles(
            branch=loan.client.branch,
            roles=[CustomUser.Role.BRANCH_MANAGER],
            title="Loan application recommended",
            message=(
                f"{loan.client.member_number} has a recommended loan application "
                f"for {loan.amount:.2f}."
            ),
            category="loan_recommended",
            data=cls._loan_context_data(loan),
            exclude_user_id=user.id if user else None,
        )

        AuditService.log(
            user=user,
            action="loan.recommend",
            target=str(loan.id),
            metadata={"status": loan.status},
        )
        return loan

    @classmethod
    @transaction.atomic
    def approve(cls, *, loan, user, comment="", override=False):
        loan = LoanApplication.objects.select_for_update().select_related("product").get(pk=loan.pk)

        allowed_statuses = {LoanApplication.Status.RECOMMENDED}
        if override and user.role in {
            CustomUser.Role.INSTITUTION_ADMIN,
            CustomUser.Role.SUPER_ADMIN,
        }:
            allowed_statuses.update(
                {
                    LoanApplication.Status.SUBMITTED,
                    LoanApplication.Status.UNDER_REVIEW,
                }
            )

        if loan.status not in allowed_statuses:
            raise ValidationError(
                "Loans must be recommended before approval unless an admin override is used."
            )

        cls.validate_application(loan.product, loan.amount, loan.term_months)

        from_status = loan.status
        loan.status = LoanApplication.Status.APPROVED
        loan.approved_by = user
        loan.approved_at = timezone.now()
        loan.rejected_reason = ""
        loan.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "rejected_reason",
                "updated_at",
            ]
        )

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.APPROVE,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=comment or "Loan application approved.",
        )

        NotificationService.notify_client(
            client=loan.client,
            title="Loan approved",
            message=(
                f"Your application for {loan.amount:.2f} has been approved "
                "and is ready for disbursement."
            ),
            category="loan_approved",
            data=cls._loan_context_data(loan),
        )

        AuditService.log(
            user=user,
            action="loan.approve",
            target=str(loan.id),
            metadata={"status": loan.status, "override": bool(override)},
        )
        return loan

    @classmethod
    @transaction.atomic
    def reject(cls, *, loan, user, reason="", comment=""):
        loan = LoanApplication.objects.select_for_update().get(pk=loan.pk)

        if loan.status not in {
            LoanApplication.Status.SUBMITTED,
            LoanApplication.Status.UNDER_REVIEW,
            LoanApplication.Status.RECOMMENDED,
        }:
            raise ValidationError("Only submitted, reviewed, or recommended loans can be rejected.")

        from_status = loan.status
        loan.status = LoanApplication.Status.REJECTED
        loan.approved_by = None
        loan.approved_at = None
        loan.recommended_by = None
        loan.recommended_at = None
        loan.rejected_by = user
        loan.rejected_at = timezone.now()
        loan.rejected_reason = cls._normalize_comment(reason or comment)
        loan.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "recommended_by",
                "recommended_at",
                "rejected_by",
                "rejected_at",
                "rejected_reason",
                "updated_at",
            ]
        )

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.REJECT,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=loan.rejected_reason or "Loan application rejected.",
        )

        NotificationService.notify_client(
            client=loan.client,
            title="Loan rejected",
            message=(
                f"Your application for {loan.amount:.2f} was rejected."
                + (f" Reason: {loan.rejected_reason}" if loan.rejected_reason else "")
            ),
            category="loan_rejected",
            data=cls._loan_context_data(loan),
        )

        AuditService.log(
            user=user,
            action="loan.reject",
            target=str(loan.id),
            metadata={"reason": loan.rejected_reason, "status": loan.status},
        )
        return loan

    @classmethod
    @transaction.atomic
    def disburse(cls, *, loan, user, reference, disbursement_method=""):
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related("client__institution", "client__branch", "product")
            .get(pk=loan.pk)
        )
        reference = cls._normalize_reference(reference)
        disbursement_method = cls._normalize_comment(disbursement_method)
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

        from_status = loan.status
        loan.status = LoanApplication.Status.DISBURSED
        loan.disbursed_at = timezone.now()
        loan.disbursed_by = user
        loan.disbursement_method = disbursement_method
        loan.disbursement_reference = reference
        loan.principal_balance = loan.amount
        loan.interest_balance = total_interest
        loan.save(
            update_fields=[
                "status",
                "disbursed_at",
                "disbursed_by",
                "disbursement_method",
                "disbursement_reference",
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

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.DISBURSE,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment="Loan disbursed.",
            reference=reference,
        )

        NotificationService.notify_client(
            client=loan.client,
            title="Loan disbursed",
            message=(
                f"Your approved loan of {loan.amount:.2f} has been disbursed."
                + (
                    f" Reference: {reference}."
                    if reference
                    else ""
                )
            ),
            category="loan_disbursed",
            data=cls._loan_context_data(loan) | {"reference": reference},
        )

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
    def repay(cls, *, loan, amount, reference, received_by, payment_method=""):
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related("client__institution", "client__branch")
            .get(pk=loan.pk)
        )
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(reference)
        payment_method = cls._normalize_comment(payment_method)
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

        from_status = loan.status
        if loan.principal_balance <= ZERO_DECIMAL and loan.interest_balance <= ZERO_DECIMAL:
            loan.status = LoanApplication.Status.CLOSED
            loan.principal_balance = ZERO_DECIMAL
            loan.interest_balance = ZERO_DECIMAL

        remaining_balance_after = (loan.principal_balance + loan.interest_balance).quantize(CENT)

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
                penalty_component=ZERO_DECIMAL,
                remaining_balance_after=remaining_balance_after,
                payment_method=payment_method,
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
        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.REPAY,
            acted_by=received_by,
            from_status=from_status,
            to_status=loan.status,
            comment=f"Loan repayment recorded for {amount:.2f}.",
            reference=reference,
        )

        NotificationService.notify_client(
            client=loan.client,
            title="Loan repayment recorded",
            message=(
                f"A repayment of {amount:.2f} was recorded on your loan."
                f" Remaining balance: {remaining_balance_after:.2f}."
            ),
            category="loan_repayment_recorded",
            data=cls._loan_context_data(loan)
            | {
                "reference": reference,
                "remaining_balance_after": f"{remaining_balance_after:.2f}",
            },
        )

        AuditService.log(
            user=received_by,
            action="loan.repay",
            target=str(loan.id),
            metadata={
                "reference": reference,
                "amount": str(amount),
                "status": loan.status,
                "remaining_balance_after": str(remaining_balance_after),
            },
        )
        return repayment
