from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from django.utils.translation import get_language, get_language_bidi, gettext

from olympia import amo
from olympia.access import acl

from urllib.parse import quote


def i18n(request):
    lang = get_language()
    return {
        'LANGUAGES': settings.LANGUAGES,
        'LANG': settings.LANGUAGE_URL_MAP.get(lang) or lang,
        'DIR': 'rtl' if get_language_bidi() else 'ltr',
    }


def global_settings(request):
    """
    Storing standard AMO-wide information used in global headers, such as
    account links and settings.
    """
    account_links = []
    tools_links = []
    context = {}

    tools_title = gettext('Tools')
    is_reviewer = False

    # We're using `getattr` here because `request.user` can be missing,
    # e.g in case of a 500-server error.
    if getattr(request, 'user', AnonymousUser()).is_authenticated:
        is_reviewer = acl.is_user_any_kind_of_reviewer(request.user)

        account_links.append(
            {'text': gettext('My Profile'), 'href': request.user.get_url_path()}
        )

        account_links.append(
            {'text': gettext('Account Settings'), 'href': reverse('users.edit')}
        )
        account_links.append(
            {'text': gettext('My Collections'), 'href': reverse('collections.list')}
        )

        account_links.append(
            {
                'text': gettext('Log out'),
                'href': reverse('devhub.logout') + '?to=' + quote(request.path),
            }
        )

        if request.user.is_developer:
            tools_links.append(
                {
                    'text': gettext('Manage My Submissions'),
                    'href': reverse('devhub.addons'),
                }
            )
        tools_links.append(
            {
                'text': gettext('Submit a New Add-on'),
                'href': reverse('devhub.submit.agreement'),
            }
        )
        tools_links.append(
            {
                'text': gettext('Submit a New Theme'),
                'href': reverse('devhub.submit.agreement'),
            }
        )
        tools_links.append(
            {'text': gettext('Developer Hub'), 'href': reverse('devhub.index')}
        )
        tools_links.append(
            {'text': gettext('Manage API Keys'), 'href': reverse('devhub.api_key')}
        )

        if is_reviewer:
            tools_links.append(
                {
                    'text': gettext('Reviewer Tools'),
                    'href': reverse('reviewers.dashboard'),
                }
            )
        if acl.action_allowed(request, amo.permissions.ANY_ADMIN):
            tools_links.append(
                {'text': gettext('Admin Tools'), 'href': reverse('admin:index')}
            )

        context['user'] = request.user
    else:
        context['user'] = AnonymousUser()

    context.update(
        {
            'account_links': account_links,
            'settings': settings,
            'amo': amo,
            'tools_links': tools_links,
            'tools_title': tools_title,
            'is_reviewer': is_reviewer,
        }
    )
    return context
