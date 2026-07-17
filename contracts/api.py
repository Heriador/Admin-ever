"""CRUD API for contracts.

Contracts drive access, so they keep history: only DRAFT contracts can
be deleted. Anything that has been ACTIVE is closed by status
(EXPIRED / TERMINATED), never removed.
"""

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from accounts.models import Capability
from accounts.permissions import require_capabilities
from organizations.api import ScopedClientField

from .models import Contract, ContractStatus


class ContractSerializer(serializers.ModelSerializer):
    client = ScopedClientField()
    is_currently_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Contract
        fields = [
            "id", "client", "reference", "status", "start_date", "end_date",
            "notes", "is_currently_valid", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise ValidationError({"end_date": "End date cannot be before start date."})
        return attrs


class ContractViewSet(viewsets.ModelViewSet):
    serializer_class = ContractSerializer
    permission_classes = [
        require_capabilities(
            read=Capability.Codes.CONTRACTS_READ,
            write=Capability.Codes.CONTRACTS_MANAGE,
        )
    ]

    def get_queryset(self):
        return Contract.objects.visible_to(self.request.user).select_related("client")

    def perform_destroy(self, instance):
        if instance.status != ContractStatus.DRAFT:
            raise ValidationError(
                {"detail": "Only DRAFT contracts can be deleted; close others by status."}
            )
        instance.delete()
