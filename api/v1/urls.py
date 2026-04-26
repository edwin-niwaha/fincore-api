from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounting.views import AccountViewSet, JournalEntryViewSet
from apps.audit.views import AuditLogViewSet
from apps.clients.views import ClientViewSet
from apps.dashboards.views import (
    AdminDashboardView,
    ClientDashboardView,
    StaffDashboardView,
)
from apps.institutions.views import BranchViewSet, InstitutionViewSet
from apps.loans.views import (
    LoanApplicationViewSet,
    LoanProductViewSet,
    LoanRepaymentViewSet,
)
from apps.notifications.views import NotificationViewSet
from apps.reports.views import FinancialReportViewSet
from apps.savings.views import SavingsAccountViewSet, SavingsTransactionViewSet
from apps.transactions.views import TransactionViewSet

# ✅ UPDATED USERS IMPORTS
from apps.users.views import (
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    UserViewSet,
    ForgotPasswordView,
    ResetPasswordView,
    ChangePasswordView,
    SendEmailVerificationView,
    VerifyEmailView,
    GoogleLoginAPIView,
)

# Router
router = DefaultRouter()

# =========================
# Core Modules
# =========================

# Institutions
router.register("institutions", InstitutionViewSet, basename="institution")
router.register("branches", BranchViewSet, basename="branch")

# Users (admin/staff management)
router.register("users", UserViewSet, basename="user")

# Clients
router.register("clients", ClientViewSet, basename="client")

# Accounting
router.register("accounting/accounts", AccountViewSet, basename="account")
router.register("accounting/journal-entries", JournalEntryViewSet, basename="journal-entry")

# Savings
router.register("savings/accounts", SavingsAccountViewSet, basename="savings-account")
router.register("savings/transactions", SavingsTransactionViewSet, basename="savings-transaction")

# Loans
router.register("loans/products", LoanProductViewSet, basename="loan-product")
router.register("loans/applications", LoanApplicationViewSet, basename="loan-application")
router.register("loans/repayments", LoanRepaymentViewSet, basename="loan-repayment")

# Transactions
router.register("transactions", TransactionViewSet, basename="transaction")

# Notifications
router.register("notifications", NotificationViewSet, basename="notification")

# Audit Logs
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

# Reports
router.register("reports", FinancialReportViewSet, basename="report")


urlpatterns = [
    # =========================================
    # AUTH (FinCore Clean Auth System)
    # =========================================

    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", MeView.as_view(), name="auth-me"),

    # JWT
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/verify/", TokenVerifyView.as_view(), name="auth-verify"),

    # Password Management
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="auth-reset-password"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="auth-change-password"),

    # Email Verification
    path("auth/send-email-verification/", SendEmailVerificationView.as_view(), name="auth-send-email-verification"),
    path("auth/verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),

    # Social Auth
    path("auth/social/google/", GoogleLoginAPIView.as_view(), name="auth-google-login"),

    # =========================================
    # Dashboards
    # =========================================
    path("dashboards/client/", ClientDashboardView.as_view(), name="dashboard-client"),
    path("dashboards/staff/", StaffDashboardView.as_view(), name="dashboard-staff"),
    path("dashboards/admin/", AdminDashboardView.as_view(), name="dashboard-admin"),


    # =========================================
    # API ROUTER
    # =========================================
    path("", include(router.urls)),
]