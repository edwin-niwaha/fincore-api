import logging

from django.db import connection
from django.db.utils import OperationalError
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        database_status = "ok"
        response_status = status.HTTP_200_OK

        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except OperationalError:
            logger.exception("FinCore API health check failed because the database is unavailable.")
            database_status = "error"
            response_status = status.HTTP_503_SERVICE_UNAVAILABLE

        return Response(
            {
                "status": "ok" if response_status == status.HTTP_200_OK else "degraded",
                "service": "fincore-api",
                "database": {
                    "status": database_status,
                    "vendor": connection.vendor,
                },
            },
            status=response_status,
        )
