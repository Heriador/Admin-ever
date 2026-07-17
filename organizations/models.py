from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ClientStatus(models.TextChoices):
    WAITING = "WAITING", "Waiting"  # Created, pending approval or activation
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"  # Temporarily suspended, may be reactivated
    DEACTIVATED = "DEACTIVATED", "Deactivated"  # Terminated permanently

    # Only ACTIVE grants access; every other status locks out the
    # client's users and drops the client from partner/platform scope.


class ClientQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The single source of truth for client scoping.

        Every endpoint and service that lists or touches clients must go
        through this method so a scoping rule is never re-implemented
        (and gotten subtly wrong) elsewhere.
        """
        if user.is_platform:
            return self
        if user.is_partner and user.partner_id:
            return self.filter(partners=user.partner_id)
        if user.is_client and user.client_id:
            return self.filter(pk=user.client_id)
        return self.none()

    def active(self):
        return self.filter(status=ClientStatus.ACTIVE)

    def with_active_contract(self, at=None):
        from contracts.models import Contract

        valid = Contract.objects.currently_valid(at=at).filter(client=models.OuterRef("pk"))
        return self.filter(models.Exists(valid))


class Client(models.Model):
    name = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=20, choices=ClientStatus.choices, default=ClientStatus.WAITING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ClientQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "clients"

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        """Access is granted only while ACTIVE; WAITING, INACTIVE and
        DEACTIVATED all deny it. Keep every access decision on this
        property (or ClientQuerySet.active()) so a new status can never
        slip through an ad-hoc comparison."""
        return self.status == ClientStatus.ACTIVE

    def has_active_contract(self, at=None):
        at = at or timezone.now().date()
        return self.contracts.currently_valid(at=at).exists()


class PartnerQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_platform:
            return self
        if user.is_partner and user.partner_id:
            return self.filter(pk=user.partner_id)
        return self.none()


class Partner(models.Model):
    """An organization whose users administer one or more clients."""

    name = models.CharField(max_length=255, unique=True)
    clients = models.ManyToManyField(Client, related_name="partners", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PartnerQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class HeadquartersQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self.filter(client__in=Client.objects.visible_to(user))


class Headquarters(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="headquarters"
    )
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="HeadquartersAssignment",
        related_name="headquarters",
        blank=True,
    )

    objects = HeadquartersQuerySet.as_manager()

    class Meta:
        ordering = ["client__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "name"], name="unique_headquarters_name_per_client"
            )
        ]
        verbose_name_plural = "headquarters"

    def __str__(self):
        return f"{self.client.name} / {self.name}"


class HeadquartersAssignment(models.Model):
    headquarters = models.ForeignKey(Headquarters, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["headquarters", "user"], name="unique_headquarters_assignment"
            )
        ]

    def __str__(self):
        return f"{self.user} @ {self.headquarters}"

    def clean(self):
        # Only users of the same client can be assigned to its headquarters.
        if self.user_id and self.headquarters_id:
            if self.user.client_id != self.headquarters.client_id:
                raise ValidationError(
                    "User must belong to the same client as the headquarters."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
