from datetime import timedelta

import jwt as pyjwt
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Capability, Role, UserType
from accounts.permissions import require_capabilities
from contracts.models import ContractStatus

from .factories import make_client, make_contract, make_headquarters, make_user

PASSWORD = "test-password-123"


class LoginTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.client_org = make_client()
        self.contract = make_contract(self.client_org)
        self.user = make_user(
            client=self.client_org, roles=[Role.Codes.CLIENT_ADMIN, Role.Codes.CLIENT_USER]
        )

    def login(self, username=None):
        return self.api.post(
            reverse("auth-login"),
            {"username": username or self.user.username, "password": PASSWORD},
        )

    def test_login_returns_tokens_with_role_claims(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        claims = pyjwt.decode(
            response.data["access"], options={"verify_signature": False}
        )
        self.assertEqual(claims["user_type"], UserType.CLIENT)
        self.assertCountEqual(
            claims["roles"], [Role.Codes.CLIENT_ADMIN, Role.Codes.CLIENT_USER]
        )
        # CLIENT_ADMIN's bundle, resolved to capability codes.
        self.assertIn(Capability.Codes.USERS_MANAGE, claims["capabilities"])
        self.assertNotIn(Capability.Codes.CLIENTS_MANAGE, claims["capabilities"])

    def test_login_rejected_when_contract_expired(self):
        self.contract.status = ContractStatus.EXPIRED
        self.contract.save()
        response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"].code, "access_revoked")

    def test_login_rejected_with_wrong_password(self):
        response = self.api.post(
            reverse("auth-login"), {"username": self.user.username, "password": "nope"}
        )
        self.assertEqual(response.status_code, 401)

    def test_refresh_rejected_after_contract_expires(self):
        refresh_token = self.login().data["refresh"]
        # Contract lapses between login and refresh.
        self.contract.end_date = timezone.now().date() - timedelta(days=1)
        self.contract.save()
        response = self.api.post(reverse("auth-refresh"), {"refresh": refresh_token})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"].code, "access_revoked")

    def test_refresh_succeeds_while_contract_valid(self):
        refresh_token = self.login().data["refresh"]
        response = self.api.post(reverse("auth-refresh"), {"refresh": refresh_token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)


class MeTests(TestCase):
    def setUp(self):
        self.api = APIClient()

    def authenticate(self, user):
        self.api.force_authenticate(user)

    def test_me_returns_roles_scope_and_headquarters(self):
        client_org = make_client("Acme")
        make_contract(client_org)
        hq = make_headquarters(client_org, "Main office")
        user = make_user(client=client_org, roles=[Role.Codes.CLIENT_USER])
        hq.members.add(user)

        self.authenticate(user)
        response = self.api.get(reverse("me"))

        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["user_type"], UserType.CLIENT)
        self.assertEqual(data["roles"], [Role.Codes.CLIENT_USER])
        self.assertEqual(data["client"], {"id": client_org.id, "name": "Acme"})
        self.assertIsNone(data["partner"])
        self.assertEqual(data["scoped_client_ids"], [client_org.id])
        self.assertEqual(
            data["headquarters"],
            [{"id": hq.id, "name": "Main office", "client_id": client_org.id}],
        )

    def test_me_reflects_custom_role_capabilities(self):
        client_org = make_client()
        make_contract(client_org)
        # A custom role defined at runtime — the desktop app knows
        # nothing about its name, only the capability codes it grants.
        custom = Role.objects.create(code="HQ_COORDINATOR", name="HQ coordinator")
        custom.capabilities.set(
            Capability.objects.filter(code=Capability.Codes.HEADQUARTERS_READ)
        )
        user = make_user(client=client_org)
        user.roles.add(custom)

        self.authenticate(user)
        data = self.api.get(reverse("me")).data

        self.assertEqual(data["roles"], ["HQ_COORDINATOR"])
        self.assertEqual(data["capabilities"], [Capability.Codes.HEADQUARTERS_READ])

    def test_me_requires_authentication(self):
        response = self.api.get(reverse("me"))
        self.assertEqual(response.status_code, 401)


class RequireCapabilitiesTests(TestCase):
    """Unit coverage for the permission class Phase 4 endpoints will use."""

    def setUp(self):
        from rest_framework.test import APIRequestFactory

        self.factory = APIRequestFactory()
        self.permission_class = require_capabilities(
            read=Capability.Codes.CLIENTS_READ,
            write=Capability.Codes.CLIENTS_MANAGE,
        )

    def check(self, user, method):
        request = getattr(self.factory, method)("/fake/")
        request.user = user
        return self.permission_class().has_permission(request, view=None)

    def test_viewer_can_read_but_not_write(self):
        viewer = make_user(UserType.PLATFORM, roles=[Role.Codes.PLATFORM_VIEWER])
        self.assertTrue(self.check(viewer, "get"))
        self.assertFalse(self.check(viewer, "post"))

    def test_super_admin_can_write(self):
        admin = make_user(UserType.PLATFORM, roles=[Role.Codes.SUPER_ADMIN])
        self.assertTrue(self.check(admin, "post"))

    def test_user_without_capability_cannot_read(self):
        user = make_user(client=make_client())  # no roles at all
        self.assertFalse(self.check(user, "get"))

    def test_read_only_endpoint_denies_writes_for_everyone(self):
        read_only = require_capabilities(read=Capability.Codes.CLIENTS_READ)
        admin = make_user(UserType.PLATFORM, roles=[Role.Codes.SUPER_ADMIN])
        request = self.factory.post("/fake/")
        request.user = admin
        self.assertFalse(read_only().has_permission(request, view=None))
