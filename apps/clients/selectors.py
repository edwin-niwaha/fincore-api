def clients_for_user(user):
    qs = __import__('apps.clients.models', fromlist=['Client']).Client.objects.select_related('institution', 'branch', 'user')
    if user.role == 'client':
        return qs.filter(user=user)
    if user.role == 'super_admin':
        return qs
    if user.branch_id:
        return qs.filter(branch=user.branch)
    if user.institution_id:
        return qs.filter(institution=user.institution)
    return qs.none()
