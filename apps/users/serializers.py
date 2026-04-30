from django.contrib.auth import get_user_model, password_validation
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .access import (
    can_manage_role,
    infer_user_type,
    role_requires_branch,
    role_requires_institution,
)
from .services import authenticate_user, normalize_email, register_user

User = get_user_model()


class UserReadSerializerMixin(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    institution_name = serializers.CharField(source="institution.name", read_only=True)
    institution_code = serializers.CharField(source="institution.code", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    profile_type = serializers.SerializerMethodField()
    linked_client_id = serializers.UUIDField(source="client_profile.id", read_only=True)
    linked_client_member_number = serializers.CharField(
        source="client_profile.member_number",
        read_only=True,
    )

    def get_avatar_url(self, obj):
        if not getattr(obj, "avatar", None):
            return None
        try:
            return obj.avatar.url
        except Exception:
            return None

    def get_full_name(self, obj):
        full_name = obj.get_full_name().strip()
        if full_name:
            return full_name
        return obj.username or obj.email

    def get_profile_type(self, obj):
        if getattr(obj, "client_profile", None):
            return "client"
        if getattr(obj, "is_staff_user", False):
            return "staff"
        return "user"


class UserSerializer(UserReadSerializerMixin):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "avatar_url",
            "role",
            "role_display",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "profile_type",
            "linked_client_id",
            "linked_client_member_number",
            "is_active",
            "is_email_verified",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class UserAdminSerializer(UserReadSerializerMixin):
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "avatar_url",
            "role",
            "role_display",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "profile_type",
            "linked_client_id",
            "linked_client_member_number",
            "is_active",
            "is_email_verified",
            "password",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "full_name",
            "avatar_url",
            "role_display",
            "institution_name",
            "institution_code",
            "branch_name",
            "branch_code",
            "created_at",
            "updated_at",
            "is_email_verified",
        )

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
        if not username:
            raise serializers.ValidationError("Username is required.")
        qs = User.objects.filter(username__iexact=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return username

    def validate(self, attrs):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        role = attrs.get("role") or getattr(self.instance, "role", User.Role.CLIENT)
        institution = attrs.get("institution", getattr(self.instance, "institution", None))
        branch = attrs.get("branch", getattr(self.instance, "branch", None))

        if actor and actor.is_authenticated and not can_manage_role(actor, role):
            raise PermissionDenied("You cannot assign that role.")

        if branch and not institution:
            institution = branch.institution
            attrs["institution"] = institution

        actor_role = getattr(actor, "role", None)
        if actor and actor.is_authenticated and actor_role == User.Role.INSTITUTION_ADMIN:
            if not actor.institution_id:
                raise PermissionDenied("Your account is not assigned to an institution.")

            if role_requires_institution(role) and not institution:
                institution = actor.institution
                attrs["institution"] = institution
            elif institution and institution.pk != actor.institution_id:
                raise PermissionDenied("You can only manage users in your institution.")

            if branch and branch.institution_id != actor.institution_id:
                raise PermissionDenied("You can only assign branches in your institution.")

        if actor and actor.is_authenticated and actor_role == User.Role.BRANCH_MANAGER:
            if not actor.institution_id or not actor.branch_id:
                raise PermissionDenied("Your account is not assigned to a branch.")

            if role_requires_institution(role) and not institution:
                institution = actor.institution
                attrs["institution"] = institution
            elif institution and institution.pk != actor.institution_id:
                raise PermissionDenied("You can only manage users in your institution.")

            if not branch:
                branch = actor.branch
                attrs["branch"] = branch
            elif branch.pk != actor.branch_id:
                raise PermissionDenied("You can only manage users in your branch.")

        if role == User.Role.SUPER_ADMIN:
            attrs["institution"] = None
            attrs["branch"] = None
            return attrs

        if role == User.Role.INSTITUTION_ADMIN:
            attrs["branch"] = None
            branch = None

        if role_requires_institution(role) and not institution:
            raise serializers.ValidationError(
                {"institution": ["Institution is required for this role."]}
            )

        if role_requires_branch(role) and not branch:
            raise serializers.ValidationError(
                {"branch": ["Branch is required for this role."]}
            )

        if branch and institution and branch.institution_id != institution.id:
            raise serializers.ValidationError(
                {"branch": ["Selected branch does not belong to the chosen institution."]}
            )

        return attrs

    def _apply_role_defaults(self, user):
        user.user_type = infer_user_type(user.role)
        return user

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            password_validation.validate_password(password, user)
            user.set_password(password)
        else:
            user.set_unusable_password()
        self._apply_role_defaults(user)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if password:
            password_validation.validate_password(password, instance)
            instance.set_password(password)

        self._apply_role_defaults(instance)
        instance.save()
        return instance


class ProfileSerializer(UserReadSerializerMixin):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "avatar",
            "avatar_url",
            "role",
            "role_display",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "profile_type",
            "linked_client_id",
            "linked_client_member_number",
            "is_email_verified",
        )
        read_only_fields = (
            "id",
            "email",
            "role",
            "role_display",
            "institution",
            "institution_name",
            "institution_code",
            "branch",
            "branch_name",
            "branch_code",
            "profile_type",
            "linked_client_id",
            "linked_client_member_number",
            "is_email_verified",
            "avatar_url",
            "full_name",
        )

    def validate_username(self, value):
        username = value.strip()
        if not username:
            raise serializers.ValidationError("Username is required.")
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
    new_password_confirm = serializers.CharField(
        write_only=True,
        min_length=8,
        trim_whitespace=False,
    )

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
