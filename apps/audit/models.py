from django.db import models
from apps.common.models import TimeStampedModel
class AuditLog(TimeStampedModel):
    user = models.ForeignKey("users.User", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=120)
    target = models.CharField(max_length=180, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
