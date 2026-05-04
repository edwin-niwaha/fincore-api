import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.services import AuditService

from .access import is_user_manager, scope_user_queryset
from .models import EmailOTP
from .serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    LogoutSerializer,
    ProfileSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserAdminSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from .services import (
    authenticate_with_google,
    ensure_resend_allowed,
    get_latest_active_otp,
    issue_email_otp,
    send_password_reset_email,
    send_verification_email,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class AuthAnonThrottle(AnonRateThrottle):
    scope = "auth_anon"


class AuthUserThrottle(UserRateThrottle):
    scope = "auth_user"


class IsUserManager(permissions.BasePermission):
    def has_permission(self, request, view):
        return is_user_manager(request.user)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserAdminSerializer
    permission_classes = [permissions.IsAuthenticated, IsUserManager]
    authentication_classes = [JWTAuthentication]
    filterset_fields = ["role", "institution", "branch", "is_active", "is_email_verified"]
    search_fields = [
        "email",
        "username",
        "first_name",
        "last_name",
        "phone",
        "institution__name",
        "branch__name",
    ]
    ordering_fields = ["created_at", "email", "username", "role"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = User.objects.select_related("institution", "branch").order_by("-created_at")
        return scope_user_queryset(queryset, self.request.user)

    def perform_create(self, serializer):
        target_user = serializer.save()
        AuditService.log(
            user=self.request.user,
            request=self.request,
            action="users.account.create",
            target=str(target_user.id),
            institution=target_user.institution,
            branch=target_user.branch,
            metadata={
                "email": target_user.email,
                "username": target_user.username,
                "role": target_user.role,
                "is_active": target_user.is_active,
            },
        )

    def perform_update(self, serializer):
        target_user = serializer.instance

        if target_user == self.request.user:
            protected_fields = {"role", "institution", "branch", "is_active"}
            changed_fields = protected_fields.intersection(serializer.validated_data.keys())
            if changed_fields:
                raise ValidationError(
                    {
                        "detail": (
                            "Use the profile endpoint for your own profile. "
                            "Role, assignment, and activation cannot be changed here."
                        )
                    }
                )

        target_user = serializer.save()
        AuditService.log(
            user=self.request.user,
            request=self.request,
            action="users.account.update",
            target=str(target_user.id),
            institution=target_user.institution,
            branch=target_user.branch,
            metadata={
                "email": target_user.email,
                "username": target_user.username,
                "role": target_user.role,
                "is_active": target_user.is_active,
            },
        )

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise ValidationError({"detail": "You cannot delete your own account."})

        target_id = str(instance.id)
        email = instance.email
        role = instance.role
        institution = instance.institution
        branch = instance.branch
        instance.delete()
        AuditService.log(
            user=self.request.user,
            request=self.request,
            action="users.account.delete",
            target=target_id,
            institution=institution,
            branch=branch,
            metadata={
                "email": email,
                "role": role,
            },
        )


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAnonThrottle]

    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        tokens = self._issue_tokens(user)

        _, raw_code = issue_email_otp(
            user=user,
            purpose=EmailOTP.Purpose.VERIFY_EMAIL,
        )
        send_verification_email(user=user, code=raw_code)

        return Response(
            {
                "user": UserSerializer(user, context={"request": request}).data,
                "tokens": tokens,
                "detail": "Registration successful. Verification code sent to email.",
            },
            status=status.HTTP_201_CREATED,
        )

    def _issue_tokens(self, user):
        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAnonThrottle]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        tokens = serializer.validated_data["tokens"]

        AuditService.log(
            user=user,
            request=request,
            action="auth.login.success",
            target=str(user.id),
            metadata={
                "email": user.email,
                "role": user.role,
            },
        )

        return Response(
            {
                "user": UserSerializer(user, context={"request": request}).data,
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [AuthUserThrottle]

    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except Exception as exc:
            raise ValidationError({"refresh": "Invalid or expired refresh token."}) from exc

        AuditService.log(
            user=request.user,
            request=request,
            action="auth.logout.success",
            target=str(request.user.id),
            metadata={
                "email": request.user.email,
                "role": request.user.role,
            },
        )

        return Response({"detail": "Logout successful."}, status=status.HTTP_200_OK)


class MeView(RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    serializer_class = ProfileSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        return Response(
            UserSerializer(request.user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        logger.info("Updated FinCore profile user_id=%s", request.user.id)
        AuditService.log(
            user=request.user,
            request=request,
            action="auth.profile.update",
            target=str(request.user.id),
            metadata={
                "email": request.user.email,
                "role": request.user.role,
            },
        )

        return Response(
            UserSerializer(request.user, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class GoogleLoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAnonThrottle]

    def post(self, request, *args, **kwargs):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = authenticate_with_google(
            access_token=serializer.validated_data["access_token"],
            request=request,
        )

        return Response(
            {
                "user": UserSerializer(result.user, context={"request": request}).data,
                "tokens": result.tokens,
            },
            status=status.HTTP_200_OK,
        )


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAnonThrottle]

    def post(self, request, *args, **kwargs):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if user and ensure_resend_allowed(
            user=user,
            purpose=EmailOTP.Purpose.RESET_PASSWORD,
        ):
            _, raw_code = issue_email_otp(
                user=user,
                purpose=EmailOTP.Purpose.RESET_PASSWORD,
            )
            send_password_reset_email(user=user, code=raw_code)

        return Response(
            {"detail": "If an account exists with that email, a reset code has been sent."},
            status=status.HTTP_200_OK,
        )


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthAnonThrottle]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        code = serializer.validated_data["code"]
        new_password = serializer.validated_data["password"]

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            raise ValidationError({"detail": "Invalid or expired code."})

        otp = get_latest_active_otp(
            user=user,
            purpose=EmailOTP.Purpose.RESET_PASSWORD,
        )

        if not otp or otp.is_used() or otp.is_expired() or not otp.can_attempt():
            raise ValidationError({"detail": "Invalid or expired code."})

        otp.attempts += 1
        otp.save(update_fields=["attempts"])

        if not otp.verify_code(code):
            raise ValidationError({"detail": "Invalid or expired code."})

        otp.used_at = timezone.now()
        otp.save(update_fields=["used_at"])

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {"detail": "Password reset successful."},
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [AuthUserThrottle]

    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        current_password = serializer.validated_data["current_password"]
        new_password = serializer.validated_data["new_password"]

        if not user.check_password(current_password):
            raise ValidationError({"current_password": ["Current password is incorrect."]})

        if current_password == new_password:
            raise ValidationError(
                {"new_password": ["New password must be different from current password."]}
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        AuditService.log(
            user=user,
            request=request,
            action="auth.password.change",
            target=str(user.id),
            metadata={
                "email": user.email,
                "role": user.role,
            },
        )

        return Response(
            {"detail": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


class SendEmailVerificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [AuthUserThrottle]

    def post(self, request, *args, **kwargs):
        user = request.user

        if user.is_email_verified:
            return Response(
                {"detail": "Email already verified."},
                status=status.HTTP_200_OK,
            )

        if not ensure_resend_allowed(user=user, purpose=EmailOTP.Purpose.VERIFY_EMAIL):
            raise Throttled(detail="Please wait before requesting another code.")

        _, raw_code = issue_email_otp(
            user=user,
            purpose=EmailOTP.Purpose.VERIFY_EMAIL,
        )
        send_verification_email(user=user, code=raw_code)

        return Response(
            {"detail": "Verification code sent."},
            status=status.HTTP_200_OK,
        )


class VerifyEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [AuthUserThrottle]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        code = serializer.validated_data["code"]

        if user.is_email_verified:
            return Response(
                {"detail": "Email already verified."},
                status=status.HTTP_200_OK,
            )

        otp = get_latest_active_otp(user=user, purpose=EmailOTP.Purpose.VERIFY_EMAIL)

        if not otp or otp.is_used() or otp.is_expired() or not otp.can_attempt():
            raise ValidationError({"detail": "Invalid or expired code."})

        otp.attempts += 1
        otp.save(update_fields=["attempts"])

        if not otp.verify_code(code):
            raise ValidationError({"detail": "Invalid or expired code."})

        otp.used_at = timezone.now()
        otp.save(update_fields=["used_at"])

        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])

        return Response(
            {
                "detail": "Email verified successfully.",
                "user": UserSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )
