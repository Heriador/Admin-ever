"""Plain helper constructors shared by the test suites.

Kept dependency-free (no factory_boy) while the model surface is small.
"""

import itertools
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Role, UserType
from contracts.models import Contract, ContractStatus
from organizations.models import Client, ClientStatus, Headquarters, Partner

User = get_user_model()
_seq = itertools.count()


def make_client(name=None, status=ClientStatus.ACTIVE, **kwargs):
    # Tests default to ACTIVE (the model default is WAITING) so that
    # access checks pass unless a test opts into another status.
    return Client.objects.create(
        name=name or f"Client {next(_seq)}", status=status, **kwargs
    )


def make_partner(name=None, clients=(), **kwargs):
    partner = Partner.objects.create(name=name or f"Partner {next(_seq)}", **kwargs)
    partner.clients.set(clients)
    return partner


def make_contract(
    client, status=ContractStatus.ACTIVE, start=None, end="default", reference=None, **kwargs
):
    today = timezone.now().date()
    if end == "default":
        end = today + timedelta(days=365)
    return Contract.objects.create(
        client=client,
        reference=reference or f"C-{next(_seq)}",
        status=status,
        start_date=start or today - timedelta(days=30),
        end_date=end,
        **kwargs,
    )


def make_headquarters(client, name=None, **kwargs):
    return Headquarters.objects.create(
        client=client, name=name or f"HQ {next(_seq)}", **kwargs
    )


def make_user(user_type=UserType.CLIENT, client=None, partner=None, roles=(), **kwargs):
    kwargs.setdefault("username", f"user{next(_seq)}")
    kwargs.setdefault("password", "test-password-123")
    user = User.objects.create_user(
        user_type=user_type, client=client, partner=partner, **kwargs
    )
    if roles:
        user.roles.set(Role.objects.filter(code__in=roles))
    return user
