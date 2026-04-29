from apps.users.models import CustomUser

from .models import Transaction


def transactions_for_user(user):
    queryset = (
        Transaction.objects.select_related(
            "institution",
            "branch",
            "client",
            "created_by",
        )
        .order_by("-created_at", "-id")
    )

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.role == CustomUser.Role.CLIENT:
        return queryset.filter(client__user=user)

    if user.role == CustomUser.Role.SUPER_ADMIN:
        return queryset

    if user.branch_id:
        return queryset.filter(branch=user.branch)

    if user.institution_id:
        return queryset.filter(institution=user.institution)

    return queryset.none()
