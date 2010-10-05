from django.contrib import admin
from django.contrib.admin.filterspecs import FilterSpec

from .models import License, Version


class LicenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'builtin', 'url')
    list_filter = ('builtin',)
    ordering = ('builtin',)


class BuiltinFilterSpec(FilterSpec):
    """Let us filter licenses by builtin/non-builtin."""

    def __init__(self, field, request, params, model, model_admin):
        super(BuiltinFilterSpec, self).__init__(field, request, params,
                                                model, model_admin)
        self.lookup_kwarg = '%s__gt' % field.name
        self.lookup_val = request.GET.get(self.lookup_kwarg, False)

    def choices(self, cl):
        yield {'selected': not self.lookup_val,
               'query_string': cl.get_query_string({}, [self.lookup_kwarg]),
               'display': 'All licenses'}
        yield {'selected': self.lookup_val,
               'query_string': cl.get_query_string({self.lookup_kwarg: 0}),
               'display': 'Built-in licenses'}


FilterSpec.filter_specs.insert(0,
    (lambda f: f.model is License, BuiltinFilterSpec))

admin.site.register(License, LicenseAdmin)
admin.site.register(Version)
