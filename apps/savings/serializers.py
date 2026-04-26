from rest_framework import serializers
from .models import SavingsAccount, SavingsTransaction

class SavingsAccountSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.__str__", read_only=True)
    class Meta:
        model = SavingsAccount
        fields = "__all__"
        read_only_fields = ["id", "account_number", "balance", "created_at", "updated_at"]

class SavingsTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavingsTransaction
        fields = "__all__"
        read_only_fields = ["id", "balance_after", "performed_by", "created_at", "updated_at"]

class SavingsOperationSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(max_length=80)
    notes = serializers.CharField(required=False, allow_blank=True)
