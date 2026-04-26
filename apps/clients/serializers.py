from rest_framework import serializers
from .models import Client

class ClientSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = "__all__"
        read_only_fields = ["id", "member_number", "created_at", "updated_at"]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

class ClientSelfServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ["id", "member_number", "first_name", "last_name", "phone", "email", "address", "occupation", "status"]
        read_only_fields = ["id", "member_number", "first_name", "last_name", "status"]
