"""CRUD API for clients, partners and headquarters.

Every queryset is filtered through the model's visible_to(); every
serializer re-checks that any client referenced in a write is inside
the requester's scope. Clients and partners are never hard-deleted —
lifecycle is driven by Client.status / Partner.is_active.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import Capability
from accounts.permissions import require_capabilities

from .models import Client, Headquarters, HeadquartersAssignment, Partner

User = get_user_model()

# Write methods only — lifecycle instead of deletion.
NO_DELETE = ["get", "post", "put", "patch", "head", "options"]


class ScopedClientField(serializers.PrimaryKeyRelatedField):
    """A client FK that only accepts clients visible to the requester."""

    def get_queryset(self):
        return Client.objects.visible_to(self.context["request"].user)


class ClientSerializer(serializers.ModelSerializer):
    has_active_contract = serializers.BooleanField(read_only=True)

    class Meta:
        model = Client
        fields = [
            "id", "name", "status", "has_active_contract",
            "created_at", "updated_at",
        ]


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    permission_classes = [
        require_capabilities(
            read=Capability.Codes.CLIENTS_READ,
            write=Capability.Codes.CLIENTS_MANAGE,
        )
    ]
    http_method_names = NO_DELETE

    def get_queryset(self):
        return Client.objects.visible_to(self.request.user)


class PartnerSerializer(serializers.ModelSerializer):
    clients = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Client.objects.all(), required=False
    )

    class Meta:
        model = Partner
        fields = ["id", "name", "is_active", "clients", "created_at", "updated_at"]


class PartnerViewSet(viewsets.ModelViewSet):
    serializer_class = PartnerSerializer
    permission_classes = [
        require_capabilities(
            read=Capability.Codes.PARTNERS_READ,
            write=Capability.Codes.PARTNERS_MANAGE,
        )
    ]
    http_method_names = NO_DELETE

    def get_queryset(self):
        return Partner.objects.visible_to(self.request.user)


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]


class HeadquartersSerializer(serializers.ModelSerializer):
    client = ScopedClientField()
    members = MemberSerializer(many=True, read_only=True)

    class Meta:
        model = Headquarters
        fields = [
            "id", "client", "name", "address", "is_active", "members",
            "created_at", "updated_at",
        ]


class AssignmentInputSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class HeadquartersViewSet(viewsets.ModelViewSet):
    serializer_class = HeadquartersSerializer
    permission_classes = [
        require_capabilities(
            read=Capability.Codes.HEADQUARTERS_READ,
            write=Capability.Codes.HEADQUARTERS_MANAGE,
        )
    ]

    def get_queryset(self):
        return Headquarters.objects.visible_to(self.request.user).prefetch_related(
            "members"
        )

    def _get_target_user(self, request):
        serializer = AssignmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = (
            User.objects.visible_to(request.user)
            .filter(pk=serializer.validated_data["user_id"])
            .first()
        )
        if user is None:
            raise serializers.ValidationError({"user_id": "User not found."})
        return user

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        headquarters = self.get_object()
        user = self._get_target_user(request)
        if user.client_id != headquarters.client_id:
            raise serializers.ValidationError(
                {"user_id": "User must belong to the same client as the headquarters."}
            )
        if HeadquartersAssignment.objects.filter(
            headquarters=headquarters, user=user
        ).exists():
            raise serializers.ValidationError(
                {"user_id": "User is already assigned to this headquarters."}
            )
        HeadquartersAssignment.objects.create(headquarters=headquarters, user=user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def unassign(self, request, pk=None):
        headquarters = self.get_object()
        user = self._get_target_user(request)
        deleted, _ = HeadquartersAssignment.objects.filter(
            headquarters=headquarters, user=user
        ).delete()
        if not deleted:
            raise serializers.ValidationError(
                {"user_id": "User is not assigned to this headquarters."}
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
