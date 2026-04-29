from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounting.views import AccountViewSet, JournalEntryViewSet
from apps.audit.views import AuditLogViewSet
from apps.clients.views import ClientViewSet
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
router.register("loans/products", LoanProductViewSet, basename="loan-product")
router.register("loans/applications", LoanApplicationViewSet, basename="loan-application")
router.register("loans/repayments", LoanRepaymentViewSet, basename="loan-repayment")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("reports", FinancialReportViewSet, basename="report")


urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
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
    path("", include(router.urls)),
]
