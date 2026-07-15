from django.db import migrations

CAPABILITIES = [
    ("clients.read", "View clients"),
    ("clients.manage", "Create and modify clients"),
    ("partners.read", "View partners"),
    ("partners.manage", "Create and modify partners"),
    ("users.read", "View users"),
    ("users.manage", "Create and modify users"),
    ("contracts.read", "View contracts"),
    ("contracts.manage", "Create and modify contracts"),
    ("headquarters.read", "View headquarters"),
    ("headquarters.manage", "Create and modify headquarters"),
    ("roles.read", "View roles"),
    ("roles.manage", "Create and modify custom roles"),
]

ALL = [code for code, _ in CAPABILITIES]
READS = [code for code in ALL if code.endswith(".read")]

# Capability bundles for the six built-in roles. Editable at runtime;
# this is only the starting point.
SYSTEM_ROLE_CAPABILITIES = {
    "SUPER_ADMIN": ALL,
    "PLATFORM_SUPPORT": [
        "clients.read", "clients.manage",
        "partners.read",
        "users.read", "users.manage",
        "contracts.read", "contracts.manage",
        "headquarters.read", "headquarters.manage",
        "roles.read",
    ],
    "PLATFORM_VIEWER": READS,
    "PARTNER_ADMIN": [
        "clients.read",
        "users.read", "users.manage",
        "contracts.read",
        "headquarters.read", "headquarters.manage",
    ],
    "CLIENT_ADMIN": [
        "clients.read",
        "users.read", "users.manage",
        "contracts.read",
        "headquarters.read", "headquarters.manage",
    ],
    "CLIENT_USER": [],
}


def seed(apps, schema_editor):
    Capability = apps.get_model("accounts", "Capability")
    Role = apps.get_model("accounts", "Role")

    by_code = {}
    for code, name in CAPABILITIES:
        by_code[code], _ = Capability.objects.update_or_create(
            code=code, defaults={"name": name}
        )

    for role_code, capability_codes in SYSTEM_ROLE_CAPABILITIES.items():
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            continue
        role.is_system = True
        role.save(update_fields=["is_system"])
        role.capabilities.set([by_code[c] for c in capability_codes])


def unseed(apps, schema_editor):
    Capability = apps.get_model("accounts", "Capability")
    Capability.objects.filter(code__in=ALL).delete()
    Role = apps.get_model("accounts", "Role")
    Role.objects.update(is_system=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_capability_role_is_system_role_capabilities"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
