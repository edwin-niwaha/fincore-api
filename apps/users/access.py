from .models import CustomUser

USER_MANAGER_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
}

ADMIN_LIKE_ROLES = {
    CustomUser.Role.SUPER_ADMIN,
    CustomUser.Role.INSTITUTION_ADMIN,
    CustomUser.Role.BRANCH_MANAGER,
}

BRANCH_REQUIRED_ROLES = {
    CustomUser.Role.BRANCH_MANAGER,
    CustomUser.Role.LOAN_OFFICER,
    CustomUser.Role.ACCOUNTANT,
    CustomUser.Role.TELLER,
}

MANAGEABLE_ROLES_BY_ACTOR = {
    CustomUser.Role.SUPER_ADMIN: {role for role, _ in CustomUser.Role.choices},
    CustomUser.Role.INSTITUTION_ADMIN: {
        CustomUser.Role.INSTITUTION_ADMIN,
        CustomUser.Role.BRANCH_MANAGER,
        CustomUser.Role.LOAN_OFFICER,
        CustomUser.Role.ACCOUNTANT,
        CustomUser.Role.TELLER,
        CustomUser.Role.CLIENT,
    },
    CustomUser.Role.BRANCH_MANAGER: {
        CustomUser.Role.LOAN_OFFICER,
        CustomUser.Role.ACCOUNTANT,
        CustomUser.Role.TELLER,
        CustomUser.Role.CLIENT,
    },
}


def user_role(user):
    return getattr(user, "role", None)


def is_super_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user_role(user) == CustomUser.Role.SUPER_ADMIN
        )
    )


def is_user_manager(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_super_admin(user)
            or user_role(user) in USER_MANAGER_ROLES
        )
    )


def manageable_roles_for(user):
    if is_super_admin(user):
        return MANAGEABLE_ROLES_BY_ACTOR[CustomUser.Role.SUPER_ADMIN]

    return MANAGEABLE_ROLES_BY_ACTOR.get(user_role(user), set())


def can_manage_role(user, role):
    return role in manageable_roles_for(user)


def role_requires_institution(role):
    return role != CustomUser.Role.SUPER_ADMIN


def role_requires_branch(role):
    return role in BRANCH_REQUIRED_ROLES


def infer_user_type(role):
    if role in ADMIN_LIKE_ROLES:
        return CustomUser.UserType.ADMIN
    return CustomUser.UserType.USER


def scope_user_queryset(queryset, actor):
    if is_super_admin(actor):
        return queryset

    actor_role = user_role(actor)
    manageable_roles = manageable_roles_for(actor)

    if actor_role == CustomUser.Role.INSTITUTION_ADMIN and actor.institution_id:
        return queryset.filter(
            institution_id=actor.institution_id,
            role__in=manageable_roles,
        )

    if (
        actor_role == CustomUser.Role.BRANCH_MANAGER
        and actor.institution_id
        and actor.branch_id
    ):
        return queryset.filter(
            institution_id=actor.institution_id,
            branch_id=actor.branch_id,
            role__in=manageable_roles,
        )

    return queryset.none()
