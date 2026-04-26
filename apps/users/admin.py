from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("FinCore", {"fields": ("role", "institution", "branch", "phone")}),)
    list_display = ("username", "email", "role", "institution", "branch", "is_active")
    list_filter = ("role", "institution", "branch", "is_active")
