"""Admin for the small reference/lookup models: DataType, BufferType, and the bare registrations."""

from django.contrib.gis import admin

from ..models import BufferType, DataType, MooringType, Program, StationType


@admin.register(DataType)
class DataTypeAdmin(admin.ModelAdmin):
    search_fields = ["short_name", "standard_name", "long_name", "units"]


@admin.register(BufferType)
class BufferTypeAdmin(admin.ModelAdmin):
    search_fields = ["name"]


admin.site.register(Program)
admin.site.register(MooringType)
admin.site.register(StationType)
