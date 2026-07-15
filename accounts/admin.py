from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Capability, Role, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "user_type", "client", "partner", "is_active")
    list_filter = ("user_type", "is_active", "roles")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Organization & roles", {"fields": ("user_type", "client", "partner", "roles")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Organization & roles", {"fields": ("user_type", "client", "partner", "roles")}),
    )
    filter_horizontal = BaseUserAdmin.filter_horizontal + ("roles",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_system")
    list_filter = ("is_system",)
    search_fields = ("code", "name")
    filter_horizontal = ("capabilities",)

    def get_readonly_fields(self, request, obj=None):
        # System role identities are fixed; their capability bundles
        # stay editable.
        if obj and obj.is_system:
            return ("code", "is_system")
        return ("is_system",)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Capability)
class CapabilityAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
