from django.contrib import admin, messages
from django.db.utils import IntegrityError

import jingo

from access.admin import GroupUserInline
from .models import UserProfile, BlacklistedUsername, BlacklistedEmailDomain
from .users import forms


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('^email',)
    inlines = (GroupUserInline,)

    # XXX TODO: Ability to edit the picture
    # XXX TODO: Ability to change the password (use AdminPasswordChangeForm)
    fieldsets = (
        (None, {
            'fields': ('email', 'username', 'display_name', 'password',
                       'bio', 'homepage', 'location', 'occupation',),
        }),
        ('Registration', {
            'fields': ('confirmationcode', 'resetcode',
                       'resetcode_expires'),
        }),
        ('Flags', {
            'fields': ('deleted', 'display_collections',
                       'display_collections_fav', 'emailhidden',
                       'notifycompat', 'notifyevents', 'sandboxshown'),
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
        return jingo.render(request, self.template_path, {'form': form})


class BlacklistedUsernameAdmin(BlacklistModelAdmin):
    list_display = search_fields = ('username',)
    blacklist_model = BlacklistedUsername
    model_field = 'username'
    model_add_form = forms.BlacklistedUsernameAddForm
    add_form_field = 'usernames'
    template_path = 'admin/blacklisted_username/add.html'


class BlacklistedEmailDomainAdmin(BlacklistModelAdmin):
    list_display = search_fields = ('domain',)
    blacklist_model = BlacklistedEmailDomain
    model_field = 'domain'
    model_add_form = forms.BlacklistedEmailDomainAddForm
    add_form_field = 'domains'
    template_path = 'admin/blacklisted_email_domain/add.html'

admin.site.register(UserProfile, UserAdmin)
admin.site.register(BlacklistedUsername, BlacklistedUsernameAdmin)
admin.site.register(BlacklistedEmailDomain, BlacklistedEmailDomainAdmin)
