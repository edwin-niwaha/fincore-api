from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils.text import slugify
from cloudinary.models import CloudinaryField

from apps.common.models import TimeStampedModel


class ClientStatusChoices(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"
    REJECTED = "rejected", "Rejected"
    BLACKLISTED = "blacklisted", "Blacklisted"


class GenderChoices(models.TextChoices):
    FEMALE = "female", "Female"
    MALE = "male", "Male"
    OTHER = "other", "Other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer Not To Say"


class MembershipTypeChoices(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    GROUP = "group", "Group"
    ORGANIZATION = "organization", "Organization"


class KycStatusChoices(models.TextChoices):
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


class KycLevelChoices(models.TextChoices):
    LEVEL_1 = "level_1", "Level 1"
    LEVEL_2 = "level_2", "Level 2"
    LEVEL_3 = "level_3", "Level 3"


class RiskRatingChoices(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


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
    passport_number = models.CharField(max_length=80, blank=True)
    registration_number = models.CharField(max_length=80, blank=True)
    gender = models.CharField(max_length=20, choices=GenderChoices.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    membership_type = models.CharField(
        max_length=30,
        choices=MembershipTypeChoices.choices,
        default=MembershipTypeChoices.INDIVIDUAL,
    )
    address = models.TextField(blank=True)
    occupation = models.CharField(max_length=120, blank=True)
    employer = models.CharField(max_length=160, blank=True)
    next_of_kin_name = models.CharField(max_length=160, blank=True)
    next_of_kin_phone = models.CharField(max_length=40, blank=True)
    next_of_kin_relationship = models.CharField(max_length=80, blank=True)
    profile_photo = CloudinaryField(
        "profile photo",
        folder="fincore/clients/profile-photos",
        transformation={
            "width": 500,
            "height": 500,
            "crop": "fill",
            "gravity": "face",
            "quality": "auto",
            "fetch_format": "auto",
        },
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=ClientStatusChoices.choices,
        default=ClientStatusChoices.ACTIVE,
    )
    kyc_status = models.CharField(
        max_length=20,
        choices=KycStatusChoices.choices,
        default=KycStatusChoices.PENDING,
    )
    kyc_level = models.CharField(
        max_length=20,
        choices=KycLevelChoices.choices,
        blank=True,
    )
    risk_rating = models.CharField(
        max_length=20,
        choices=RiskRatingChoices.choices,
        default=RiskRatingChoices.LOW,
    )
    is_watchlist_flagged = models.BooleanField(default=False)
    verification_comments = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_clients",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
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

    class Meta(TimeStampedModel.Meta):
        indexes = [
            models.Index(fields=["institution", "branch", "status"], name="client_inst_branch_status_idx"),
            models.Index(fields=["kyc_status", "risk_rating"], name="client_kyc_risk_idx"),
            models.Index(fields=["membership_type", "joining_date"], name="client_member_type_join_idx"),
            models.Index(fields=["is_watchlist_flagged"], name="client_watchlist_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.member_number:
            next_value = ClientMemberSequence.next_value_for_branch(self.branch)
            prefix = build_member_number_prefix(self.branch)
            self.member_number = f"{prefix}-{next_value:06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member_number} - {self.first_name} {self.last_name}"


class ClientStatusHistory(TimeStampedModel):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=ClientStatusChoices.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_status_changes",
    )
    reason = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["client", "created_at"], name="cli_stat_cl_cr_idx"),
            models.Index(fields=["to_status", "created_at"], name="cli_stat_st_cr_idx"),
        ]

    def __str__(self):
        return f"{self.client.member_number}: {self.from_status or '-'} -> {self.to_status}"
