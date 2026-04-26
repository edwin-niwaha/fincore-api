from django.db import models
from apps.common.models import StatusChoices, TimeStampedModel

class Institution(TimeStampedModel):
    name = models.CharField(max_length=180)
    code = models.SlugField(unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=8, default="UGX")
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)

    def __str__(self):
        return self.name

class Branch(TimeStampedModel):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=180)
    code = models.SlugField()
    address = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)

    class Meta:
        unique_together = ("institution", "code")

    def __str__(self):
        return f"{self.institution.code} - {self.name}"
