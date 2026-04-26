from rest_framework import serializers
from .models import JournalEntry, JournalEntryLine, LedgerAccount

class LedgerAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerAccount
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

class JournalEntryLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntryLine
        fields = ["id", "account", "debit", "credit"]

class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalEntryLineSerializer(many=True)

    class Meta:
        model = JournalEntry
        fields = ["id", "institution", "branch", "reference", "description", "posted_by", "posted_at", "lines"]
        read_only_fields = ["id", "posted_by", "posted_at"]

    def create(self, validated_data):
        from .services import JournalService
        lines = validated_data.pop("lines")
        request = self.context.get("request")
        return JournalService.post_entry(lines=lines, posted_by=getattr(request, "user", None), **validated_data)
