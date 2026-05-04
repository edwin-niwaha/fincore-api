from django.contrib import admin

from .models import Client, ClientMemberSequence, ClientStatusHistory


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "member_number",
        "first_name",
        "last_name",
        "phone",
        "membership_type",
        "gender",
        "branch",
        "status",
        "kyc_status",
        "risk_rating",
        "is_watchlist_flagged",
    )
    search_fields = (
        "member_number",
        "first_name",
        "last_name",
        "phone",
        "email",
        "national_id",
        "passport_number",
        "registration_number",
    )
    list_filter = (
        "status",
        "kyc_status",
        "membership_type",
        "risk_rating",
        "is_watchlist_flagged",
        "gender",
        "institution",
        "branch",
    )


@admin.register(ClientMemberSequence)
class ClientMemberSequenceAdmin(admin.ModelAdmin):
    list_display = ("branch", "last_value")
    search_fields = ("branch__name", "branch__code", "branch__institution__name")


@admin.register(ClientStatusHistory)
class ClientStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("client", "from_status", "to_status", "changed_by", "created_at")
    list_filter = ("to_status", "created_at")
    search_fields = ("client__member_number", "client__first_name", "client__last_name")
