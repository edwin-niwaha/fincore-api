from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser, EmailOTP


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
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
    list_select_related = ("institution", "branch")

    readonly_fields = (
        "created_at",
        "updated_at",
        "last_login",
        "date_joined",
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))

        cloudinary_enabled = getattr(settings, "ENABLE_CLOUDINARY", False)

        if not cloudinary_enabled:
            cleaned_fieldsets = []

            for title, options in fieldsets:
                options = options.copy()
                fields = options.get("fields")

                if fields:
                    options["fields"] = tuple(
                        field for field in fields if field != "avatar"
                    )

                cleaned_fieldsets.append((title, options))

            return cleaned_fieldsets

        return fieldsets


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
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
    list_select_related = ("user",)

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