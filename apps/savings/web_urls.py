from django.urls import path

from .web_views import (
    SavingsAccountDepositView,
    SavingsAccountDetailView,
    SavingsAccountListView,
    SavingsAccountWithdrawalView,
)

app_name = "savings_web"

urlpatterns = [
    path("accounts/", SavingsAccountListView.as_view(), name="account-list"),
    path("accounts/<uuid:pk>/", SavingsAccountDetailView.as_view(), name="account-detail"),
    path(
        "accounts/<uuid:pk>/deposit/",
        SavingsAccountDepositView.as_view(),
        name="account-deposit",
    ),
    path(
        "accounts/<uuid:pk>/withdraw/",
        SavingsAccountWithdrawalView.as_view(),
        name="account-withdraw",
    ),
]
