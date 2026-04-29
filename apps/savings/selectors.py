from django.db.models import Count, Max

from apps.users.models import CustomUser

from .models import SavingsAccount


def savings_accounts_for_user(user):
    queryset = (
        SavingsAccount.objects.select_related("client", "client__branch", "client__institution")
        .annotate(
            transaction_count=Count("transactions", distinct=True),
            last_transaction_at=Max("transactions__created_at"),
        )
        .order_by("account_number", "client__last_name", "client__first_name")
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
