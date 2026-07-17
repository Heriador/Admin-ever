from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ContractStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    TERMINATED = "TERMINATED", "Terminated"


class ContractQuerySet(models.QuerySet):
    def visible_to(self, user):
        from organizations.models import Client

        return self.filter(client__in=Client.objects.visible_to(user))

    def currently_valid(self, at=None):
        """Contracts that grant access on the given date.

        A contract grants access while its status is ACTIVE and the date
        falls inside [start_date, end_date]. A null end_date means
        open-ended.
        """
        at = at or timezone.now().date()
        return self.filter(status=ContractStatus.ACTIVE, start_date__lte=at).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=at)
        )

    def overdue(self, at=None):
        """ACTIVE contracts whose end_date has passed and should be flipped
        to EXPIRED by the expiry job."""
        at = at or timezone.now().date()
        return self.filter(status=ContractStatus.ACTIVE, end_date__lt=at)


class Contract(models.Model):
    client = models.ForeignKey(
        "organizations.Client", on_delete=models.CASCADE, related_name="contracts"
    )
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20, choices=ContractStatus.choices, default=ContractStatus.DRAFT
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Blank = open-ended.")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ContractQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="contract_end_not_before_start",
            )
        ]

    def __str__(self):
        return f"{self.reference} ({self.client.name})"

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be before start date."})

    @property
    def is_currently_valid(self):
        today = timezone.now().date()
        return (
            self.status == ContractStatus.ACTIVE
            and self.start_date <= today
            and (self.end_date is None or self.end_date >= today)
        )

    def mark_expired(self):
        self.status = ContractStatus.EXPIRED
        self.save(update_fields=["status", "updated_at"])
