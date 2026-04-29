from django.contrib import admin

from .models import Client, ClientMemberSequence


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("member_number", "first_name", "last_name", "phone", "branch", "status")
    search_fields = ("member_number", "first_name", "last_name", "phone", "national_id")
    list_filter = ("status", "institution", "branch")


@admin.register(ClientMemberSequence)
class ClientMemberSequenceAdmin(admin.ModelAdmin):
    list_display = ("branch", "last_value")
    search_fields = ("branch__name", "branch__code", "branch__institution__name")
