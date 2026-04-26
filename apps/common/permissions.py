from rest_framework.permissions import BasePermission

STAFF_ROLES = {
    "super_admin", "institution_admin", "branch_manager", "loan_officer", "accountant", "teller"
}
ADMIN_ROLES = {"super_admin", "institution_admin"}
ACCOUNTING_ROLES = {"super_admin", "institution_admin", "branch_manager", "accountant"}
LOAN_ROLES = {"super_admin", "institution_admin", "branch_manager", "loan_officer"}
CASH_ROLES = {"super_admin", "institution_admin", "branch_manager", "teller", "accountant"}

class IsStaffRole(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in STAFF_ROLES)

class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in ADMIN_ROLES)

class IsAccountingRole(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in ACCOUNTING_ROLES)

class IsLoanRole(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in LOAN_ROLES)

class IsCashRole(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in CASH_ROLES)
