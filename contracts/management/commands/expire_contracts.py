from django.core.management.base import BaseCommand

from contracts.models import Contract, ContractStatus


class Command(BaseCommand):
    help = (
        "Flip ACTIVE contracts whose end_date has passed to EXPIRED. "
        "Run nightly (cron / Celery Beat). Access enforcement does not "
        "depend on this job — login and refresh check validity by date — "
        "but it keeps the stored status honest for the admin UI."
    )

    def handle(self, *args, **options):
        overdue = list(Contract.objects.overdue().select_related("client"))
        for contract in overdue:
            contract.mark_expired()
            self.stdout.write(f"Expired {contract.reference} ({contract.client.name})")
        self.stdout.write(self.style.SUCCESS(f"{len(overdue)} contract(s) expired."))
        # Report on the side effect that matters: clients that just lost access.
        for client in {contract.client for contract in overdue}:
            if not client.has_active_contract():
                self.stdout.write(
                    self.style.WARNING(f"Client without active contract: {client.name}")
                )
