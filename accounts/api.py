"""Authentication endpoints for the custom admin UI and the desktop app.

Login and refresh both re-check `User.has_active_access()`, so a lapsed
contract revokes a client user's access within one access-token lifetime
without needing a token blocklist.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

User = get_user_model()

ACCESS_REVOKED_DETAIL = "Access revoked: your organization has no active contract."


class ScopedTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["user_type"] = user.user_type
        token["roles"] = user.role_codes()
        # Capabilities, not role names, are the enforceable contract:
        # roles are runtime-editable bundles, so the desktop app must
        # gate features on these codes.
        token["capabilities"] = user.capability_codes()
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.has_active_access():
            raise AuthenticationFailed(ACCESS_REVOKED_DETAIL, code="access_revoked")
        return data


class ScopedTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        incoming = RefreshToken(attrs["refresh"])
        user = User.objects.filter(pk=incoming.get("user_id")).first()
        if user is None or not user.has_active_access():
            raise AuthenticationFailed(ACCESS_REVOKED_DETAIL, code="access_revoked")
        return super().validate(attrs)


class LoginView(TokenObtainPairView):
    serializer_class = ScopedTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    serializer_class = ScopedTokenRefreshSerializer


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.SlugRelatedField(slug_field="code", many=True, read_only=True)
    capabilities = serializers.SerializerMethodField()
    client = serializers.SerializerMethodField()
    partner = serializers.SerializerMethodField()
    scoped_client_ids = serializers.SerializerMethodField()
    headquarters = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "user_type",
            "roles",
            "capabilities",
            "client",
            "partner",
            "scoped_client_ids",
            "headquarters",
        ]

    def get_capabilities(self, user):
        return user.capability_codes()

    def get_client(self, user):
        if user.client_id:
            return {"id": user.client_id, "name": user.client.name}
        return None

    def get_partner(self, user):
        if user.partner_id:
            return {"id": user.partner_id, "name": user.partner.name}
        return None

    def get_scoped_client_ids(self, user):
        return list(user.scoped_clients().values_list("id", flat=True))

    def get_headquarters(self, user):
        return [
            {"id": hq.id, "name": hq.name, "client_id": hq.client_id}
            for hq in user.headquarters.filter(is_active=True)
        ]


class MeView(APIView):
    """Identity, roles and scope for the authenticated user. The desktop
    app and the admin UI both drive their authorization display off this
    payload."""

    def get(self, request):
        return Response(MeSerializer(request.user).data)
