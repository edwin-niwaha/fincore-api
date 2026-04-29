from django.contrib import admin

from .models import SavingsAccount, SavingsTransaction

admin.site.register(SavingsAccount)
admin.site.register(SavingsTransaction)
