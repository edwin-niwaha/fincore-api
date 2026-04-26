from decimal import Decimal
from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import JournalEntry, JournalEntryLine

class JournalService:
    @staticmethod
    @transaction.atomic
    def post_entry(*, institution, branch=None, reference, description, lines, posted_by=None):
        total_debit = sum(Decimal(str(line.get("debit", "0"))) for line in lines)
        total_credit = sum(Decimal(str(line.get("credit", "0"))) for line in lines)
        if total_debit <= 0 or total_debit != total_credit:
            raise ValidationError("Journal entry must balance and have positive amounts.")
        entry = JournalEntry.objects.create(
            institution=institution, branch=branch, reference=reference, description=description, posted_by=posted_by
        )
        for line in lines:
            JournalEntryLine.objects.create(journal_entry=entry, **line)
        return entry
