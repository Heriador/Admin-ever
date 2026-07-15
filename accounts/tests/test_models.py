from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Capability, Role, UserType
from organizations.models import ClientStatus

from .factories import make_client, make_contract, make_partner, make_user


class UserTypeConstraintTests(TestCase):
    def test_platform_user_cannot_have_client(self):
        client = make_client()
        user = make_user(UserType.PLATFORM)
        user.client = client
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_partner_user_requires_partner(self):
        user = make_user(UserType.PARTNER, partner=make_partner())
        user.partner = None
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_client_user_requires_client(self):
        user = make_user(UserType.CLIENT, client=make_client())
        user.client = None
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_client_user_cannot_also_have_partner(self):
        user = make_user(UserType.CLIENT, client=make_client())
        user.partner = make_partner()
        with self.assertRaises(ValidationError):
            user.full_clean()


class ActiveAccessTests(TestCase):
    def test_client_user_with_valid_contract_has_access(self):
        client = make_client()
        make_contract(client)
        self.assertTrue(make_user(client=client).has_active_access())

    def test_client_user_without_contract_is_revoked(self):
        self.assertFalse(make_user(client=make_client()).has_active_access())

    def test_client_user_with_expired_contract_is_revoked(self):
        client = make_client()
        today = timezone.now().date()
        make_contract(
            client, start=today - timedelta(days=60), end=today - timedelta(days=1)
        )
        self.assertFalse(make_user(client=client).has_active_access())

    def test_only_active_client_status_grants_access(self):
        # Every non-ACTIVE status must lock out the client's users, even
        # with a perfectly valid contract in place.
        for status in ClientStatus:
            with self.subTest(status=status):
                client = make_client(status=status)
                make_contract(client)
                user = make_user(client=client)
                self.assertEqual(
                    user.has_active_access(), status == ClientStatus.ACTIVE
                )

    def test_inactive_user_is_revoked(self):
        client = make_client()
        make_contract(client)
        user = make_user(client=client, is_active=False)
        self.assertFalse(user.has_active_access())

    def test_partner_user_keeps_access_when_a_client_contract_lapses(self):
        client = make_client()  # no contract at all
        partner = make_partner(clients=[client])
        user = make_user(UserType.PARTNER, partner=partner)
        self.assertTrue(user.has_active_access())
        # ...but the lapsed client drops out of their actionable scope.
        self.assertEqual(user.scoped_clients().count(), 0)

    def test_platform_user_always_has_access(self):
        self.assertTrue(make_user(UserType.PLATFORM).has_active_access())


class ScopedClientsTests(TestCase):
    def setUp(self):
        self.with_contract = make_client("With contract")
        make_contract(self.with_contract)
        self.without_contract = make_client("Without contract")
        # Contracted clients in every non-ACTIVE status: none may appear
        # in anyone's scope.
        for status in (
            ClientStatus.WAITING,
            ClientStatus.INACTIVE,
            ClientStatus.DEACTIVATED,
        ):
            make_contract(make_client(f"{status} client", status=status))

    def test_platform_scope_is_all_contracted_active_clients(self):
        user = make_user(UserType.PLATFORM)
        self.assertQuerySetEqual(user.scoped_clients(), [self.with_contract])

    def test_partner_scope_is_linked_contracted_clients_only(self):
        other = make_client("Other")
        make_contract(other)
        partner = make_partner(clients=[self.with_contract, self.without_contract])
        user = make_user(UserType.PARTNER, partner=partner)
        self.assertQuerySetEqual(user.scoped_clients(), [self.with_contract])

    def test_client_scope_is_own_client(self):
        user = make_user(client=self.with_contract)
        self.assertQuerySetEqual(user.scoped_clients(), [self.with_contract])


class RoleTests(TestCase):
    def test_roles_are_seeded_by_migration(self):
        self.assertEqual(Role.objects.count(), 6)
        self.assertTrue(Role.objects.filter(code=Role.Codes.SUPER_ADMIN).exists())

    def test_role_codes_helper(self):
        user = make_user(
            UserType.PLATFORM, roles=[Role.Codes.SUPER_ADMIN, Role.Codes.PLATFORM_VIEWER]
        )
        self.assertCountEqual(
            user.role_codes(), [Role.Codes.SUPER_ADMIN, Role.Codes.PLATFORM_VIEWER]
        )


class CapabilityTests(TestCase):
    def test_system_roles_are_flagged_and_bundled(self):
        self.assertEqual(Role.objects.filter(is_system=True).count(), 6)
        super_admin = Role.objects.get(code=Role.Codes.SUPER_ADMIN)
        self.assertEqual(super_admin.capabilities.count(), Capability.objects.count())
        viewer = Role.objects.get(code=Role.Codes.PLATFORM_VIEWER)
        self.assertTrue(
            all(c.code.endswith(".read") for c in viewer.capabilities.all())
        )

    def test_capability_codes_union_across_roles(self):
        custom = Role.objects.create(code="AUDITOR", name="Auditor")
        custom.capabilities.set(
            Capability.objects.filter(
                code__in=[Capability.Codes.CONTRACTS_READ, Capability.Codes.CLIENTS_READ]
            )
        )
        user = make_user(UserType.PLATFORM, roles=[Role.Codes.PLATFORM_VIEWER])
        user.roles.add(custom)
        codes = user.capability_codes()
        # Union, deduplicated: clients.read appears in both roles.
        self.assertEqual(codes.count(Capability.Codes.CLIENTS_READ), 1)
        self.assertIn(Capability.Codes.CONTRACTS_READ, codes)
        self.assertNotIn(Capability.Codes.CLIENTS_MANAGE, codes)

    def test_has_capability(self):
        user = make_user(UserType.PLATFORM, roles=[Role.Codes.PLATFORM_VIEWER])
        self.assertTrue(user.has_capability(Capability.Codes.CLIENTS_READ))
        self.assertFalse(user.has_capability(Capability.Codes.CLIENTS_MANAGE))

    def test_user_without_roles_has_no_capabilities(self):
        user = make_user(client=make_client())
        self.assertEqual(user.capability_codes(), [])

    def test_system_role_cannot_be_deleted(self):
        role = Role.objects.get(code=Role.Codes.SUPER_ADMIN)
        with self.assertRaises(ValidationError):
            role.delete()

    def test_custom_role_can_be_deleted(self):
        custom = Role.objects.create(code="TEMP", name="Temp")
        custom.delete()
        self.assertFalse(Role.objects.filter(code="TEMP").exists())
