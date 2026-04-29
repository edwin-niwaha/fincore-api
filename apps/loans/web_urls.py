from django.urls import path

from .web_views import (
    LoanApplicationApproveView,
    LoanApplicationDetailView,
    LoanApplicationDisburseView,
    LoanApplicationListView,
    LoanApplicationRejectView,
    LoanApplicationRepaymentView,
    LoanProductListView,
)

app_name = "loans_web"

urlpatterns = [
    path("products/", LoanProductListView.as_view(), name="product-list"),
    path("applications/", LoanApplicationListView.as_view(), name="application-list"),
    path("applications/<uuid:pk>/", LoanApplicationDetailView.as_view(), name="application-detail"),
    path(
        "applications/<uuid:pk>/approve/",
        LoanApplicationApproveView.as_view(),
        name="application-approve",
    ),
    path(
        "applications/<uuid:pk>/reject/",
        LoanApplicationRejectView.as_view(),
        name="application-reject",
    ),
    path(
        "applications/<uuid:pk>/disburse/",
        LoanApplicationDisburseView.as_view(),
        name="application-disburse",
    ),
    path(
        "applications/<uuid:pk>/repay/",
        LoanApplicationRepaymentView.as_view(),
        name="application-repay",
    ),
]
