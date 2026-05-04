from django.urls import path

from . import web_views

app_name = "transactions_web"

urlpatterns = [
    path("ledger/", web_views.ledger, name="ledger"),
]
