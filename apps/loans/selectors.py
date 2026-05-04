from decimal import Decimal

from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from apps.users.models import CustomUser

from .models import LoanApplication, LoanProduct


def loan_products_for_user(user):
    queryset = (
        LoanProduct.objects.select_related(
            "institution",
            "receivable_account",
            "funding_account",
            "interest_income_account",
        )
        .annotate(
            application_count=Count("loanapplication", distinct=True),
            total_requested_amount=Coalesce(
                Sum("loanapplication__amount"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("institution__name", "code", "name")
    )

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.role == CustomUser.Role.CLIENT:
        if user.institution_id:
            return queryset.filter(institution=user.institution, is_active=True)
        return queryset.none()

    if user.role == CustomUser.Role.SUPER_ADMIN:
        return queryset

    if user.institution_id:
        return queryset.filter(institution=user.institution)

    return queryset.none()


def loans_for_user(user):
    queryset = (
        LoanApplication.objects.select_related(
            "client",
            "product",
            "product__institution",
            "client__institution",
            "client__branch",
            "created_by",
            "submitted_by",
            "appraised_by",
            "recommended_by",
            "approved_by",
            "rejected_by",
            "withdrawn_by",
            "disbursed_by",
        )
        .annotate(
            repayment_count=Count("repayments", distinct=True),
            schedule_count=Count("schedule", distinct=True),
        )
        .order_by("-created_at")
    )

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.role == CustomUser.Role.CLIENT:
        return queryset.filter(client__user=user)

    if user.role == CustomUser.Role.SUPER_ADMIN:
        return queryset

    if user.branch_id:
        return queryset.filter(client__branch=user.branch)

    if user.institution_id:
        return queryset.filter(client__institution=user.institution)

    return queryset.none()
