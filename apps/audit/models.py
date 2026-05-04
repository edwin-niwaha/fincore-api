from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class AuditLog(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    institution = models.ForeignKey(
        "institutions.Institution",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    branch = models.ForeignKey(
        "institutions.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=120)
    module = models.CharField(max_length=80, blank=True, db_index=True)
    resource = models.CharField(max_length=80, blank=True, db_index=True)
    event = models.CharField(max_length=80, blank=True, db_index=True)
    target = models.CharField(max_length=180, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    request_path = models.CharField(max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        indexes = [
            models.Index(fields=["module", "resource", "event"], name="aud_mod_res_evt_idx"),
            models.Index(fields=["institution", "branch", "created_at"], name="aud_scope_cr_idx"),
            models.Index(fields=["user", "created_at"], name="aud_usr_cr_idx"),
            models.Index(fields=["action", "created_at"], name="aud_act_cr_idx"),
        ]

    def __str__(self):
        if self.target:
            return f"{self.action} -> {self.target}"
        return self.action
