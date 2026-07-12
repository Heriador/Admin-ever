from datetime import timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.tests.factories import make_client, make_contract
from contracts.models import Contract, ContractStatus


def days(n):
    return timezone.now().date() + timedelta(days=n)


class ContractValidityTests(TestCase):
    def setUp(self):
        self.client_org = make_client()

    def test_active_contract_in_window_is_valid(self):
        contract = make_contract(self.client_org, start=days(-10), end=days(10))
        self.assertTrue(contract.is_currently_valid)
        self.assertTrue(self.client_org.has_active_contract())

    def test_open_ended_contract_is_valid(self):
        make_contract(self.client_org, start=days(-10), end=None)
        self.assertTrue(self.client_org.has_active_contract())

    def test_future_contract_is_not_yet_valid(self):
        make_contract(self.client_org, start=days(5), end=days(100))
        self.assertFalse(self.client_org.has_active_contract())

    def test_past_contract_is_not_valid(self):
        make_contract(self.client_org, start=days(-100), end=days(-1))
        self.assertFalse(self.client_org.has_active_contract())

    def test_contract_valid_on_its_boundary_dates(self):
        make_contract(self.client_org, start=days(0), end=days(0))
        self.assertTrue(self.client_org.has_active_contract())

    def test_draft_and_terminated_contracts_grant_no_access(self):
        make_contract(self.client_org, status=ContractStatus.DRAFT)
        make_contract(self.client_org, status=ContractStatus.TERMINATED)
        self.assertFalse(self.client_org.has_active_contract())

    def test_end_before_start_rejected(self):
        contract = Contract(
            client=self.client_org,
            reference="BAD-1",
            status=ContractStatus.ACTIVE,
            start_date=days(0),
            end_date=days(-1),
        )
        with self.assertRaises(ValidationError):
            contract.full_clean()


class ExpireContractsCommandTests(TestCase):
    def test_overdue_active_contracts_are_expired(self):
        client_org = make_client()
        overdue = make_contract(client_org, start=days(-100), end=days(-1))
        current = make_contract(client_org, start=days(-10), end=days(10))
        already_expired = make_contract(
            client_org, status=ContractStatus.EXPIRED, start=days(-300), end=days(-200)
        )

        out = StringIO()
        call_command("expire_contracts", stdout=out)

        overdue.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(overdue.status, ContractStatus.EXPIRED)
        self.assertEqual(current.status, ContractStatus.ACTIVE)
        self.assertIn("1 contract(s) expired", out.getvalue())
        # Client still holds a valid contract, so no revocation warning.
        self.assertNotIn("without active contract", out.getvalue())

    def test_command_reports_clients_losing_access(self):
        client_org = make_client()
        make_contract(client_org, start=days(-100), end=days(-1))

        out = StringIO()
        call_command("expire_contracts", stdout=out)

        self.assertIn(f"Client without active contract: {client_org.name}", out.getvalue())
