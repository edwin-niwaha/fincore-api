from django.contrib import admin
from .models import JournalEntry, JournalEntryLine, LedgerAccount
class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 0
@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    inlines = [JournalEntryLineInline]
    list_display = ("reference", "institution", "branch", "posted_at")
admin.site.register(LedgerAccount)
