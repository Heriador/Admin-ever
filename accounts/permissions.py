"""Capability-based DRF permissions.

Authorization is always checked against capability codes, never role
names — roles are runtime-editable bundles, so their names carry no
enforceable meaning. Typical Phase 4 usage:

    class ClientViewSet(...):
        permission_classes = [
            require_capabilities(
                read=Capability.Codes.CLIENTS_READ,
                write=Capability.Codes.CLIENTS_MANAGE,
            )
        ]

Scope (which clients the action may touch) is a separate axis,
enforced by filtering querysets through Client.objects.visible_to().
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


def require_capabilities(read, write=None):
    """Permission class requiring `read` for safe methods and `write`
    for mutating ones. `write=None` makes the endpoint read-only for
    everyone (writes are always denied rather than falling open)."""

    class _HasCapability(BasePermission):
        message = "You do not have the capability required for this action."

        def has_permission(self, request, view):
            user = request.user
            if not user or not user.is_authenticated:
                return False
            required = read if request.method in SAFE_METHODS else write
            return bool(required) and user.has_capability(required)

    return _HasCapability
