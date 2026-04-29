from django.contrib import admin
from django.db.models import Count

from .models import Branch, Institution


class BranchInline(admin.TabularInline):
    model = Branch
    extra = 0
    fields = ("name", "code", "status", "address")
    show_change_link = True


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "status",
        "currency",
        "branch_count",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("name", "code", "email", "phone")
    ordering = ("name",)
    inlines = [BranchInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_branch_count=Count("branches"))

    def branch_count(self, obj):
        return getattr(obj, "_branch_count", 0)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "institution", "status", "created_at")
    list_filter = ("status", "institution")
    search_fields = ("name", "code", "institution__name", "institution__code", "address")
    ordering = ("institution__name", "name")
    list_select_related = ("institution",)
