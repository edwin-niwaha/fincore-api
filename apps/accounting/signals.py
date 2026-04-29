from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.institutions.models import Institution

from .services import ChartOfAccountsService


@receiver(post_save, sender=Institution)
def ensure_default_chart_of_accounts(sender, instance, created, **kwargs):
    if created:
        ChartOfAccountsService.ensure_default_accounts(instance)
