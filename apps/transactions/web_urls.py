from django.urls import path

from .web_views import TransactionLedgerView

app_name = "transactions_web"

urlpatterns = [
    path("", TransactionLedgerView.as_view(), name="ledger"),
]
