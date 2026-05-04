from django.urls import path

from . import web_views

app_name = "savings_web"

urlpatterns = [
    path("accounts/", web_views.account_list, name="account-list"),
    path("accounts/<uuid:pk>/", web_views.account_detail, name="account-detail"),
    path("accounts/<uuid:pk>/deposit/", web_views.account_deposit, name="account-deposit"),
    path(
        "accounts/<uuid:pk>/withdraw/",
        web_views.account_withdraw,
        name="account-withdraw",
    ),
]
