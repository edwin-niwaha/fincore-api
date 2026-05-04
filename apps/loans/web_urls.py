from django.urls import path

from . import web_views

app_name = "loans_web"

urlpatterns = [
    path("products/", web_views.product_list, name="product-list"),
    path("applications/", web_views.application_list, name="application-list"),
    path("applications/<uuid:pk>/", web_views.application_detail, name="application-detail"),
    path(
        "applications/<uuid:pk>/approve/",
        web_views.application_approve,
        name="application-approve",
    ),
    path(
        "applications/<uuid:pk>/disburse/",
        web_views.application_disburse,
        name="application-disburse",
    ),
    path(
        "applications/<uuid:pk>/repay/",
        web_views.application_repay,
        name="application-repay",
    ),
]
