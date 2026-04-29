from datetime import timedelta
import hashlib
import hmac
import secrets

from cloudinary.models import CloudinaryField
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        if not username:
            raise ValueError("Username is required.")

        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=username, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", CustomUser.Role.SUPER_ADMIN)
        extra_fields.setdefault("user_type", CustomUser.UserType.ADMIN)
        extra_fields.setdefault("is_email_verified", True)

        if extra_fields["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, username, password, **extra_fields)


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        INSTITUTION_ADMIN = "institution_admin", "Institution Admin"
        BRANCH_MANAGER = "branch_manager", "Branch Manager"
        LOAN_OFFICER = "loan_officer", "Loan Officer"
        ACCOUNTANT = "accountant", "Accountant"
        TELLER = "teller", "Teller/Cashier"
        CLIENT = "client", "Client/Self-service user"

    class UserType(models.TextChoices):
        USER = "USER", _("User")
        ADMIN = "ADMIN", _("Admin")

    email = models.EmailField(unique=True, db_index=True)
    role = models.CharField(
        max_length=40,
        choices=Role.choices,
        default=Role.CLIENT,
        db_index=True,
    )
    institution = models.ForeignKey(
        "institutions.Institution",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )
    branch = models.ForeignKey(
        "institutions.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )
    phone = models.CharField(max_length=40, blank=True)

    avatar = CloudinaryField(
        "avatar",
        folder="fincore/users/avatars",
        transformation={
            "width": 300,
            "height": 300,
            "crop": "fill",
            "gravity": "face",
            "quality": "auto",
            "fetch_format": "auto",
        },
        blank=True,
        null=True,
    )

    user_type = models.CharField(
        max_length=10,
        choices=UserType.choices,
        default=UserType.USER,
        db_index=True,
    )
    is_email_verified = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = CustomUserManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "User"
        verbose_name_plural = "Users"
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role"]),
            models.Index(fields=["user_type"]),
            models.Index(fields=["institution", "branch"]),
            models.Index(fields=["is_email_verified"]),
            models.Index(fields=["created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email).lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    @property
    def is_staff_user(self):
        return self.role != self.Role.CLIENT


class EmailOTP(models.Model):
    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "VERIFY_EMAIL", _("Verify Email")
        RESET_PASSWORD = "RESET_PASSWORD", _("Reset Password")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_otps",
    )
    email = models.EmailField(db_index=True)
    purpose = models.CharField(
        max_length=30,
        choices=Purpose.choices,
        db_index=True,
    )
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(blank=True, null=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email OTP"
        verbose_name_plural = "Email OTPs"
        indexes = [
            models.Index(fields=["email", "purpose"]),
            models.Index(fields=["user", "purpose"]),
            models.Index(fields=["expires_at"]),
        ]

    @staticmethod
    def generate_code(length=6) -> str:
        digits = "0123456789"
        return "".join(secrets.choice(digits) for _ in range(length))

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @classmethod
    def create_otp(cls, *, user, email: str, purpose: str, ttl_minutes: int = 10):
        raw_code = cls.generate_code()
        otp = cls.objects.create(
            user=user,
            email=email,
            purpose=purpose,
            code_hash=cls.hash_code(raw_code),
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )
        return otp, raw_code

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def is_used(self) -> bool:
        return self.used_at is not None

    def can_attempt(self) -> bool:
        return self.attempts < self.max_attempts

    def verify_code(self, raw_code: str) -> bool:
        incoming_hash = self.hash_code(raw_code)
        return hmac.compare_digest(self.code_hash, incoming_hash)