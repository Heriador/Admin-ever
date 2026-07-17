from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models


class UserType(models.TextChoices):
    PLATFORM = "PLATFORM", "Platform"
    PARTNER = "PARTNER", "Partner"
    CLIENT = "CLIENT", "Client"


class Capability(models.Model):
    """An atomic permission code — the stable authorization contract.

    Roles are editable bundles of capabilities, so with custom roles a
    role *name* means nothing to enforcement code. The API's permission
    checks and the desktop app's feature gating must always test
    capability codes, never role names. Backend-enforced codes live in
    `Capability.Codes`; platform admins may add further codes that only
    the desktop app interprets (e.g. gating a screen).
    """

    class Codes:
        CLIENTS_READ = "clients.read"
        CLIENTS_MANAGE = "clients.manage"
        PARTNERS_READ = "partners.read"
        PARTNERS_MANAGE = "partners.manage"
        USERS_READ = "users.read"
        USERS_MANAGE = "users.manage"
        CONTRACTS_READ = "contracts.read"
        CONTRACTS_MANAGE = "contracts.manage"
        HEADQUARTERS_READ = "headquarters.read"
        HEADQUARTERS_MANAGE = "headquarters.manage"
        ROLES_READ = "roles.read"
        ROLES_MANAGE = "roles.manage"

    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "capabilities"

    def __str__(self):
        return self.code


class Role(models.Model):
    """A named, runtime-editable bundle of capabilities.

    Roles decide *what* a user may do; the user's type/organization
    decides *which clients* they may do it to (see
    Client.objects.visible_to). The six built-in roles are seeded by a
    data migration and flagged `is_system`; custom roles are created by
    administrators at runtime. Never key authorization off `code` —
    use capability codes (see Capability).
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
    capabilities = models.ManyToManyField(Capability, related_name="roles", blank=True)
    is_system = models.BooleanField(
        default=False,
        help_text="Seeded role required by the platform; cannot be deleted.",
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError("System roles cannot be deleted.")
        return super().delete(*args, **kwargs)


class UserQuerySet(models.QuerySet):
    def visible_to(self, user):
        """User scoping, mirroring Client.objects.visible_to: platform
        staff see everyone; partner users see their partner's own users
        plus the users of its linked clients; client users see their
        client's users."""
        if user.is_platform:
            return self
        if user.is_partner and user.partner_id:
            return self.filter(
                models.Q(client__partners=user.partner_id)
                | models.Q(partner_id=user.partner_id)
            ).distinct()
        if user.is_client and user.client_id:
            return self.filter(client_id=user.client_id)
        return self.none()


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    # Concrete named class (not a from_queryset() dynamic type) so the
    # migration framework can serialize it: Django's UserManager sets
    # use_in_migrations = True.
    pass


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

    objects = UserManager()

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

    def capability_codes(self):
        """Effective capabilities: the union across all of the user's
        roles. This — not role codes — is what authorization checks
        and the desktop app must consume."""
        return list(
            Capability.objects.filter(roles__users=self)
            .values_list("code", flat=True)
            .distinct()
        )

    def has_capability(self, code):
        return Capability.objects.filter(roles__users=self, code=code).exists()
