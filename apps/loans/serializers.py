from rest_framework import serializers
from .models import LoanApplication, LoanProduct, LoanRepayment, RepaymentSchedule
from .services import LoanService

class LoanProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanProduct
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

class LoanApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = "__all__"
        read_only_fields = ["id", "status", "approved_by", "rejected_reason", "disbursed_at", "principal_balance", "interest_balance", "created_at", "updated_at"]

    def validate(self, attrs):
        product = attrs.get("product") or getattr(self.instance, "product", None)
        amount = attrs.get("amount") or getattr(self.instance, "amount", None)
        term = attrs.get("term_months") or getattr(self.instance, "term_months", None)
        if product and amount and term:
            LoanService.validate_application(product, amount, term)
        return attrs

class RepaymentScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepaymentSchedule
        fields = "__all__"

class LoanRepaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanRepayment
        fields = "__all__"
        read_only_fields = ["id", "principal_component", "interest_component", "received_by", "created_at", "updated_at"]

class LoanActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)

class LoanRepaymentCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(max_length=80)
