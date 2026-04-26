from django.contrib import admin
from .models import Client
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("member_number", "first_name", "last_name", "phone", "branch", "status")
    search_fields = ("member_number", "first_name", "last_name", "phone", "national_id")
    list_filter = ("status", "institution", "branch")
