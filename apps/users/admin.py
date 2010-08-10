from django.contrib import admin, messages
from django.db.utils import IntegrityError
from django.utils.encoding import smart_unicode

import jingo

from access.admin import GroupUserInline
from .models import UserProfile, BlacklistedNickname
from .users import forms


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('^email',)
    inlines = (GroupUserInline,)

    # XXX TODO: Ability to edit the picture
    # XXX TODO: Ability to change the password (use AdminPasswordChangeForm)
    fieldsets = (
        (None, {
            'fields': ('nickname', 'firstname', 'lastname', 'email',
                       'password', 'bio', 'homepage', 'location',
                       'occupation',),
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


class BlacklistedNicknameAdmin(admin.ModelAdmin):
    list_display = search_fields = ('nickname',)

    def add_view(self, request, form_url='', extra_context=None):
        """Override the default admin add view for bulk add."""
        form = forms.BlacklistedNicknameAddForm()
        if request.method == 'POST':
            form = forms.BlacklistedNicknameAddForm(request.POST)
            if form.is_valid():
                inserted = 0
                duplicates = 0
                for n in form.cleaned_data['nicknames'].splitlines():
                    # check with teh cache
                    if BlacklistedNickname.blocked(n):
                        duplicates += 1
                        continue
                    n = smart_unicode(n).lower().encode('utf-8')
                    try:
                        BlacklistedNickname.objects.create(nickname=n)
                        inserted += 1
                    except IntegrityError:
                        # although unlikely, someone else could have added
                        # the nickname.
                        # note: unless we manage the transactions manually,
                        # we do lose a primary id here
                        duplicates += 1
                msg = '%s new nicknames added to the blacklist.' % (inserted)
                if duplicates:
                    msg += ' %s duplicates were ignored.' % (duplicates)
                messages.success(request, msg)
                form = forms.BlacklistedNicknameAddForm()
                # Default django admin change list view does not print messages
                # no redirect for now
                # return http.HttpResponseRedirect(reverse(
                #     'admin:users_blacklistednickname_changelist'))
        return jingo.render(request, 'admin/blacklisted_nickname/add.html',
                            {'form': form})

admin.site.register(UserProfile, UserAdmin)
admin.site.register(BlacklistedNickname, BlacklistedNicknameAdmin)
