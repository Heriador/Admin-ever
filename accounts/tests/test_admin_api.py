"""End-to-end permission/scope matrix for the admin CRUD API.

Four personas exercised against every resource family:
- super:    PLATFORM + SUPER_ADMIN        (all capabilities)
- viewer:   PLATFORM + PLATFORM_VIEWER    (read-only everywhere)
- partner:  PARTNER + PARTNER_ADMIN       (users/HQ inside linked clients)
- cadmin:   CLIENT  + CLIENT_ADMIN        (users/HQ inside own client)
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Capability, Role, User, UserType
from contracts.models import Contract, ContractStatus
from organizations.models import Headquarters, HeadquartersAssignment

from .factories import (
    make_client,
    make_contract,
    make_headquarters,
    make_partner,
    make_user,
)


class AdminApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.client_a = make_client("Client A")
        cls.client_b = make_client("Client B")
        cls.client_c = make_client("Client C")
        for c in (cls.client_a, cls.client_b, cls.client_c):
            make_contract(c)
        cls.partner_org = make_partner("Partner X", clients=[cls.client_a, cls.client_b])

        cls.super = make_user(UserType.PLATFORM, roles=[Role.Codes.SUPER_ADMIN])
        cls.viewer = make_user(UserType.PLATFORM, roles=[Role.Codes.PLATFORM_VIEWER])
        cls.partner = make_user(
            UserType.PARTNER, partner=cls.partner_org, roles=[Role.Codes.PARTNER_ADMIN]
        )
        cls.cadmin = make_user(
            client=cls.client_a, roles=[Role.Codes.CLIENT_ADMIN], username="cadmin"
        )

    def as_user(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def results(self, response):
        return response.data["results"]


class ClientEndpointTests(AdminApiTestCase):
    def test_list_is_scoped_per_persona(self):
        for user, expected in [
            (self.super, {"Client A", "Client B", "Client C"}),
            (self.partner, {"Client A", "Client B"}),
            (self.cadmin, {"Client A"}),
        ]:
            response = self.as_user(user).get(reverse("client-list"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {c["name"] for c in self.results(response)}, expected
            )

    def test_viewer_reads_but_cannot_write(self):
        api = self.as_user(self.viewer)
        self.assertEqual(api.get(reverse("client-list")).status_code, 200)
        response = api.post(reverse("client-list"), {"name": "New Co"})
        self.assertEqual(response.status_code, 403)

    def test_super_admin_creates_client(self):
        response = self.as_user(self.super).post(
            reverse("client-list"), {"name": "New Co", "status": "ACTIVE"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["has_active_contract"])

    def test_client_admin_cannot_modify_own_client(self):
        response = self.as_user(self.cadmin).patch(
            reverse("client-detail", args=[self.client_a.id]), {"name": "Renamed"}
        )
        self.assertEqual(response.status_code, 403)

    def test_out_of_scope_client_is_404_not_403(self):
        # Scope filtering means "Client C" simply does not exist for the
        # partner — existence is not leaked.
        response = self.as_user(self.partner).get(
            reverse("client-detail", args=[self.client_c.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_clients_cannot_be_deleted(self):
        response = self.as_user(self.super).delete(
            reverse("client-detail", args=[self.client_c.id])
        )
        self.assertEqual(response.status_code, 405)


class UserEndpointTests(AdminApiTestCase):
    def create_payload(self, **overrides):
        payload = {
            "username": "newuser",
            "password": "s3cure-Pass-9",
            "user_type": UserType.CLIENT,
            "client": self.client_a.id,
            "roles": [Role.Codes.CLIENT_USER],
        }
        payload.update(overrides)
        return payload

    def test_list_is_scoped(self):
        make_user(client=self.client_b, username="b-user")
        seen_by_cadmin = self.as_user(self.cadmin).get(reverse("user-list"))
        self.assertEqual(
            {u["username"] for u in self.results(seen_by_cadmin)}, {"cadmin"}
        )
        seen_by_partner = self.as_user(self.partner).get(reverse("user-list"))
        # Own partner colleagues + users of linked clients; no platform staff.
        self.assertEqual(
            {u["username"] for u in self.results(seen_by_partner)},
            {"cadmin", "b-user", self.partner.username},
        )

    def test_client_admin_creates_user_in_own_client(self):
        response = self.as_user(self.cadmin).post(
            reverse("user-list"), self.create_payload()
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username="newuser")
        self.assertEqual(created.client_id, self.client_a.id)
        self.assertTrue(created.check_password("s3cure-Pass-9"))

    def test_client_admin_cannot_create_user_elsewhere(self):
        response = self.as_user(self.cadmin).post(
            reverse("user-list"), self.create_payload(client=self.client_b.id)
        )
        self.assertEqual(response.status_code, 400)

    def test_partner_admin_creates_user_in_linked_client(self):
        response = self.as_user(self.partner).post(
            reverse("user-list"), self.create_payload(client=self.client_b.id)
        )
        self.assertEqual(response.status_code, 201)

    def test_non_platform_cannot_create_platform_users(self):
        response = self.as_user(self.partner).post(
            reverse("user-list"),
            self.create_payload(user_type=UserType.PLATFORM, client=None),
        )
        self.assertEqual(response.status_code, 400)

    def test_role_escalation_is_blocked(self):
        response = self.as_user(self.cadmin).post(
            reverse("user-list"), self.create_payload(roles=[Role.Codes.SUPER_ADMIN])
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("capabilities you do not hold", str(response.data))

    def test_custom_role_within_own_capabilities_is_grantable(self):
        limited = Role.objects.create(code="HQ_ONLY", name="HQ only")
        limited.capabilities.set(
            Capability.objects.filter(code=Capability.Codes.HEADQUARTERS_READ)
        )
        response = self.as_user(self.cadmin).post(
            reverse("user-list"), self.create_payload(roles=["HQ_ONLY"])
        )
        self.assertEqual(response.status_code, 201)

    def test_weak_password_rejected(self):
        response = self.as_user(self.super).post(
            reverse("user-list"), self.create_payload(password="123")
        )
        self.assertEqual(response.status_code, 400)

    def test_non_platform_cannot_rehome_users(self):
        target = make_user(client=self.client_a, username="movable")
        response = self.as_user(self.cadmin).patch(
            reverse("user-detail", args=[target.id]), {"client": self.client_b.id}
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_deactivates_instead_of_removing(self):
        target = make_user(client=self.client_a, username="leaving")
        response = self.as_user(self.cadmin).delete(
            reverse("user-detail", args=[target.id])
        )
        self.assertEqual(response.status_code, 204)
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_platform_admin_creates_partner_user(self):
        response = self.as_user(self.super).post(
            reverse("user-list"),
            self.create_payload(
                user_type=UserType.PARTNER, client=None, partner=self.partner_org.id,
                roles=[Role.Codes.PARTNER_ADMIN],
            ),
        )
        self.assertEqual(response.status_code, 201)


class ContractEndpointTests(AdminApiTestCase):
    def test_partner_reads_but_cannot_write_contracts(self):
        api = self.as_user(self.partner)
        listing = api.get(reverse("contract-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            {c["client"] for c in self.results(listing)},
            {self.client_a.id, self.client_b.id},
        )
        response = api.post(
            reverse("contract-list"),
            {"client": self.client_a.id, "reference": "X-1", "start_date": "2026-01-01"},
        )
        self.assertEqual(response.status_code, 403)

    def test_super_admin_creates_contract(self):
        response = self.as_user(self.super).post(
            reverse("contract-list"),
            {
                "client": self.client_c.id,
                "reference": "NEW-1",
                "status": ContractStatus.ACTIVE,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_currently_valid"])

    def test_only_draft_contracts_can_be_deleted(self):
        draft = make_contract(self.client_c, status=ContractStatus.DRAFT)
        active = Contract.objects.filter(
            client=self.client_c, status=ContractStatus.ACTIVE
        ).first()
        api = self.as_user(self.super)
        self.assertEqual(
            api.delete(reverse("contract-detail", args=[active.id])).status_code, 400
        )
        self.assertEqual(
            api.delete(reverse("contract-detail", args=[draft.id])).status_code, 204
        )

    def test_end_before_start_rejected(self):
        response = self.as_user(self.super).post(
            reverse("contract-list"),
            {
                "client": self.client_c.id,
                "reference": "BAD-9",
                "start_date": "2026-06-01",
                "end_date": "2026-01-01",
            },
        )
        self.assertEqual(response.status_code, 400)


class HeadquartersEndpointTests(AdminApiTestCase):
    def test_client_admin_manages_own_headquarters(self):
        api = self.as_user(self.cadmin)
        created = api.post(
            reverse("headquarters-list"),
            {"client": self.client_a.id, "name": "North"},
        )
        self.assertEqual(created.status_code, 201)
        elsewhere = api.post(
            reverse("headquarters-list"),
            {"client": self.client_c.id, "name": "Rogue"},
        )
        self.assertEqual(elsewhere.status_code, 400)

    def test_assignment_lifecycle(self):
        hq = make_headquarters(self.client_a, "Main")
        member = make_user(client=self.client_a, username="member")
        api = self.as_user(self.cadmin)

        assign = api.post(
            reverse("headquarters-assign", args=[hq.id]), {"user_id": member.id}
        )
        self.assertEqual(assign.status_code, 204)
        self.assertTrue(
            HeadquartersAssignment.objects.filter(headquarters=hq, user=member).exists()
        )

        duplicate = api.post(
            reverse("headquarters-assign", args=[hq.id]), {"user_id": member.id}
        )
        self.assertEqual(duplicate.status_code, 400)

        detail = api.get(reverse("headquarters-detail", args=[hq.id]))
        self.assertEqual(
            [m["username"] for m in detail.data["members"]], ["member"]
        )

        unassign = api.post(
            reverse("headquarters-unassign", args=[hq.id]), {"user_id": member.id}
        )
        self.assertEqual(unassign.status_code, 204)
        repeat = api.post(
            reverse("headquarters-unassign", args=[hq.id]), {"user_id": member.id}
        )
        self.assertEqual(repeat.status_code, 400)

    def test_cross_client_assignment_rejected(self):
        hq = make_headquarters(self.client_a, "Main")
        outsider = make_user(client=self.client_b, username="outsider")
        response = self.as_user(self.partner).post(
            reverse("headquarters-assign", args=[hq.id]), {"user_id": outsider.id}
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_assign(self):
        hq = make_headquarters(self.client_a, "Main")
        member = make_user(client=self.client_a, username="member2")
        response = self.as_user(self.viewer).post(
            reverse("headquarters-assign", args=[hq.id]), {"user_id": member.id}
        )
        self.assertEqual(response.status_code, 403)


class RoleEndpointTests(AdminApiTestCase):
    def test_super_admin_creates_custom_role(self):
        response = self.as_user(self.super).post(
            reverse("role-list"),
            {
                "code": "AUDITOR",
                "name": "Auditor",
                "capabilities": [
                    Capability.Codes.CLIENTS_READ,
                    Capability.Codes.CONTRACTS_READ,
                ],
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["is_system"])

    def test_system_role_bundle_editable_but_identity_frozen(self):
        role = Role.objects.get(code=Role.Codes.PLATFORM_VIEWER)
        api = self.as_user(self.super)
        rename = api.patch(reverse("role-detail", args=[role.id]), {"code": "VIEWER2"})
        self.assertEqual(rename.status_code, 400)
        rebundle = api.patch(
            reverse("role-detail", args=[role.id]),
            {"capabilities": [Capability.Codes.CLIENTS_READ]},
        )
        self.assertEqual(rebundle.status_code, 200)

    def test_system_role_cannot_be_deleted_custom_can(self):
        api = self.as_user(self.super)
        system = Role.objects.get(code=Role.Codes.CLIENT_USER)
        self.assertEqual(
            api.delete(reverse("role-detail", args=[system.id])).status_code, 400
        )
        custom = Role.objects.create(code="TEMP", name="Temp")
        self.assertEqual(
            api.delete(reverse("role-detail", args=[custom.id])).status_code, 204
        )

    def test_partner_admin_has_no_role_access(self):
        response = self.as_user(self.partner).get(reverse("role-list"))
        self.assertEqual(response.status_code, 403)

    def test_capability_catalog_is_read_only(self):
        api = self.as_user(self.super)
        listing = api.get(reverse("capability-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 12)
        create = api.post(
            reverse("capability-list"), {"code": "x.y", "name": "X"}
        )
        # Our permission class denies unsafe methods (403) before DRF's
        # routing would return 405 — writes are blocked either way.
        self.assertEqual(create.status_code, 403)
