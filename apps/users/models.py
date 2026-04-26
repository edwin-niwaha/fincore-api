from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        INSTITUTION_ADMIN = "institution_admin", "Institution Admin"
        BRANCH_MANAGER = "branch_manager", "Branch Manager"
        LOAN_OFFICER = "loan_officer", "Loan Officer"
        ACCOUNTANT = "accountant", "Accountant"
        TELLER = "teller", "Teller/Cashier"
        CLIENT = "client", "Client/Self-service user"

    role = models.CharField(max_length=40, choices=Role.choices, default=Role.CLIENT)
    institution = models.ForeignKey("institutions.Institution", null=True, blank=True, on_delete=models.SET_NULL)
    branch = models.ForeignKey("institutions.Branch", null=True, blank=True, on_delete=models.SET_NULL)
    phone = models.CharField(max_length=40, blank=True)

    @property
    def is_staff_user(self):
        return self.role != self.Role.CLIENT
