from django.contrib import admin

from .models import JournalEntry, JournalEntryLine, LedgerAccount


class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 0


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    inlines = [JournalEntryLineInline]
    list_display = (
        "reference",
        "institution",
        "branch",
        "entry_date",
        "status",
        "source",
        "posted_at",
    )
    list_filter = ("institution", "branch", "status", "source", "entry_date")
    search_fields = ("reference", "source_reference", "description")


@admin.register(LedgerAccount)
class LedgerAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "institution", "type", "normal_balance", "is_active")
    list_filter = ("institution", "type", "normal_balance", "is_active")
    search_fields = ("code", "name", "description")
