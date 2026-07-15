from django.contrib import admin

from contracts.models import Contract

from .models import Client, Headquarters, HeadquartersAssignment, Partner


class ContractInline(admin.TabularInline):
    model = Contract
    extra = 0


class HeadquartersInline(admin.TabularInline):
    model = Headquarters
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "contract_status", "created_at")
    list_filter = ("status",)
    search_fields = ("name",)
    inlines = [ContractInline, HeadquartersInline]

    @admin.display(boolean=True, description="Active contract")
    def contract_status(self, obj):
        return obj.has_active_contract()


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    filter_horizontal = ("clients",)


class AssignmentInline(admin.TabularInline):
    model = HeadquartersAssignment
    extra = 0


@admin.register(Headquarters)
class HeadquartersAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "is_active")
    list_filter = ("is_active", "client")
    search_fields = ("name", "client__name")
    inlines = [AssignmentInline]
