from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import UserType
from accounts.tests.factories import (
    make_client,
    make_headquarters,
    make_partner,
    make_user,
)
from organizations.models import Client, HeadquartersAssignment


class ClientVisibilityTests(TestCase):
    def setUp(self):
        self.client_a = make_client("A")
        self.client_b = make_client("B")
        self.client_c = make_client("C")
        self.partner = make_partner(clients=[self.client_a, self.client_b])

    def test_platform_user_sees_all_clients(self):
        user = make_user(UserType.PLATFORM)
        self.assertEqual(Client.objects.visible_to(user).count(), 3)

    def test_partner_user_sees_only_linked_clients(self):
        user = make_user(UserType.PARTNER, partner=self.partner)
        self.assertQuerySetEqual(
            Client.objects.visible_to(user), [self.client_a, self.client_b]
        )

    def test_client_user_sees_only_own_client(self):
        user = make_user(client=self.client_c)
        self.assertQuerySetEqual(Client.objects.visible_to(user), [self.client_c])

    def test_partner_user_without_partner_link_sees_nothing(self):
        # Defensive: a partner-type user whose FK was cleared must not
        # fall through to a wider scope.
        user = make_user(UserType.PARTNER, partner=self.partner)
        user.partner_id = None
        self.assertEqual(Client.objects.visible_to(user).count(), 0)


class HeadquartersAssignmentTests(TestCase):
    def setUp(self):
        self.client_a = make_client("A")
        self.client_b = make_client("B")
        self.hq_a = make_headquarters(self.client_a)

    def test_user_of_same_client_can_be_assigned(self):
        user = make_user(client=self.client_a)
        assignment = HeadquartersAssignment.objects.create(
            headquarters=self.hq_a, user=user
        )
        self.assertIsNotNone(assignment.pk)
        self.assertIn(user, self.hq_a.members.all())

    def test_user_of_other_client_cannot_be_assigned(self):
        user = make_user(client=self.client_b)
        with self.assertRaises(ValidationError):
            HeadquartersAssignment.objects.create(headquarters=self.hq_a, user=user)

    def test_duplicate_assignment_rejected(self):
        user = make_user(client=self.client_a)
        HeadquartersAssignment.objects.create(headquarters=self.hq_a, user=user)
        with self.assertRaises(ValidationError):
            HeadquartersAssignment.objects.create(headquarters=self.hq_a, user=user)

    def test_headquarters_name_unique_per_client_only(self):
        make_headquarters(self.client_a, "Main")
        # Same name under another client is fine.
        make_headquarters(self.client_b, "Main")
        with self.assertRaises(Exception):
            make_headquarters(self.client_a, "Main")
