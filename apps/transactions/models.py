from django.conf import settings
from django.db import models
from apps.common.models import TimeStampedModel

class Transaction(TimeStampedModel):
    institution = models.ForeignKey("institutions.Institution", on_delete=models.PROTECT)
    branch = models.ForeignKey("institutions.Branch", on_delete=models.PROTECT)
    client = models.ForeignKey("clients.Client", null=True, blank=True, on_delete=models.PROTECT)
    category = models.CharField(max_length=40)
    direction = models.CharField(max_length=20, choices=(("debit", "Debit"), ("credit", "Credit")))
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
