from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils.text import slugify

from apps.common.models import TimeStampedModel


class ClientStatusChoices(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    BLACKLISTED = "blacklisted", "Blacklisted"


class GenderChoices(models.TextChoices):
    FEMALE = "female", "Female"
    MALE = "male", "Male"
    OTHER = "other", "Other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer Not To Say"


def build_member_number_prefix(branch):
    branch_code = slugify(getattr(branch, "code", "")) or "member"
    compact_code = branch_code.replace("-", "").upper()
    return compact_code[:4] or "MEMB"


class ClientMemberSequence(models.Model):
    branch = models.OneToOneField(
        "institutions.Branch",
        on_delete=models.CASCADE,
        related_name="client_member_sequence",
    )
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Client member sequence"
        verbose_name_plural = "Client member sequences"

    def __str__(self):
        return f"{self.branch.code.upper()} #{self.last_value}"

    @classmethod
    def next_value_for_branch(cls, branch):
        with transaction.atomic():
            sequence, _ = cls.objects.select_for_update().get_or_create(
                branch=branch,
                defaults={"last_value": 0},
            )
            sequence.last_value = F("last_value") + 1
            sequence.save(update_fields=["last_value"])
            sequence.refresh_from_db(fields=["last_value"])
            return sequence.last_value

class Client(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_profile",
    )
    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.PROTECT,
        related_name="clients",
    )
    branch = models.ForeignKey(
        "institutions.Branch",
        on_delete=models.PROTECT,
        related_name="clients",
    )
    member_number = models.CharField(max_length=40, unique=True, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    national_id = models.CharField(max_length=80, blank=True)
    gender = models.CharField(max_length=20, choices=GenderChoices.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    occupation = models.CharField(max_length=120, blank=True)
    next_of_kin_name = models.CharField(max_length=160, blank=True)
    next_of_kin_phone = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ClientStatusChoices.choices,
        default=ClientStatusChoices.ACTIVE,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_clients",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_clients",
    )

    def save(self, *args, **kwargs):
        if not self.member_number:
            next_value = ClientMemberSequence.next_value_for_branch(self.branch)
            prefix = build_member_number_prefix(self.branch)
            self.member_number = f"{prefix}-{next_value:06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member_number} - {self.first_name} {self.last_name}"
