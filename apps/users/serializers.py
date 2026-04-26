from django.contrib.auth import get_user_model, password_validation
from django.db import transaction
from rest_framework import serializers

from .services import authenticate_user, normalize_email, register_user

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "phone",
            "avatar_url",
            "role",
            "institution",
            "branch",
            "is_active",
            "is_email_verified",
            "created_at",
        )
        read_only_fields = fields

    def get_avatar_url(self, obj):
        if not getattr(obj, "avatar", None):
            return None
        try:
            return obj.avatar.url
        except Exception:
            return None


class UserAdminSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "phone",
            "role",
            "institution",
            "branch",
            "is_active",
            "is_email_verified",
            "password",
            "created_at",
        )
        read_only_fields = ("id", "created_at", "is_email_verified")

    def validate_email(self, value):
        email = normalize_email(value)
        qs = User.objects.filter(email__iexact=email)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_username(self, value):
        username = value.strip()
        qs = User.objects.filter(username__iexact=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return username

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            password_validation.validate_password(password, user)
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if password:
            password_validation.validate_password(password, instance)
            instance.set_password(password)

        instance.save()
        return instance


class ProfileSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "phone",
            "avatar",
            "avatar_url",
            "role",
            "institution",
            "branch",
            "is_email_verified",
        )
        read_only_fields = (
            "id",
            "email",
            "role",
            "institution",
            "branch",
            "is_email_verified",
            "avatar_url",
        )

    def get_avatar_url(self, obj):
        if not getattr(obj, "avatar", None):
            return None
        try:
            return obj.avatar.url
        except Exception:
            return None

    def validate_username(self, value):
        username = value.strip()
        qs = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return username


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate_email(self, value):
        email = normalize_email(value)
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_username(self, value):
        username = value.strip()
        if not username:
            raise serializers.ValidationError("Username is required.")
        if User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError("This username is already taken.")
        return username

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        password_validation.validate_password(attrs["password"])
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("password_confirm", None)
        return register_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        return normalize_email(value)

    def validate(self, attrs):
        result = authenticate_user(
            email=attrs["email"],
            password=attrs["password"],
            request=self.context.get("request"),
        )
        attrs["user"] = result.user
        attrs["tokens"] = result.tokens
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(trim_whitespace=True)

    def validate_refresh(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Refresh token is required.")
        return value


class GoogleLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(trim_whitespace=True)

    def validate_access_token(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Access token is required.")
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return normalize_email(value)


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6, min_length=6, trim_whitespace=True)
    password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate_email(self, value):
        return normalize_email(value)

    def validate_code(self, value):
        code = value.strip()
        if not code.isdigit():
            raise serializers.ValidationError("Code must contain only digits.")
        return code

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        password_validation.validate_password(attrs["password"])
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords do not match."}
            )
        password_validation.validate_password(attrs["new_password"])
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6, min_length=6, trim_whitespace=True)

    def validate_code(self, value):
        code = value.strip()
        if not code.isdigit():
            raise serializers.ValidationError("Code must contain only digits.")
        return code