from django.conf import settings
from django.db import models
from apps.common.models import TimeStampedModel


class Notification(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=160)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    category = models.CharField(max_length=40, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta(TimeStampedModel.Meta):
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"]),
            models.Index(fields=["category", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.title}"
