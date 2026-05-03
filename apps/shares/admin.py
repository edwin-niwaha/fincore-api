from django.contrib import admin
from .models import ShareAccount, ShareAccountSequence, ShareProduct, ShareTransaction

@admin.register(ShareProduct)
class ShareProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "institution", "nominal_price", "status")
    search_fields = ("code", "name")
    list_filter = ("status", "institution")

@admin.register(ShareAccount)
class ShareAccountAdmin(admin.ModelAdmin):
    list_display = ("account_number", "client", "product", "shares", "total_value", "status")
    search_fields = ("account_number", "client__member_number", "client__first_name", "client__last_name")
    list_filter = ("status", "product")

@admin.register(ShareTransaction)
class ShareTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "account", "type", "shares", "amount", "balance_after", "created_at")
    search_fields = ("reference", "account__account_number")
    list_filter = ("type",)

admin.site.register(ShareAccountSequence)
