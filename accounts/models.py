from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class UserType(models.TextChoices):
    PLATFORM = "PLATFORM", "Platform"
    PARTNER = "PARTNER", "Partner"
    CLIENT = "CLIENT", "Client"


class Role(models.Model):
    """A named capability set returned to the desktop app on login.

    Roles decide *what* a user may do; the user's type/organization
    decides *which clients* they may do it to (see
    Client.objects.visible_to). Well-known codes live in `Role.Codes`
    and are seeded by a data migratio n.
    """

    class Codes:
        SUPER_ADMIN = "SUPER_ADMIN"
        PLATFORM_SUPPORT = "PLATFORM_SUPPORT"
        PLATFORM_VIEWER = "PLATFORM_VIEWER"
        PARTNER_ADMIN = "PARTNER_ADMIN"
        CLIENT_ADMIN = "CLIENT_ADMIN"
        CLIENT_USER = "CLIENT_USER"

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    user_type = models.CharField(
        max_length=20, choices=UserType.choices, default=UserType.CLIENT
    )
    client = models.ForeignKey(
        "organizations.Client",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="users",
    )
    partner = models.ForeignKey(
        "organizations.Partner",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="users",
    )
    roles = models.ManyToManyField(Role, related_name="users", blank=True)

    class Meta(AbstractUser.Meta):
        constraints = [
            # The organization FKs must match the user type: platform
            # users have neither, partner users only a partner, client
            # users only a client.
            models.CheckConstraint(
                condition=(
                    models.Q(user_type=UserType.PLATFORM, client__isnull=True, partner__isnull=True)
                    | models.Q(user_type=UserType.PARTNER, client__isnull=True, partner__isnull=False)
                    | models.Q(user_type=UserType.CLIENT, client__isnull=False, partner__isnull=True)
                ),
                name="user_organization_matches_type",
            )
        ]

    def __str__(self):
        return self.username

    # --- Type helpers ----------------------------------------------------

    @property
    def is_platform(self):
        return self.user_type == UserType.PLATFORM

    @property
    def is_partner(self):
        return self.user_type == UserType.PARTNER

    @property
    def is_client(self):
        return self.user_type == UserType.CLIENT

    def clean(self):
        super().clean()
        if self.is_platform and (self.client_id or self.partner_id):
            raise ValidationError("Platform users cannot belong to a client or partner.")
        if self.is_partner and (not self.partner_id or self.client_id):
            raise ValidationError("Partner users must belong to a partner and no client.")
        if self.is_client and (not self.client_id or self.partner_id):
            raise ValidationError("Client users must belong to a client and no partner.")

    # --- Access & scope ---------------------------------------------------

    def has_active_access(self):
        """Whether this user may authenticate right now.

        Client users are cut off when their client is deactivated or its
        contract lapses. Partner and platform users keep access (their
        *scope* shrinks instead — see scoped_clients).
        """
        if not self.is_active:
            return False
        if self.is_client:
            return self.client.is_active and self.client.has_active_contract()
        if self.is_partner:
            return self.partner.is_active
        return True

    def scoped_clients(self):
        """Clients this user can currently act on: their visibility set,
        narrowed to active clients holding a valid contract."""
        from organizations.models import Client

        return (
            Client.objects.visible_to(self)
            .active()
            .with_active_contract()
        )

    def role_codes(self):
        return list(self.roles.values_list("code", flat=True))
