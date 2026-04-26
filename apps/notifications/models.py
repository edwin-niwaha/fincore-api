from django.db import models
from apps.common.models import TimeStampedModel
class Notification(TimeStampedModel):
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=160)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    category = models.CharField(max_length=40, blank=True)
