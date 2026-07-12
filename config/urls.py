from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.api import LoginView, MeView, RefreshView

urlpatterns = [
    # Staff-only escape hatch for data inspection; the product UI is the
    # custom frontend built against /api/v1/.
    path("admin/", admin.site.urls),
    # API v1
    path("api/v1/auth/login/", LoginView.as_view(), name="auth-login"),
    path("api/v1/auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("api/v1/me/", MeView.as_view(), name="me"),
    # OpenAPI contract for the custom UI / desktop app teams
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
