from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # API v1
    path("api/v1/", include("api.v1.urls")),

    # API Docs (important for frontend + testing)
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/",
        RedirectView.as_view(pattern_name="schema", permanent=False),
        name="schema-legacy",
    ),
    path(
        "api/docs/",
        RedirectView.as_view(pattern_name="swagger-ui", permanent=False),
        name="swagger-ui-legacy",
    ),
    path(
        "api/me/",
        RedirectView.as_view(pattern_name="me", permanent=False),
        name="me-legacy",
    ),
]

# Serve static/media only in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
