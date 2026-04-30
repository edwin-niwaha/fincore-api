from django.contrib import admin

from .models import (
    LoanApplication,
    LoanApplicationAction,
    LoanProduct,
    LoanRepayment,
    RepaymentSchedule,
)

admin.site.register(LoanProduct)
admin.site.register(LoanApplication)
admin.site.register(RepaymentSchedule)
admin.site.register(LoanRepayment)
admin.site.register(LoanApplicationAction)
