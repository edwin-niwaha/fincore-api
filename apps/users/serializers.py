from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone", "role", "institution", "branch", "password", "is_active"]
        read_only_fields = ["id"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone", "role", "institution", "branch"]
        read_only_fields = ["id", "username", "role", "institution", "branch"]


from django.contrib.auth import authenticate
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = "email"

    def validate(self, attrs):
        identifier = attrs.get("email") or attrs.get("username")
        password = attrs.get("password")
        if not identifier or not password:
            raise serializers.ValidationError({"detail": "Email/username and password are required."})

        user = User.objects.filter(email__iexact=identifier).first() or User.objects.filter(username__iexact=identifier).first()
        if not user:
            raise serializers.ValidationError({"detail": "Invalid login details."})

        authenticated = authenticate(
            request=self.context.get("request"),
            username=user.get_username(),
            password=password,
        )
        if authenticated is None:
            raise serializers.ValidationError({"detail": "Invalid login details."})
        if not authenticated.is_active:
            raise serializers.ValidationError({"detail": "User account is disabled."})

        refresh = self.get_token(authenticated)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": ProfileSerializer(authenticated).data,
        }
