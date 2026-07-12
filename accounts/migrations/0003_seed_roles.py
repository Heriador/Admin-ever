from django.db import migrations

ROLES = [
    ("SUPER_ADMIN", "Super administrator", "Full control over the platform."),
    ("PLATFORM_SUPPORT", "Platform support", "Platform staff with limited management access."),
    ("PLATFORM_VIEWER", "Platform viewer", "Read-only platform access."),
    ("PARTNER_ADMIN", "Partner administrator", "Administers the clients linked to their partner."),
    ("CLIENT_ADMIN", "Client administrator", "Administers users and headquarters of their own client."),
    ("CLIENT_USER", "Client user", "Standard desktop application user."),
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for code, name, description in ROLES:
        Role.objects.update_or_create(
            code=code, defaults={"name": name, "description": description}
        )


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(code__in=[code for code, _, _ in ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
    ]

    operations = [migrations.RunPython(seed_roles, unseed_roles)]
