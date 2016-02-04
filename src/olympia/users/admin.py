from django.contrib import admin, messages
from django.db.utils import IntegrityError
from django.shortcuts import render

from olympia.access.admin import GroupUserInline

from .models import UserProfile, BlacklistedName, BlacklistedEmailDomain
from . import forms


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
                       'bio', 'homepage', 'location', 'occupation'),
        }),
        ('Registration', {
            'fields': ('confirmationcode',),
        }),
        ('Flags', {
            'fields': ('deleted', 'display_collections',
                       'display_collections_fav',
                       'notifycompat', 'notifyevents'),
        }),
        ('Admin', {
            'fields': ('notes', 'picture_type'),
        }),
    )


class BlacklistModelAdmin(admin.ModelAdmin):
    def add_view(self, request, form_url='', extra_context=None):
        """Override the default admin add view for bulk add."""
        form = self.model_add_form()
        if request.method == 'POST':
            form = self.model_add_form(request.POST)
            if form.is_valid():
                inserted = 0
                duplicates = 0

                for x in form.cleaned_data[self.add_form_field].splitlines():
                    # check with teh cache
                    if self.blacklist_model.blocked(x):
                        duplicates += 1
                        continue
                    try:
                        self.blacklist_model.objects.create(
                            **{self.model_field: x.lower()})
                        inserted += 1
                    except IntegrityError:
                        # although unlikely, someone else could have added
                        # the same value.
                        # note: unless we manage the transactions manually,
                        # we do lose a primary id here.
                        duplicates += 1
                msg = '%s new values added to the blacklist.' % (inserted)
                if duplicates:
                    msg += ' %s duplicates were ignored.' % (duplicates)
                messages.success(request, msg)
                form = self.model_add_form()
        return render(request, self.template_path, {'form': form})


class BlacklistedNameAdmin(BlacklistModelAdmin):
    list_display = search_fields = ('name',)
    blacklist_model = BlacklistedName
    model_field = 'name'
    model_add_form = forms.BlacklistedNameAddForm
    add_form_field = 'names'
    template_path = 'users/admin/blacklisted_name/add.html'


class BlacklistedEmailDomainAdmin(BlacklistModelAdmin):
    list_display = search_fields = ('domain',)
    blacklist_model = BlacklistedEmailDomain
    model_field = 'domain'
    model_add_form = forms.BlacklistedEmailDomainAddForm
    add_form_field = 'domains'
    template_path = 'users/admin/blacklisted_email_domain/add.html'

admin.site.register(UserProfile, UserAdmin)
admin.site.register(BlacklistedName, BlacklistedNameAdmin)
admin.site.register(BlacklistedEmailDomain, BlacklistedEmailDomainAdmin)
