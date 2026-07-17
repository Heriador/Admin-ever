from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.api import (
    CapabilityViewSet,
    LoginView,
    MeView,
    RefreshView,
    RoleViewSet,
    UserViewSet,
)
from contracts.api import ContractViewSet
from organizations.api import ClientViewSet, HeadquartersViewSet, PartnerViewSet

router = DefaultRouter()
router.register("clients", ClientViewSet, basename="client")
router.register("partners", PartnerViewSet, basename="partner")
router.register("headquarters", HeadquartersViewSet, basename="headquarters")
router.register("contracts", ContractViewSet, basename="contract")
router.register("users", UserViewSet, basename="user")
router.register("roles", RoleViewSet, basename="role")
router.register("capabilities", CapabilityViewSet, basename="capability")

urlpatterns = [
    # Staff-only escape hatch for data inspection; the product UI is the
    # custom frontend built against /api/v1/.
    path("admin/", admin.site.urls),
    # API v1
    path("api/v1/auth/login/", LoginView.as_view(), name="auth-login"),
    path("api/v1/auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("api/v1/me/", MeView.as_view(), name="me"),
    path("api/v1/", include(router.urls)),
    # OpenAPI contract for the custom UI / desktop app teams
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
