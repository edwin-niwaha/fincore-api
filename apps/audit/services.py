class AuditService:
    @staticmethod
    def log(*, user=None, action, target="", metadata=None, ip_address=None):
        from .models import AuditLog
        return AuditLog.objects.create(user=user if getattr(user, "is_authenticated", False) else None, action=action, target=target, metadata=metadata or {}, ip_address=ip_address)
