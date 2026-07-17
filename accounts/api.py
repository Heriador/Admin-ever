"""Auth, user, role and capability endpoints.

Login and refresh both re-check `User.has_active_access()`, so a lapsed
contract revokes a client user's access within one access-token lifetime
without needing a token blocklist.

User administration enforces two safety rules on top of capabilities:
- non-platform requesters can only create CLIENT users inside their
  scope, and cannot re-home anyone (user_type/client/partner frozen);
- nobody can grant a role containing capabilities they do not hold
  themselves (no privilege escalation through role assignment).
"""

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, viewsets
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from organizations.api import ScopedClientField

from .models import Capability, Role, UserType
from .permissions import require_capabilities

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


# --- User administration -----------------------------------------------


class UserAdminSerializer(serializers.ModelSerializer):
    client = ScopedClientField(required=False, allow_null=True)
    roles = serializers.SlugRelatedField(
        slug_field="code", queryset=Role.objects.all(), many=True, required=False
    )
    capabilities = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "user_type", "client", "partner", "roles", "capabilities",
            "is_active", "password", "date_joined", "last_login",
        ]
        read_only_fields = ["date_joined", "last_login"]

    def get_capabilities(self, user):
        return user.capability_codes()

    def validate_password(self, value):
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return value

    def validate_roles(self, roles):
        # Anti-escalation: a role is grantable only if every capability
        # it bundles is already held by the requester.
        granted = set(self.context["request"].user.capability_codes())
        for role in roles:
            needed = set(role.capabilities.values_list("code", flat=True))
            if not needed <= granted:
                raise ValidationError(
                    f"Cannot grant role '{role.code}': it includes capabilities "
                    "you do not hold."
                )
        return roles

    def validate(self, attrs):
        requester = self.context["request"].user
        creating = self.instance is None

        if creating and not attrs.get("password"):
            raise ValidationError({"password": "Password is required on creation."})

        if not requester.is_platform:
            # Non-platform requesters: CLIENT users in scope only, and
            # the identity fields of existing users are frozen.
            if creating:
                if attrs.get("user_type", UserType.CLIENT) != UserType.CLIENT:
                    raise ValidationError(
                        {"user_type": "You can only create client users."}
                    )
                attrs["user_type"] = UserType.CLIENT
                if attrs.get("client") is None:
                    raise ValidationError({"client": "This field is required."})
                if attrs.get("partner") is not None:
                    raise ValidationError({"partner": "You cannot assign a partner."})
            else:
                for frozen in ("user_type", "client", "partner"):
                    if frozen in attrs and getattr(self.instance, frozen) != attrs[frozen]:
                        raise ValidationError({frozen: "You cannot change this field."})

        self._validate_organization(attrs)
        return attrs

    def _validate_organization(self, attrs):
        """Mirror the model's type/organization coherence rules so
        violations surface as 400s instead of database errors."""

        def current(field):
            return attrs.get(field, getattr(self.instance, field, None))

        user_type, client, partner = (
            current("user_type"), current("client"), current("partner"),
        )
        if user_type == UserType.PLATFORM and (client or partner):
            raise ValidationError("Platform users cannot belong to a client or partner.")
        if user_type == UserType.PARTNER and (not partner or client):
            raise ValidationError("Partner users must belong to a partner and no client.")
        if user_type == UserType.CLIENT and (not client or partner):
            raise ValidationError("Client users must belong to a client and no partner.")

    def create(self, validated_data):
        roles = validated_data.pop("roles", [])
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        user.roles.set(roles)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserAdminSerializer
    permission_classes = [
        require_capabilities(
            read=Capability.Codes.USERS_READ,
            write=Capability.Codes.USERS_MANAGE,
        )
    ]

    def get_queryset(self):
        return (
            User.objects.visible_to(self.request.user)
            .select_related("client", "partner")
            .prefetch_related("roles__capabilities")
            .order_by("username")
        )

    def perform_destroy(self, instance):
        # Users are never hard-deleted: deactivation preserves history
        # and headquarters assignments.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


# --- Roles & capabilities ------------------------------------------------


class RoleSerializer(serializers.ModelSerializer):
    capabilities = serializers.SlugRelatedField(
        slug_field="code", queryset=Capability.objects.all(), many=True, required=False
    )

    class Meta:
        model = Role
        fields = ["id", "code", "name", "description", "capabilities", "is_system"]
        read_only_fields = ["is_system"]

    def validate_code(self, value):
        if self.instance and self.instance.is_system and value != self.instance.code:
            raise ValidationError("System role codes cannot be changed.")
        return value


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.prefetch_related("capabilities")
    serializer_class = RoleSerializer
    permission_classes = [
        require_capabilities(
            read=Capability.Codes.ROLES_READ,
            write=Capability.Codes.ROLES_MANAGE,
        )
    ]

    def perform_destroy(self, instance):
        if instance.is_system:
            raise ValidationError({"detail": "System roles cannot be deleted."})
        instance.delete()


class CapabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Capability
        fields = ["id", "code", "name", "description"]


class CapabilityViewSet(viewsets.ReadOnlyModelViewSet):
    """The capability catalog. Read-only over the API: backend-enforced
    codes ship with migrations; app-only codes are added via the Django
    admin escape hatch."""

    queryset = Capability.objects.all()
    serializer_class = CapabilitySerializer
    permission_classes = [require_capabilities(read=Capability.Codes.ROLES_READ)]
