from datetime import timedelta

import jwt as pyjwt
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, UserType
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

    def test_me_requires_authentication(self):
        response = self.api.get(reverse("me"))
        self.assertEqual(response.status_code, 401)
