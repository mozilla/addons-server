from django.contrib import admin, messages
from django.db.utils import IntegrityError

from olympia.access.admin import GroupUserInline
from olympia.amo.utils import render

from . import forms
from .models import DeniedName, UserProfile


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('id', '^email', '^username')
    # A custom field used in search json in zadmin, not django.admin.
    search_fields_response = 'email'
    inlines = (GroupUserInline,)

    # XXX TODO: Ability to edit the picture
    fieldsets = (
        (None, {
            'fields': ('email', 'username', 'display_name',
                       'biography', 'homepage', 'location', 'occupation'),
        }),
        ('Flags', {
            'fields': ('deleted', 'display_collections',
                       'display_collections_fav', 'is_public'),
        }),
        ('Admin', {
            'fields': ('notes', 'picture_type'),
        }),
    )

    def delete_model(self, request, obj):
        obj.delete(hard=True)


class DeniedModelAdmin(admin.ModelAdmin):
    def add_view(self, request, form_url='', extra_context=None):
        """Override the default admin add view for bulk add."""
        form = self.model_add_form()
        if request.method == 'POST':
            form = self.model_add_form(request.POST)
            if form.is_valid():
                inserted = 0
                duplicates = 0

                for x in form.cleaned_data[self.add_form_field].splitlines():
                    # check with the cache
                    if self.deny_list_model.blocked(x):
                        duplicates += 1
                        continue
                    try:
                        self.deny_list_model.objects.create(
                            **{self.model_field: x.lower()})
                        inserted += 1
                    except IntegrityError:
                        # although unlikely, someone else could have added
                        # the same value.
                        # note: unless we manage the transactions manually,
                        # we do lose a primary id here.
                        duplicates += 1
                msg = '%s new values added to the deny list.' % (inserted)
                if duplicates:
                    msg += ' %s duplicates were ignored.' % (duplicates)
                messages.success(request, msg)
                form = self.model_add_form()
        return render(request, self.template_path, {'form': form})


class DeniedNameAdmin(DeniedModelAdmin):
    list_display = search_fields = ('name',)
    deny_list_model = DeniedName
    model_field = 'name'
    model_add_form = forms.DeniedNameAddForm
    add_form_field = 'names'
    template_path = 'users/admin/denied_name/add.html'


admin.site.register(UserProfile, UserAdmin)
admin.site.register(DeniedName, DeniedNameAdmin)
