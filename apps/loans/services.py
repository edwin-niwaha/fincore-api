import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounting.services import AccountingPostingService
from apps.audit.services import AuditService
from apps.clients.models import ClientStatusChoices
from apps.common.models import StatusChoices
from apps.notifications.services import NotificationService
from apps.savings.models import SavingsAccount
from apps.shares.models import ShareAccount
from apps.transactions.models import Transaction
from apps.transactions.services import TransactionLedgerService
from apps.users.models import CustomUser

from .models import (
    LoanApplication,
    LoanApplicationAction,
    LoanAppraisal,
    LoanRepayment,
    RepaymentSchedule,
)

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
    def _normalize_text(value):
        return str(value or "").strip()

    @staticmethod
    def _normalize_optional_decimal(value):
        if value in (None, ""):
            return None
        normalized = Decimal(str(value)).quantize(CENT)
        if normalized < ZERO_DECIMAL:
            raise ValidationError("Amounts cannot be negative.")
        return normalized

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

    @staticmethod
    def _decimal_string(value):
        return f"{Decimal(str(value or ZERO_DECIMAL)).quantize(CENT):.2f}"

    @classmethod
    def _periods_for_term(cls, *, term_months, frequency):
        normalized_term_months = int(term_months)
        if normalized_term_months <= 0:
            raise ValidationError("Loan term must be greater than zero.")

        if frequency == "weekly":
            return normalized_term_months * 4
        if frequency == "biweekly":
            return normalized_term_months * 2
        return normalized_term_months

    @staticmethod
    def _periods_per_year(frequency):
        if frequency == "weekly":
            return Decimal("52")
        if frequency == "biweekly":
            return Decimal("26")
        return Decimal("12")

    @classmethod
    def _periodic_interest_rate(cls, *, annual_interest_rate, frequency):
        annual_rate = Decimal(str(annual_interest_rate or ZERO_DECIMAL))
        return (
            annual_rate
            / Decimal("100")
            / cls._periods_per_year(frequency)
        )

    @classmethod
    def _first_due_date(cls, *, start_date, frequency, grace_period_days):
        if grace_period_days > 0:
            return start_date + timedelta(days=grace_period_days)
        return cls._schedule_due_date(
            start_date=start_date,
            frequency=frequency,
            installment_number=1,
        )

    @classmethod
    def _schedule_due_date_from_first_due_date(
        cls,
        *,
        first_due_date,
        frequency,
        installment_number,
    ):
        if installment_number <= 1:
            return first_due_date
        if frequency == "weekly":
            return first_due_date + timedelta(days=7 * (installment_number - 1))
        if frequency == "biweekly":
            return first_due_date + timedelta(days=14 * (installment_number - 1))
        return cls._add_months(first_due_date, installment_number - 1)

    @classmethod
    def _flat_schedule_amounts(cls, *, amount, annual_interest_rate, term_months, periods):
        principal_amounts = cls._split_evenly(amount, periods)
        total_interest = (
            amount
            * Decimal(str(annual_interest_rate or ZERO_DECIMAL))
            / Decimal("100")
            * Decimal(str(term_months))
            / Decimal("12")
        ).quantize(CENT)
        interest_amounts = cls._split_evenly(total_interest, periods)
        return principal_amounts, interest_amounts

    @classmethod
    def _declining_balance_amounts(cls, *, amount, annual_interest_rate, frequency, periods):
        principal_amounts = cls._split_evenly(amount, periods)
        interest_amounts = []
        remaining_principal = Decimal(str(amount)).quantize(CENT)
        periodic_rate = cls._periodic_interest_rate(
            annual_interest_rate=annual_interest_rate,
            frequency=frequency,
        )

        for principal_due in principal_amounts:
            interest_due = (remaining_principal * periodic_rate).quantize(CENT)
            interest_amounts.append(interest_due)
            remaining_principal = (remaining_principal - principal_due).quantize(CENT)

        return principal_amounts, interest_amounts

    @classmethod
    def _reducing_balance_amounts(cls, *, amount, annual_interest_rate, frequency, periods):
        amount = Decimal(str(amount)).quantize(CENT)
        periodic_rate = cls._periodic_interest_rate(
            annual_interest_rate=annual_interest_rate,
            frequency=frequency,
        )

        if periodic_rate <= ZERO_DECIMAL:
            return cls._declining_balance_amounts(
                amount=amount,
                annual_interest_rate=ZERO_DECIMAL,
                frequency=frequency,
                periods=periods,
            )

        annuity_factor = Decimal("1") - (Decimal("1") + periodic_rate) ** (-periods)
        installment_amount = (amount * periodic_rate / annuity_factor).quantize(CENT)
        principal_amounts = []
        interest_amounts = []
        remaining_principal = amount

        for installment_number in range(1, periods + 1):
            interest_due = (remaining_principal * periodic_rate).quantize(CENT)
            if installment_number == periods:
                principal_due = remaining_principal
            else:
                principal_due = (installment_amount - interest_due).quantize(CENT)
                if principal_due <= ZERO_DECIMAL:
                    principal_due = ZERO_DECIMAL
                if principal_due > remaining_principal:
                    principal_due = remaining_principal

            principal_amounts.append(principal_due)
            interest_amounts.append(interest_due)
            remaining_principal = (remaining_principal - principal_due).quantize(CENT)

        return principal_amounts, interest_amounts

    @classmethod
    def _interest_only_amounts(cls, *, amount, annual_interest_rate, frequency, periods):
        amount = Decimal(str(amount)).quantize(CENT)
        periodic_rate = cls._periodic_interest_rate(
            annual_interest_rate=annual_interest_rate,
            frequency=frequency,
        )
        periodic_interest = (amount * periodic_rate).quantize(CENT)

        principal_amounts = [ZERO_DECIMAL for _ in range(periods)]
        if periods:
            principal_amounts[-1] = amount

        interest_amounts = [periodic_interest for _ in range(periods)]
        return principal_amounts, interest_amounts

    @classmethod
    def _schedule_amounts_for_product(cls, *, product, amount, term_months):
        periods = cls._periods_for_term(
            term_months=term_months,
            frequency=product.repayment_frequency,
        )

        if product.interest_method == product.InterestMethod.REDUCING_BALANCE:
            return cls._reducing_balance_amounts(
                amount=amount,
                annual_interest_rate=product.annual_interest_rate,
                frequency=product.repayment_frequency,
                periods=periods,
            )

        if product.interest_method == product.InterestMethod.DECLINING_BALANCE:
            return cls._declining_balance_amounts(
                amount=amount,
                annual_interest_rate=product.annual_interest_rate,
                frequency=product.repayment_frequency,
                periods=periods,
            )

        if product.interest_method == product.InterestMethod.INTEREST_ONLY:
            return cls._interest_only_amounts(
                amount=amount,
                annual_interest_rate=product.annual_interest_rate,
                frequency=product.repayment_frequency,
                periods=periods,
            )

        return cls._flat_schedule_amounts(
            amount=amount,
            annual_interest_rate=product.annual_interest_rate,
            term_months=term_months,
            periods=periods,
        )

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
    def generate_repayment_schedule_preview(
        cls,
        *,
        product,
        amount,
        term_months,
        start_date=None,
    ):
        amount = cls._normalize_amount(amount)
        term_months = int(term_months)
        start_date = start_date or timezone.localdate()
        principal_amounts, interest_amounts = cls._schedule_amounts_for_product(
            product=product,
            amount=amount,
            term_months=term_months,
        )
        first_due_date = cls._first_due_date(
            start_date=start_date,
            frequency=product.repayment_frequency,
            grace_period_days=int(product.grace_period_days or 0),
        )

        rows = []
        for installment_number, (principal_due, interest_due) in enumerate(
            zip(principal_amounts, interest_amounts),
            start=1,
        ):
            rows.append(
                {
                    "due_date": cls._schedule_due_date_from_first_due_date(
                        first_due_date=first_due_date,
                        frequency=product.repayment_frequency,
                        installment_number=installment_number,
                    ),
                    "principal_due": Decimal(str(principal_due)).quantize(CENT),
                    "interest_due": Decimal(str(interest_due)).quantize(CENT),
                }
            )

        return rows

    @classmethod
    def estimate_installment_amount(cls, *, product, amount, term_months):
        preview = cls.generate_repayment_schedule_preview(
            product=product,
            amount=amount,
            term_months=term_months,
        )
        if not preview:
            return ZERO_DECIMAL
        return max(
            (row["principal_due"] + row["interest_due"] for row in preview),
            default=ZERO_DECIMAL,
        ).quantize(CENT)

    @classmethod
    def _schedule_due_date(cls, *, start_date, frequency, installment_number):
        if frequency == "weekly":
            return start_date + timedelta(days=7 * installment_number)
        if frequency == "biweekly":
            return start_date + timedelta(days=14 * installment_number)
        return cls._add_months(start_date, installment_number)

    @classmethod
    def generate_repayment_schedule(cls, *, loan, start_date=None):
        preview_rows = cls.generate_repayment_schedule_preview(
            product=loan.product,
            amount=loan.amount,
            term_months=loan.term_months,
            start_date=start_date or timezone.localdate(),
        )
        return [
            RepaymentSchedule(
                loan=loan,
                due_date=row["due_date"],
                principal_due=row["principal_due"],
                interest_due=row["interest_due"],
            )
            for row in preview_rows
        ]

    @classmethod
    def evaluate_eligibility(
        cls,
        *,
        client,
        product,
        amount,
        term_months,
        exclude_loan_id=None,
        monthly_income=None,
        monthly_expenses=None,
        existing_debt_payments=None,
    ):
        cls.validate_application(product, amount, term_months)
        amount = cls._normalize_amount(amount)
        monthly_income = cls._normalize_optional_decimal(monthly_income)
        monthly_expenses = cls._normalize_optional_decimal(monthly_expenses) or ZERO_DECIMAL
        existing_debt_payments = (
            cls._normalize_optional_decimal(existing_debt_payments) or ZERO_DECIMAL
        )

        savings_balance = (
            SavingsAccount.objects.filter(client=client, status=StatusChoices.ACTIVE)
            .aggregate(total=Sum("balance"))["total"]
            or ZERO_DECIMAL
        )
        share_capital = (
            ShareAccount.objects.filter(client=client, status=StatusChoices.ACTIVE)
            .aggregate(total=Sum("total_value"))["total"]
            or ZERO_DECIMAL
        )
        active_loans = LoanApplication.objects.filter(
            client=client,
            status__in=[LoanApplication.Status.APPROVED, LoanApplication.Status.DISBURSED],
        )
        if exclude_loan_id:
            active_loans = active_loans.exclude(pk=exclude_loan_id)
        active_loans = active_loans.filter(
            Q(principal_balance__gt=ZERO_DECIMAL) | Q(interest_balance__gt=ZERO_DECIMAL)
        )
        outstanding_loans_count = active_loans.count()
        overdue_loans_count = (
            active_loans.filter(
                schedule__due_date__lt=timezone.localdate(),
                schedule__is_paid=False,
            )
            .distinct()
            .count()
        )
        estimated_installment = cls.estimate_installment_amount(
            product=product,
            amount=amount,
            term_months=term_months,
        )

        checks = []

        def add_check(*, code, label, passed, message, value=None, threshold=None):
            checks.append(
                {
                    "code": code,
                    "label": label,
                    "passed": bool(passed),
                    "message": message,
                    "value": value,
                    "threshold": threshold,
                }
            )

        add_check(
            code="membership_status",
            label="Active membership status",
            passed=client.status == ClientStatusChoices.ACTIVE,
            message=(
                "Client membership is active."
                if client.status == ClientStatusChoices.ACTIVE
                else "Client must be active before submitting a loan application."
            ),
            value=client.status,
        )
        add_check(
            code="minimum_savings_balance",
            label="Minimum savings balance",
            passed=savings_balance >= product.minimum_savings_balance,
            message=(
                "Savings balance meets the product minimum."
                if savings_balance >= product.minimum_savings_balance
                else "Client savings balance is below the product minimum."
            ),
            value=cls._decimal_string(savings_balance),
            threshold=cls._decimal_string(product.minimum_savings_balance),
        )
        add_check(
            code="minimum_share_capital",
            label="Minimum share capital",
            passed=share_capital >= product.minimum_share_capital,
            message=(
                "Share capital meets the product minimum."
                if share_capital >= product.minimum_share_capital
                else "Client share capital is below the product minimum."
            ),
            value=cls._decimal_string(share_capital),
            threshold=cls._decimal_string(product.minimum_share_capital),
        )

        if product.max_outstanding_loans is not None:
            add_check(
                code="outstanding_loans_limit",
                label="Outstanding loans limit",
                passed=outstanding_loans_count < product.max_outstanding_loans,
                message=(
                    "Outstanding loan count is within the product limit."
                    if outstanding_loans_count < product.max_outstanding_loans
                    else "Client has reached the maximum allowed outstanding loans for this product."
                ),
                value=outstanding_loans_count,
                threshold=product.max_outstanding_loans,
            )

        add_check(
            code="arrears_history",
            label="Existing arrears/default history",
            passed=overdue_loans_count == 0,
            message=(
                "Client has no overdue loans in the current portfolio."
                if overdue_loans_count == 0
                else "Client has overdue loans and cannot proceed until arrears are resolved."
            ),
            value=overdue_loans_count,
            threshold=0,
        )

        if product.max_amount_to_savings_ratio is not None:
            max_amount_from_savings = (
                savings_balance * product.max_amount_to_savings_ratio
            ).quantize(CENT)
            add_check(
                code="savings_ratio_limit",
                label="Savings-based loan limit",
                passed=savings_balance > ZERO_DECIMAL and amount <= max_amount_from_savings,
                message=(
                    "Requested amount is within the savings-based limit."
                    if savings_balance > ZERO_DECIMAL and amount <= max_amount_from_savings
                    else "Requested amount exceeds the savings-based lending limit."
                ),
                value=cls._decimal_string(amount),
                threshold=cls._decimal_string(max_amount_from_savings),
            )

        if product.max_amount_to_share_ratio is not None:
            max_amount_from_shares = (
                share_capital * product.max_amount_to_share_ratio
            ).quantize(CENT)
            add_check(
                code="share_ratio_limit",
                label="Share-based loan limit",
                passed=share_capital > ZERO_DECIMAL and amount <= max_amount_from_shares,
                message=(
                    "Requested amount is within the share-based limit."
                    if share_capital > ZERO_DECIMAL and amount <= max_amount_from_shares
                    else "Requested amount exceeds the share-based lending limit."
                ),
                value=cls._decimal_string(amount),
                threshold=cls._decimal_string(max_amount_from_shares),
            )

        if product.debt_to_income_limit is not None:
            if monthly_income is None or monthly_income <= ZERO_DECIMAL:
                add_check(
                    code="debt_to_income_ratio",
                    label="Debt-to-income ratio",
                    passed=True,
                    message="Income data was not provided. Debt-to-income will be assessed during appraisal.",
                    threshold=cls._decimal_string(product.debt_to_income_limit),
                )
            else:
                total_debt_obligation = (
                    existing_debt_payments + estimated_installment
                ).quantize(CENT)
                debt_to_income_ratio = (
                    total_debt_obligation / monthly_income * Decimal("100")
                ).quantize(CENT)
                disposable_income = (
                    monthly_income - monthly_expenses - existing_debt_payments
                ).quantize(CENT)
                add_check(
                    code="debt_to_income_ratio",
                    label="Debt-to-income ratio",
                    passed=debt_to_income_ratio <= product.debt_to_income_limit
                    and disposable_income >= estimated_installment,
                    message=(
                        "Debt-to-income ratio is within the product limit."
                        if debt_to_income_ratio <= product.debt_to_income_limit
                        and disposable_income >= estimated_installment
                        else "Debt-to-income ratio or disposable income does not support this request."
                    ),
                    value=cls._decimal_string(debt_to_income_ratio),
                    threshold=cls._decimal_string(product.debt_to_income_limit),
                )

        eligible = all(check["passed"] for check in checks)
        failures = [check["message"] for check in checks if not check["passed"]]
        return {
            "eligible": eligible,
            "checks": checks,
            "summary": {
                "requested_amount": cls._decimal_string(amount),
                "estimated_installment": cls._decimal_string(estimated_installment),
                "savings_balance": cls._decimal_string(savings_balance),
                "share_capital": cls._decimal_string(share_capital),
                "outstanding_loans_count": outstanding_loans_count,
                "overdue_loans_count": overdue_loans_count,
                "monthly_income": cls._decimal_string(monthly_income)
                if monthly_income is not None
                else None,
                "monthly_expenses": cls._decimal_string(monthly_expenses),
                "existing_debt_payments": cls._decimal_string(existing_debt_payments),
            },
            "errors": failures,
        }

    @classmethod
    def _save_eligibility_snapshot(cls, *, loan, snapshot):
        loan.eligibility_snapshot = snapshot
        loan.save(update_fields=["eligibility_snapshot", "updated_at"])

    @classmethod
    def _ensure_submission_eligibility(cls, *, loan):
        snapshot = cls.evaluate_eligibility(
            client=loan.client,
            product=loan.product,
            amount=loan.amount,
            term_months=loan.term_months,
            exclude_loan_id=loan.id,
        )
        cls._save_eligibility_snapshot(loan=loan, snapshot=snapshot)
        if not snapshot["eligible"]:
            raise ValidationError({"eligibility": snapshot["errors"]})
        return snapshot

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

        cls._ensure_submission_eligibility(loan=loan)

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
    def appraise(
        cls,
        *,
        loan,
        user,
        recommendation,
        monthly_income=ZERO_DECIMAL,
        monthly_expenses=ZERO_DECIMAL,
        existing_debt_payments=ZERO_DECIMAL,
        risk_score=None,
        recommended_amount=None,
        recommended_term_months=None,
        collateral_notes="",
        guarantor_notes="",
        credit_comments="",
        notes="",
    ):
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related("product", "client")
            .get(pk=loan.pk)
        )

        if loan.status not in {
            LoanApplication.Status.SUBMITTED,
            LoanApplication.Status.UNDER_REVIEW,
            LoanApplication.Status.APPRAISED,
        }:
            raise ValidationError(
                "Only submitted, under-review, or appraised loans can be appraised."
            )

        normalized_recommended_amount = cls._normalize_optional_decimal(recommended_amount)
        normalized_recommended_term = (
            int(recommended_term_months) if recommended_term_months not in (None, "") else None
        )
        appraisal_amount = normalized_recommended_amount or loan.amount
        appraisal_term = normalized_recommended_term or loan.term_months

        eligibility_snapshot = cls.evaluate_eligibility(
            client=loan.client,
            product=loan.product,
            amount=appraisal_amount,
            term_months=appraisal_term,
            exclude_loan_id=loan.id,
            monthly_income=monthly_income,
            monthly_expenses=monthly_expenses,
            existing_debt_payments=existing_debt_payments,
        )
        estimated_installment = Decimal(
            eligibility_snapshot["summary"]["estimated_installment"]
        ).quantize(CENT)
        affordability_amount = (
            (
                cls._normalize_optional_decimal(monthly_income) or ZERO_DECIMAL
            )
            - (cls._normalize_optional_decimal(monthly_expenses) or ZERO_DECIMAL)
            - (cls._normalize_optional_decimal(existing_debt_payments) or ZERO_DECIMAL)
        ).quantize(CENT)

        appraisal = LoanAppraisal.objects.create(
            application=loan,
            performed_by=user,
            recommendation=recommendation,
            recommended_amount=normalized_recommended_amount,
            recommended_term_months=normalized_recommended_term,
            monthly_income=cls._normalize_optional_decimal(monthly_income) or ZERO_DECIMAL,
            monthly_expenses=cls._normalize_optional_decimal(monthly_expenses)
            or ZERO_DECIMAL,
            existing_debt_payments=cls._normalize_optional_decimal(existing_debt_payments)
            or ZERO_DECIMAL,
            affordability_amount=max(affordability_amount, ZERO_DECIMAL),
            estimated_installment=estimated_installment,
            risk_score=risk_score,
            savings_balance_snapshot=Decimal(
                eligibility_snapshot["summary"]["savings_balance"]
            ).quantize(CENT),
            share_capital_snapshot=Decimal(
                eligibility_snapshot["summary"]["share_capital"]
            ).quantize(CENT),
            outstanding_loans_snapshot=eligibility_snapshot["summary"][
                "outstanding_loans_count"
            ],
            overdue_loans_snapshot=eligibility_snapshot["summary"][
                "overdue_loans_count"
            ],
            eligibility_passed=eligibility_snapshot["eligible"],
            collateral_notes=cls._normalize_text(collateral_notes),
            guarantor_notes=cls._normalize_text(guarantor_notes),
            credit_comments=cls._normalize_text(credit_comments),
            notes=cls._normalize_text(notes),
        )

        from_status = loan.status
        loan.status = LoanApplication.Status.APPRAISED
        loan.appraised_by = user
        loan.appraised_at = timezone.now()
        loan.reviewed_at = loan.reviewed_at or loan.appraised_at
        loan.rejected_reason = ""
        loan.eligibility_snapshot = eligibility_snapshot
        loan.save(
            update_fields=[
                "status",
                "appraised_by",
                "appraised_at",
                "reviewed_at",
                "rejected_reason",
                "eligibility_snapshot",
                "updated_at",
            ]
        )

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.APPRAISE,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=(
                cls._normalize_text(notes)
                or f"Loan appraisal completed with recommendation {recommendation}."
            ),
        )

        NotificationService.notify_branch_roles(
            branch=loan.client.branch,
            roles=[CustomUser.Role.BRANCH_MANAGER],
            title="Loan appraisal completed",
            message=(
                f"{loan.client.member_number} has an appraised loan application "
                f"for {loan.amount:.2f}."
            ),
            category="loan_appraised",
            data=cls._loan_context_data(loan)
            | {
                "recommendation": recommendation,
                "eligibility_passed": eligibility_snapshot["eligible"],
            },
            exclude_user_id=user.id if user else None,
        )

        AuditService.log(
            user=user,
            action="loan.appraise",
            target=str(loan.id),
            metadata={
                "status": loan.status,
                "recommendation": appraisal.recommendation,
                "eligibility_passed": appraisal.eligibility_passed,
            },
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
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related("product")
            .prefetch_related("appraisals")
            .get(pk=loan.pk)
        )

        allowed_statuses = {
            LoanApplication.Status.RECOMMENDED,
            LoanApplication.Status.APPRAISED,
        }
        if override and user.role in {
            CustomUser.Role.INSTITUTION_ADMIN,
            CustomUser.Role.SUPER_ADMIN,
        }:
            allowed_statuses.update(
                {
                    LoanApplication.Status.SUBMITTED,
                    LoanApplication.Status.UNDER_REVIEW,
                    LoanApplication.Status.RECOMMENDED,
                    LoanApplication.Status.APPRAISED,
                }
            )

        if loan.status not in allowed_statuses:
            raise ValidationError(
                "Loans must be recommended before approval unless an admin override is used."
            )

        cls.validate_application(loan.product, loan.amount, loan.term_months)

        latest_appraisal = loan.appraisals.order_by("-created_at", "-id").first()
        if loan.status == LoanApplication.Status.APPRAISED and latest_appraisal:
            if (
                latest_appraisal.recommendation == LoanAppraisal.Recommendation.REJECT
                and not override
            ):
                raise ValidationError(
                    "The latest appraisal recommends rejection. Use an override to approve this loan."
                )
            if not latest_appraisal.eligibility_passed and not override:
                raise ValidationError(
                    "The latest appraisal did not pass the configured eligibility checks."
                )

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
            LoanApplication.Status.APPRAISED,
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
    def withdraw(cls, *, loan, user, reason=""):
        loan = LoanApplication.objects.select_for_update().get(pk=loan.pk)

        if user.role == CustomUser.Role.CLIENT and loan.client.user_id != user.id:
            raise PermissionDenied("You can only withdraw your own loan application.")

        if loan.status not in {
            LoanApplication.Status.DRAFT,
            LoanApplication.Status.SUBMITTED,
            LoanApplication.Status.UNDER_REVIEW,
            LoanApplication.Status.APPRAISED,
            LoanApplication.Status.RECOMMENDED,
        }:
            raise ValidationError(
                "Only draft, submitted, under-review, appraised, or recommended loans can be withdrawn."
            )

        from_status = loan.status
        loan.status = LoanApplication.Status.WITHDRAWN
        loan.withdrawn_by = user
        loan.withdrawn_at = timezone.now()
        loan.withdrawal_reason = cls._normalize_comment(reason)
        loan.save(
            update_fields=[
                "status",
                "withdrawn_by",
                "withdrawn_at",
                "withdrawal_reason",
                "updated_at",
            ]
        )

        cls._record_action(
            loan=loan,
            action=LoanApplicationAction.Action.WITHDRAW,
            acted_by=user,
            from_status=from_status,
            to_status=loan.status,
            comment=loan.withdrawal_reason or "Loan application withdrawn.",
        )

        AuditService.log(
            user=user,
            action="loan.withdraw",
            target=str(loan.id),
            metadata={"status": loan.status, "reason": loan.withdrawal_reason},
        )
        return loan

    @classmethod
    @transaction.atomic
    def disburse(cls, *, loan, user, reference, disbursement_method=""):
        loan = (
            LoanApplication.objects.select_for_update()
            .select_related(
                "client__institution",
                "client__branch",
                "product",
                "product__receivable_account",
                "product__funding_account",
                "product__interest_income_account",
            )
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
            .select_related(
                "client__institution",
                "client__branch",
                "product",
                "product__receivable_account",
                "product__funding_account",
                "product__interest_income_account",
            )
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
