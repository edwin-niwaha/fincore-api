from django.db import models
from apps.common.models import StatusChoices, TimeStampedModel

class Client(TimeStampedModel):
    user = models.OneToOneField("users.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="client_profile")
    institution = models.ForeignKey("institutions.Institution", on_delete=models.PROTECT, related_name="clients")
    branch = models.ForeignKey("institutions.Branch", on_delete=models.PROTECT, related_name="clients")
    member_number = models.CharField(max_length=40, unique=True, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    national_id = models.CharField(max_length=80, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    occupation = models.CharField(max_length=120, blank=True)
    next_of_kin_name = models.CharField(max_length=160, blank=True)
    next_of_kin_phone = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)

    def save(self, *args, **kwargs):
        if not self.member_number:
            prefix = self.branch.code.upper()[:4]
            count = Client.objects.filter(branch=self.branch).count() + 1
            self.member_number = f"{prefix}-{count:06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member_number} - {self.first_name} {self.last_name}"
