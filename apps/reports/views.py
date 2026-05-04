from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from apps.accounting.selectors import (
    balance_sheet_data_for_user,
    general_ledger_data_for_user,
    trial_balance_data_for_user,
)
from apps.common.permissions import IsAccountingRole, IsStaffRole
from apps.loans.models import LoanApplication, LoanRepayment
from apps.loans.selectors import loans_for_user
from apps.loans.serializers import LoanApplicationSerializer
from apps.savings.selectors import savings_accounts_for_user


class FinancialReportViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffRole]

    def get_permissions(self):
        if getattr(self, "action", None) in {
            "trial_balance",
            "general_ledger",
            "balance_sheet",
        }:
            return [IsAccountingRole()]
        return [permission() for permission in self.permission_classes]

    def _parse_date(self, value, *, field_name):
        if not value:
            return None

        parsed = parse_date(value)
        if parsed is None:
            raise ValidationError({field_name: [f"Use YYYY-MM-DD for {field_name}."]})
        return parsed

    def _parse_bool(self, value):
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    def _decimal_string(self, value):
        return f"{Decimal(str(value or '0.00')):.2f}"

    def _date_string(self, value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _scoped_loans_queryset(self, request):
        queryset = loans_for_user(request.user)

        institution_id = request.query_params.get("institution")
        if institution_id:
            queryset = queryset.filter(client__institution_id=institution_id)

        branch_id = request.query_params.get("branch")
        if branch_id:
            queryset = queryset.filter(client__branch_id=branch_id)

        product_id = request.query_params.get("product")
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        status_value = request.query_params.get("status")
        if status_value:
            queryset = queryset.filter(status=status_value)

        return queryset

    def _loan_arrears_snapshot(self, loan, *, as_of):
        overdue_rows = []
        for schedule_row in loan.schedule.all():
            if schedule_row.is_paid or not schedule_row.due_date or schedule_row.due_date >= as_of:
                continue

            outstanding_amount = schedule_row.outstanding_amount
            if outstanding_amount <= Decimal("0.00"):
                continue

            days_past_due = (as_of - schedule_row.due_date).days
            overdue_rows.append(
                {
                    "due_date": schedule_row.due_date,
                    "days_past_due": days_past_due,
                    "outstanding_amount": outstanding_amount,
                }
            )

        if not overdue_rows:
            return {
                "oldest_due_date": None,
                "days_past_due": 0,
                "overdue_installments": 0,
                "overdue_amount": Decimal("0.00"),
                "bucket_1_30": Decimal("0.00"),
                "bucket_31_60": Decimal("0.00"),
                "bucket_61_90": Decimal("0.00"),
                "bucket_91_plus": Decimal("0.00"),
            }

        bucket_1_30 = Decimal("0.00")
        bucket_31_60 = Decimal("0.00")
        bucket_61_90 = Decimal("0.00")
        bucket_91_plus = Decimal("0.00")

        for row in overdue_rows:
            amount = row["outstanding_amount"]
            days_past_due = row["days_past_due"]
            if days_past_due <= 30:
                bucket_1_30 += amount
            elif days_past_due <= 60:
                bucket_31_60 += amount
            elif days_past_due <= 90:
                bucket_61_90 += amount
            else:
                bucket_91_plus += amount

        return {
            "oldest_due_date": min(row["due_date"] for row in overdue_rows),
            "days_past_due": max(row["days_past_due"] for row in overdue_rows),
            "overdue_installments": len(overdue_rows),
            "overdue_amount": sum(
                (row["outstanding_amount"] for row in overdue_rows),
                Decimal("0.00"),
            ),
            "bucket_1_30": bucket_1_30,
            "bucket_31_60": bucket_31_60,
            "bucket_61_90": bucket_61_90,
            "bucket_91_plus": bucket_91_plus,
        }

    @action(detail=False, methods=["get"], url_path="savings-balances")
    def savings_balances(self, request):
        qs = savings_accounts_for_user(request.user)
        return response.Response(
            {
                "total_balance": qs.aggregate(total=Sum("balance"))["total"] or 0,
                "accounts": qs.count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="loan-portfolio")
    def loan_portfolio(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = self._parse_date(as_of_raw, field_name="as_of") if as_of_raw else timezone.localdate()
        include_rows = self._parse_bool(request.query_params.get("include_rows"))
        qs = self._scoped_loans_queryset(request).prefetch_related("schedule")

        principal_outstanding = Decimal("0.00")
        interest_outstanding = Decimal("0.00")
        status_totals = {}
        product_totals = {}
        overdue_loans = 0
        arrears_balance = Decimal("0.00")

        for loan in qs:
            principal_outstanding += loan.principal_balance
            interest_outstanding += loan.interest_balance

            status_entry = status_totals.setdefault(
                loan.status,
                {
                    "status": loan.status,
                    "count": 0,
                    "requested_amount": Decimal("0.00"),
                    "outstanding_balance": Decimal("0.00"),
                },
            )
            status_entry["count"] += 1
            status_entry["requested_amount"] += loan.amount
            status_entry["outstanding_balance"] += loan.outstanding_balance

            product_key = str(loan.product_id)
            product_entry = product_totals.setdefault(
                product_key,
                {
                    "product_id": str(loan.product_id),
                    "product_name": loan.product.name,
                    "product_code": loan.product.code,
                    "loan_count": 0,
                    "requested_amount": Decimal("0.00"),
                    "outstanding_balance": Decimal("0.00"),
                },
            )
            product_entry["loan_count"] += 1
            product_entry["requested_amount"] += loan.amount
            product_entry["outstanding_balance"] += loan.outstanding_balance

            arrears = self._loan_arrears_snapshot(loan, as_of=as_of)
            if arrears["overdue_amount"] > Decimal("0.00"):
                overdue_loans += 1
                arrears_balance += arrears["overdue_amount"]

        rows = []
        if include_rows:
            serialized_rows = LoanApplicationSerializer(qs, many=True).data
            arrears_by_id = {
                str(loan.id): self._loan_arrears_snapshot(loan, as_of=as_of) for loan in qs
            }

            for row in serialized_rows:
                arrears = arrears_by_id.get(str(row["id"]), {})
                row["oldest_due_date"] = self._date_string(arrears.get("oldest_due_date"))
                row["days_past_due"] = arrears.get("days_past_due", 0)
                row["overdue_installments"] = arrears.get("overdue_installments", 0)
                row["overdue_amount"] = self._decimal_string(arrears.get("overdue_amount"))
                rows.append(row)

        return response.Response(
            {
                "generated_at": timezone.now(),
                "as_of": as_of,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "product": request.query_params.get("product"),
                "status": request.query_params.get("status"),
                "principal_outstanding": self._decimal_string(principal_outstanding),
                "interest_outstanding": self._decimal_string(interest_outstanding),
                "portfolio_balance": self._decimal_string(
                    principal_outstanding + interest_outstanding
                ),
                "arrears_balance": self._decimal_string(arrears_balance),
                "loans": qs.count(),
                "pending": qs.filter(
                    status__in=[
                        LoanApplication.Status.DRAFT,
                        LoanApplication.Status.SUBMITTED,
                        LoanApplication.Status.UNDER_REVIEW,
                    ]
                ).count(),
                "appraised": qs.filter(status=LoanApplication.Status.APPRAISED).count(),
                "recommended": qs.filter(status=LoanApplication.Status.RECOMMENDED).count(),
                "approved": qs.filter(status=LoanApplication.Status.APPROVED).count(),
                "active": qs.filter(status=LoanApplication.Status.DISBURSED).count(),
                "overdue_loans": overdue_loans,
                "closed": qs.filter(status=LoanApplication.Status.CLOSED).count(),
                "rejected": qs.filter(status=LoanApplication.Status.REJECTED).count(),
                "withdrawn": qs.filter(status=LoanApplication.Status.WITHDRAWN).count(),
                "written_off": qs.filter(status=LoanApplication.Status.WRITTEN_OFF).count(),
                "status_breakdown": [
                    {
                        **row,
                        "requested_amount": self._decimal_string(row["requested_amount"]),
                        "outstanding_balance": self._decimal_string(row["outstanding_balance"]),
                    }
                    for row in status_totals.values()
                ],
                "product_breakdown": [
                    {
                        **row,
                        "requested_amount": self._decimal_string(row["requested_amount"]),
                        "outstanding_balance": self._decimal_string(row["outstanding_balance"]),
                    }
                    for row in product_totals.values()
                ],
                "rows": rows,
            }
        )

    @action(detail=False, methods=["get"], url_path="loan-disbursements")
    def loan_disbursements(self, request):
        date_from = self._parse_date(
            request.query_params.get("date_from"),
            field_name="date_from",
        )
        date_to = self._parse_date(
            request.query_params.get("date_to"),
            field_name="date_to",
        )
        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                {"date_to": ["End date must be on or after the start date."]}
            )

        qs = self._scoped_loans_queryset(request).filter(
            disbursed_at__isnull=False,
            status__in=[
                LoanApplication.Status.DISBURSED,
                LoanApplication.Status.CLOSED,
                LoanApplication.Status.WRITTEN_OFF,
            ],
        )
        if date_from:
            qs = qs.filter(disbursed_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(disbursed_at__date__lte=date_to)

        rows = [
            {
                "loan_id": str(loan.id),
                "client_name": loan.client_name,
                "client_member_number": loan.client_member_number,
                "branch_name": loan.branch_name,
                "product_name": loan.product_name,
                "product_code": loan.product_code,
                "status": loan.status,
                "approved_at": self._date_string(loan.approved_at),
                "disbursed_at": self._date_string(loan.disbursed_at),
                "amount": self._decimal_string(loan.amount),
                "principal_balance": self._decimal_string(loan.principal_balance),
                "interest_balance": self._decimal_string(loan.interest_balance),
                "outstanding_balance": self._decimal_string(loan.outstanding_balance),
                "disbursement_reference": loan.disbursement_reference,
                "disbursement_method": loan.disbursement_method,
            }
            for loan in qs.order_by("-disbursed_at", "-created_at")
        ]

        total_disbursed = sum(
            (Decimal(str(loan.amount)) for loan in qs),
            Decimal("0.00"),
        )
        principal_outstanding = sum(
            (loan.principal_balance for loan in qs),
            Decimal("0.00"),
        )
        interest_outstanding = sum(
            (loan.interest_balance for loan in qs),
            Decimal("0.00"),
        )

        return response.Response(
            {
                "generated_at": timezone.now(),
                "date_from": date_from,
                "date_to": date_to,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "product": request.query_params.get("product"),
                "totals": {
                    "count": len(rows),
                    "amount": self._decimal_string(total_disbursed),
                    "principal_outstanding": self._decimal_string(principal_outstanding),
                    "interest_outstanding": self._decimal_string(interest_outstanding),
                    "portfolio_balance": self._decimal_string(
                        principal_outstanding + interest_outstanding
                    ),
                },
                "rows": rows,
            }
        )

    @action(detail=False, methods=["get"], url_path="loan-collections")
    def loan_collections(self, request):
        date_from = self._parse_date(
            request.query_params.get("date_from"),
            field_name="date_from",
        )
        date_to = self._parse_date(
            request.query_params.get("date_to"),
            field_name="date_to",
        )
        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                {"date_to": ["End date must be on or after the start date."]}
            )

        loan_ids = self._scoped_loans_queryset(request).values_list("id", flat=True)
        repayments = LoanRepayment.objects.filter(loan_id__in=loan_ids).select_related(
            "loan__client__branch",
            "loan__product",
            "received_by",
        )
        if date_from:
            repayments = repayments.filter(created_at__date__gte=date_from)
        if date_to:
            repayments = repayments.filter(created_at__date__lte=date_to)

        rows = [
            {
                "repayment_id": str(repayment.id),
                "loan_id": str(repayment.loan_id),
                "client_name": repayment.loan.client_name,
                "client_member_number": repayment.loan.client_member_number,
                "branch_name": repayment.loan.branch_name,
                "product_name": repayment.loan.product_name,
                "product_code": repayment.loan.product_code,
                "recorded_at": self._date_string(repayment.created_at),
                "reference": repayment.reference,
                "payment_method": repayment.payment_method,
                "amount": self._decimal_string(repayment.amount),
                "principal_component": self._decimal_string(repayment.principal_component),
                "interest_component": self._decimal_string(repayment.interest_component),
                "penalty_component": self._decimal_string(repayment.penalty_component),
                "remaining_balance_after": self._decimal_string(
                    repayment.remaining_balance_after
                ),
                "received_by_email": getattr(repayment.received_by, "email", ""),
            }
            for repayment in repayments.order_by("-created_at")
        ]

        total_amount = sum((repayment.amount for repayment in repayments), Decimal("0.00"))
        principal_component = sum(
            (repayment.principal_component for repayment in repayments),
            Decimal("0.00"),
        )
        interest_component = sum(
            (repayment.interest_component for repayment in repayments),
            Decimal("0.00"),
        )
        penalty_component = sum(
            (repayment.penalty_component for repayment in repayments),
            Decimal("0.00"),
        )

        return response.Response(
            {
                "generated_at": timezone.now(),
                "date_from": date_from,
                "date_to": date_to,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "product": request.query_params.get("product"),
                "totals": {
                    "count": len(rows),
                    "amount": self._decimal_string(total_amount),
                    "principal_component": self._decimal_string(principal_component),
                    "interest_component": self._decimal_string(interest_component),
                    "penalty_component": self._decimal_string(penalty_component),
                },
                "rows": rows,
            }
        )

    @action(detail=False, methods=["get"], url_path="loan-arrears-aging")
    def loan_arrears_aging(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = self._parse_date(as_of_raw, field_name="as_of") if as_of_raw else timezone.localdate()

        qs = (
            self._scoped_loans_queryset(request)
            .filter(
                status__in=[
                    LoanApplication.Status.APPROVED,
                    LoanApplication.Status.DISBURSED,
                    LoanApplication.Status.CLOSED,
                    LoanApplication.Status.WRITTEN_OFF,
                ]
            )
            .prefetch_related("schedule")
        )

        rows = []
        total_bucket_1_30 = Decimal("0.00")
        total_bucket_31_60 = Decimal("0.00")
        total_bucket_61_90 = Decimal("0.00")
        total_bucket_91_plus = Decimal("0.00")
        overdue_balance = Decimal("0.00")
        portfolio_balance = Decimal("0.00")

        for loan in qs:
            portfolio_balance += loan.outstanding_balance
            arrears = self._loan_arrears_snapshot(loan, as_of=as_of)
            if arrears["overdue_amount"] <= Decimal("0.00"):
                continue

            total_bucket_1_30 += arrears["bucket_1_30"]
            total_bucket_31_60 += arrears["bucket_31_60"]
            total_bucket_61_90 += arrears["bucket_61_90"]
            total_bucket_91_plus += arrears["bucket_91_plus"]
            overdue_balance += arrears["overdue_amount"]

            rows.append(
                {
                    "loan_id": str(loan.id),
                    "client_name": loan.client_name,
                    "client_member_number": loan.client_member_number,
                    "branch_name": loan.branch_name,
                    "product_name": loan.product_name,
                    "product_code": loan.product_code,
                    "status": loan.status,
                    "disbursed_at": self._date_string(loan.disbursed_at),
                    "next_due_date": self._date_string(
                        loan.schedule.filter(is_paid=False)
                        .order_by("due_date", "created_at")
                        .first()
                        .due_date
                        if loan.schedule.filter(is_paid=False).exists()
                        else None
                    ),
                    "oldest_due_date": self._date_string(arrears["oldest_due_date"]),
                    "days_past_due": arrears["days_past_due"],
                    "overdue_installments": arrears["overdue_installments"],
                    "overdue_amount": self._decimal_string(arrears["overdue_amount"]),
                    "outstanding_balance": self._decimal_string(loan.outstanding_balance),
                    "bucket_1_30": self._decimal_string(arrears["bucket_1_30"]),
                    "bucket_31_60": self._decimal_string(arrears["bucket_31_60"]),
                    "bucket_61_90": self._decimal_string(arrears["bucket_61_90"]),
                    "bucket_91_plus": self._decimal_string(arrears["bucket_91_plus"]),
                }
            )

        par_ratio = Decimal("0.00")
        if portfolio_balance > Decimal("0.00"):
            par_ratio = (overdue_balance / portfolio_balance * Decimal("100")).quantize(
                Decimal("0.01")
            )

        return response.Response(
            {
                "generated_at": timezone.now(),
                "as_of": as_of,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "product": request.query_params.get("product"),
                "totals": {
                    "loans_in_arrears": len(rows),
                    "overdue_balance": self._decimal_string(overdue_balance),
                    "portfolio_balance": self._decimal_string(portfolio_balance),
                    "par_ratio": self._decimal_string(par_ratio),
                    "bucket_1_30": self._decimal_string(total_bucket_1_30),
                    "bucket_31_60": self._decimal_string(total_bucket_31_60),
                    "bucket_61_90": self._decimal_string(total_bucket_61_90),
                    "bucket_91_plus": self._decimal_string(total_bucket_91_plus),
                },
                "rows": sorted(rows, key=lambda row: row["days_past_due"], reverse=True),
            }
        )

    @action(detail=False, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = self._parse_date(as_of_raw, field_name="as_of") if as_of_raw else timezone.localdate()

        data = trial_balance_data_for_user(
            request.user,
            institution_id=request.query_params.get("institution") or None,
            branch_id=request.query_params.get("branch") or None,
            as_of=as_of,
        )
        return response.Response(
            {
                "generated_at": timezone.now(),
                "as_of": as_of,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "rows": data["rows"],
                "totals": {
                    "debit": data["total_debit"],
                    "credit": data["total_credit"],
                    "difference": data["difference"],
                },
            }
        )

    @action(detail=False, methods=["get"], url_path="general-ledger")
    def general_ledger(self, request):
        rows = general_ledger_data_for_user(
            request.user,
            institution_id=request.query_params.get("institution") or None,
            branch_id=request.query_params.get("branch") or None,
            account_id=request.query_params.get("account") or None,
            date_from=self._parse_date(
                request.query_params.get("date_from"),
                field_name="date_from",
            ),
            date_to=self._parse_date(
                request.query_params.get("date_to"),
                field_name="date_to",
            ),
        )
        return response.Response(
            {
                "generated_at": timezone.now(),
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "account": request.query_params.get("account"),
                "rows": rows,
            }
        )

    @action(detail=False, methods=["get"], url_path="income-statement")
    def income_statement(self, request):
        return response.Response(
            {
                "detail": (
                    "Income statement is not yet fully implemented. Use trial balance "
                    "and balance sheet for current accounting verification."
                )
            }
        )

    @action(detail=False, methods=["get"], url_path="balance-sheet")
    def balance_sheet(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = self._parse_date(as_of_raw, field_name="as_of") if as_of_raw else timezone.localdate()

        data = balance_sheet_data_for_user(
            request.user,
            institution_id=request.query_params.get("institution") or None,
            branch_id=request.query_params.get("branch") or None,
            as_of=as_of,
        )
        return response.Response(
            {
                "generated_at": timezone.now(),
                "as_of": as_of,
                "institution": request.query_params.get("institution"),
                "branch": request.query_params.get("branch"),
                "sections": data["sections"],
                "totals": data["totals"],
            }
        )
