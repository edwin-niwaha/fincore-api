from apps.users.models import CustomUser

from .models import Client


def clients_for_user(user):
    queryset = Client.objects.select_related(
        "institution",
        "branch",
        "user",
        "created_by",
        "updated_by",
    ).order_by("member_number", "last_name", "first_name")

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.role == CustomUser.Role.CLIENT:
        return queryset.filter(user=user)

    if user.role == CustomUser.Role.SUPER_ADMIN:
        return queryset

    if user.branch_id:
        return queryset.filter(branch=user.branch)

    if user.institution_id:
        return queryset.filter(institution=user.institution)

    return queryset.none()
