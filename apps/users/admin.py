from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser, EmailOTP


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    # =========================
    # Fieldsets
    # =========================
    fieldsets = tuple(UserAdmin.fieldsets) + (
        (
            "FinCore Access",
            {
                "fields": (
                    "role",
                    "user_type",
                    "institution",
                    "branch",
                    "phone",
                    "avatar",
                    "is_email_verified",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    add_fieldsets = tuple(UserAdmin.add_fieldsets) + (
        (
            "FinCore Access",
            {
                "fields": (
                    "email",
                    "role",
                    "institution",
                    "branch",
                    "phone",
                )
            },
        ),
    )

    # =========================
    # List View
    # =========================
    list_display = (
        "id",
        "email",
        "username",
        "role",
        "institution",
        "branch",
        "is_active",
        "is_email_verified",
        "created_at",
    )

    list_filter = (
        "role",
        "user_type",
        "institution",
        "branch",
        "is_active",
        "is_email_verified",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "email",
        "username",
        "first_name",
        "last_name",
        "phone",
        "institution__name",
        "branch__name",
    )

    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    # =========================
    # Performance
    # =========================
    list_select_related = ("institution", "branch")

    # ✅ ONLY enable if InstitutionAdmin & BranchAdmin have search_fields
    # autocomplete_fields = ("institution", "branch")

    # =========================
    # Readonly
    # =========================
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_login",
        "date_joined",
    )


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    # =========================
    # List View
    # =========================
    list_display = (
        "id",
        "email",
        "purpose",
        "user",
        "expires_at",
        "used_at",
        "attempts",
        "created_at",
    )

    list_filter = (
        "purpose",
        "used_at",
        "created_at",
        "expires_at",
    )

    search_fields = (
        "email",
        "user__email",
        "user__username",
    )

    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    # =========================
    # Performance
    # =========================
    list_select_related = ("user",)

    # =========================
    # Readonly
    # =========================
    readonly_fields = (
        "user",
        "email",
        "purpose",
        "code_hash",
        "expires_at",
        "used_at",
        "attempts",
        "max_attempts",
        "created_at",
    )