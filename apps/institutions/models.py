from cloudinary.models import CloudinaryField
from django.db import models

from apps.common.models import StatusChoices, TimeStampedModel


class Institution(TimeStampedModel):
    name = models.CharField(max_length=180)
    code = models.SlugField(unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=8, default="UGX")

    logo = CloudinaryField(
        "institution_logo",
        folder="institution-logos",
        transformation={
            "width": 300,
            "height": 300,
            "crop": "limit",
            "quality": "auto",
            "format": "png",
        },
        blank=True,
        null=True,
    )
    postal_address = models.CharField(max_length=255, blank=True)
    physical_address = models.CharField(max_length=255, blank=True)
    website = models.CharField(max_length=120, blank=True)
    statement_title = models.CharField(
        max_length=120,
        default="ACCOUNT STATEMENT",
    )

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE,
    )

    def __str__(self):
        return self.name


class Branch(TimeStampedModel):
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name="branches",
    )
    name = models.CharField(max_length=180)
    code = models.SlugField()
    address = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE,
    )

    class Meta:
        unique_together = ("institution", "code")

    def __str__(self):
        return f"{self.institution.code} - {self.name}"
