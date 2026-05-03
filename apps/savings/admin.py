from django.contrib import admin

from .models import SavingsAccount, SavingsAccountSequence, SavingsPolicy, SavingsTransaction


@admin.register(SavingsPolicy)
class SavingsPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "minimum_balance", "withdrawal_charge", "is_active", "updated_at")
    list_editable = ("minimum_balance", "withdrawal_charge", "is_active")
    search_fields = ("name",)


@admin.register(SavingsAccount)
class SavingsAccountAdmin(admin.ModelAdmin):
    list_display = ("account_number", "client", "balance", "status", "updated_at")
    search_fields = ("account_number", "client__member_number", "client__first_name", "client__last_name")
    list_filter = ("status", "client__institution", "client__branch")


@admin.register(SavingsTransaction)
class SavingsTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "account", "type", "amount", "balance_after", "transaction_date", "performed_by")
    search_fields = ("reference", "account__account_number", "account__client__member_number")
    list_filter = ("type", "transaction_date", "account__client__institution", "account__client__branch")
    readonly_fields = ("account", "type", "amount", "balance_after", "reference", "performed_by", "notes")


@admin.register(SavingsAccountSequence)
class SavingsAccountSequenceAdmin(admin.ModelAdmin):
    list_display = ("branch", "last_value")
    search_fields = ("branch__name", "branch__code")
