def loans_for_user(user):
    from .models import LoanApplication
    qs = LoanApplication.objects.select_related('client', 'product', 'client__institution', 'client__branch')
    if user.role == 'client':
        return qs.filter(client__user=user)
    if user.role == 'super_admin':
        return qs
    if user.branch_id:
        return qs.filter(client__branch=user.branch)
    if user.institution_id:
        return qs.filter(client__institution=user.institution)
    return qs.none()
