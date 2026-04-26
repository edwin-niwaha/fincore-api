def savings_accounts_for_user(user):
    from .models import SavingsAccount
    qs = SavingsAccount.objects.select_related('client', 'client__branch', 'client__institution')
    if user.role == 'client':
        return qs.filter(client__user=user)
    if user.role == 'super_admin':
        return qs
    if user.branch_id:
        return qs.filter(client__branch=user.branch)
    if user.institution_id:
        return qs.filter(client__institution=user.institution)
    return qs.none()
