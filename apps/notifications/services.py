from django.contrib.auth import get_user_model

from apps.clients.models import Client

from .models import Notification

User = get_user_model()


class NotificationService:
    @staticmethod
    def notify_user(*, user, title, message, category="", data=None):
        if not user:
            return None

        return Notification.objects.create(
            user=user,
            title=title.strip(),
            message=message.strip(),
            category=category.strip(),
            data=data or {},
        )

    @classmethod
    def notify_client(cls, *, client, title, message, category="", data=None):
        if not isinstance(client, Client) or not client.user_id:
            return None

        return cls.notify_user(
            user=client.user,
            title=title,
            message=message,
            category=category,
            data=data,
        )

    @classmethod
    def notify_branch_roles(
        cls,
        *,
        branch,
        roles,
        title,
        message,
        category="",
        data=None,
        exclude_user_id=None,
    ):
        queryset = User.objects.filter(
            branch=branch,
            role__in=roles,
            is_active=True,
        )
        if exclude_user_id:
            queryset = queryset.exclude(pk=exclude_user_id)

        return [
            cls.notify_user(
                user=user,
                title=title,
                message=message,
                category=category,
                data=data,
            )
            for user in queryset
        ]
