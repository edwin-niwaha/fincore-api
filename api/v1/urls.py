from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounting.views import AccountViewSet, JournalEntryViewSet
from apps.audit.views import AuditLogViewSet
from apps.clients.views import ClientViewSet
from apps.clients.self_service_views import (
    SelfServiceDashboardView,
    SelfServiceLoanApplicationViewSet,
    SelfServiceLoanProductViewSet,
    SelfServiceLoanRepaymentViewSet,
    SelfServiceLoanStatementView,
    SelfServiceLoanViewSet,
    SelfServiceNotificationViewSet,
    SelfServiceProfileView,
    SelfServiceSavingsStatementView,
    SelfServiceSavingsSummaryView,
    SelfServiceSavingsTransactionViewSet,
    SelfServiceSavingsViewSet,
    SelfServiceTransactionViewSet,
)
from apps.shares.views import ShareAccountViewSet, ShareProductViewSet, ShareTransactionViewSet
from apps.common.views import HealthCheckView
from apps.dashboards.views import AdminDashboardView, ClientDashboardView, StaffDashboardView
from apps.institutions.views import BranchViewSet, InstitutionViewSet
from apps.loans.views import LoanApplicationViewSet, LoanProductViewSet, LoanRepaymentViewSet
from apps.notifications.views import NotificationViewSet
from apps.reports.views import FinancialReportViewSet
from apps.savings.views import SavingsAccountViewSet, SavingsTransactionViewSet
from apps.transactions.views import TransactionViewSet
from apps.users.views import (
    ChangePasswordView,
    ForgotPasswordView,
    GoogleLoginAPIView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    ResetPasswordView,
    SendEmailVerificationView,
    UserViewSet,
    VerifyEmailView,
)

router = DefaultRouter()

router.register("institutions", InstitutionViewSet, basename="institution")
router.register("branches", BranchViewSet, basename="branch")
router.register("users", UserViewSet, basename="user")
router.register("clients", ClientViewSet, basename="client")
router.register("accounting/accounts", AccountViewSet, basename="account")
router.register("accounting/journal-entries", JournalEntryViewSet, basename="journal-entry")
router.register("savings/accounts", SavingsAccountViewSet, basename="savings-account")
router.register("savings/transactions", SavingsTransactionViewSet, basename="savings-transaction")
router.register("shares/products", ShareProductViewSet, basename="share-product")
router.register("shares/accounts", ShareAccountViewSet, basename="share-account")
router.register("shares/transactions", ShareTransactionViewSet, basename="share-transaction")
router.register("loans/products", LoanProductViewSet, basename="loan-product")
router.register("loans/applications", LoanApplicationViewSet, basename="loan-application")
router.register("loans/repayments", LoanRepaymentViewSet, basename="loan-repayment")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("reports", FinancialReportViewSet, basename="report")


urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("me/", MeView.as_view(), name="me"),
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/verify/", TokenVerifyView.as_view(), name="auth-verify"),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="auth-reset-password"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    path(
        "auth/send-email-verification/",
        SendEmailVerificationView.as_view(),
        name="auth-send-email-verification",
    ),
    path("auth/verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("auth/social/google/", GoogleLoginAPIView.as_view(), name="auth-google-login"),
    path("dashboards/client/", ClientDashboardView.as_view(), name="dashboard-client"),
    path("dashboards/staff/", StaffDashboardView.as_view(), name="dashboard-staff"),
    path("dashboards/admin/", AdminDashboardView.as_view(), name="dashboard-admin"),
    path("self-service/profile/", SelfServiceProfileView.as_view(), name="self-service-profile"),
    path(
        "self-service/dashboard/",
        SelfServiceDashboardView.as_view(),
        name="self-service-dashboard",
    ),
    path(
        "self-service/savings/",
        SelfServiceSavingsViewSet.as_view({"get": "list"}),
        name="self-service-savings",
    ),
    path(
        "self-service/savings/summary/",
        SelfServiceSavingsSummaryView.as_view(),
        name="self-service-savings-summary",
    ),
    path(
        "self-service/savings/statement/",
        SelfServiceSavingsStatementView.as_view(),
        name="self-service-savings-statement",
    ),
    path(
        "self-service/savings/transactions/",
        SelfServiceSavingsTransactionViewSet.as_view({"get": "list"}),
        name="self-service-savings-transactions",
    ),
    path(
        "self-service/loan-products/",
        SelfServiceLoanProductViewSet.as_view({"get": "list"}),
        name="self-service-loan-products",
    ),
    path(
        "self-service/loan-applications/",
        SelfServiceLoanApplicationViewSet.as_view({"get": "list", "post": "create"}),
        name="self-service-loan-applications",
    ),
    path(
        "self-service/loan-applications/<uuid:pk>/",
        SelfServiceLoanApplicationViewSet.as_view({"get": "retrieve"}),
        name="self-service-loan-application-detail",
    ),
    path(
        "self-service/loans/",
        SelfServiceLoanViewSet.as_view({"get": "list"}),
        name="self-service-loans",
    ),
    path(
        "self-service/loans/statement/",
        SelfServiceLoanStatementView.as_view(),
        name="self-service-loan-statement",
    ),
    path(
        "self-service/loans/<uuid:pk>/",
        SelfServiceLoanViewSet.as_view({"get": "retrieve"}),
        name="self-service-loan-detail",
    ),
    path(
        "self-service/repayments/",
        SelfServiceLoanRepaymentViewSet.as_view({"get": "list"}),
        name="self-service-repayments",
    ),
    path(
        "self-service/transactions/",
        SelfServiceTransactionViewSet.as_view({"get": "list"}),
        name="self-service-transactions",
    ),
    path(
        "self-service/notifications/",
        SelfServiceNotificationViewSet.as_view({"get": "list"}),
        name="self-service-notifications",
    ),
    path(
        "self-service/notifications/mark-all-read/",
        SelfServiceNotificationViewSet.as_view({"post": "mark_all_read"}),
        name="self-service-notifications-mark-all-read",
    ),
    path(
        "self-service/notifications/<uuid:pk>/mark-read/",
        SelfServiceNotificationViewSet.as_view(
            {"post": "mark_read", "patch": "mark_read"}
        ),
        name="self-service-notification-mark-read",
    ),
    path("", include(router.urls)),
]
