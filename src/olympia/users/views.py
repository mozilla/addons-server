import functools

from operator import attrgetter

from django import http
from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_list_or_404, get_object_or_404, redirect
from django.utils.http import is_safe_url
from django.utils.translation import ugettext
from django.views.decorators.cache import never_cache

import olympia.core.logger

from olympia import amo
from olympia.abuse.models import send_abuse_report
from olympia.access import acl
from olympia.accounts.views import logout_user
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon, Category
from olympia.amo import messages
from olympia.amo.decorators import (
    json_view, login_required, permission_required, use_primary_db)
from olympia.amo.forms import AbuseForm
from olympia.amo.urlresolvers import get_url_prefix, reverse
from olympia.amo.utils import escape_all, render
from olympia.bandwagon.models import Collection
from olympia.browse.views import PersonasFilter
from olympia.users import notifications as notifications
from olympia.users.models import UserNotification

from . import forms, tasks
from .models import UserProfile
from .signals import logged_out
from .utils import UnsubscribeCode


log = olympia.core.logger.getLogger('z.users')

addon_view = addon_view_factory(qs=Addon.objects.valid)

THEMES_LIMIT = 20


def user_view(f):
    @functools.wraps(f)
    def wrapper(request, user_id, *args, **kw):
        """Provides a user object given a user ID or username."""
        if user_id.isdigit():
            key = 'id'
        else:
            key = 'username'
            # If the username is `me` then show the current user's profile.
            if (user_id == 'me' and request.user and
                    request.user.username):
                user_id = request.user.username
        user = get_object_or_404(UserProfile, **{key: user_id})
        return f(request, user, *args, **kw)
    return wrapper


@login_required(redirect=False)
@json_view
@non_atomic_requests
def ajax(request):
    """Query for a user matching a given email."""

    if 'q' not in request.GET:
        raise http.Http404()

    data = {'status': 0, 'message': ''}

    email = request.GET.get('q', '').strip()

    if not email:
        data.update(message=ugettext('An email address is required.'))
        return data

    user = UserProfile.objects.filter(email=email)

    msg = ugettext('A user with that email address does not exist.')

    if user:
        data.update(status=1, id=user[0].id, name=user[0].name)
    else:
        data['message'] = msg

    return escape_all(data)


@login_required
def delete(request):
    amouser = request.user
    if request.method == 'POST':
        form = forms.UserDeleteForm(request.POST, request=request)
        if form.is_valid():
            messages.success(request, ugettext('Profile Deleted'))
            amouser.delete()
            response = http.HttpResponseRedirect(reverse('home'))
            logout_user(request, response)
            return response
    else:
        form = forms.UserDeleteForm(request=request)

    return render(request, 'users/delete.html',
                  {'form': form, 'amouser': amouser})


@login_required
def delete_photo(request, user_id):
    not_mine = str(request.user.id) != user_id
    if (not_mine and not acl.action_allowed(request,
                                            amo.permissions.USERS_EDIT)):
        return http.HttpResponseForbidden()

    user = UserProfile.objects.get(id=user_id)

    if request.method == 'POST':
        user.picture_type = None
        user.save()
        log.debug(u'User (%s) deleted photo' % user)
        tasks.delete_photo.delay(user.picture_path)
        messages.success(request, ugettext('Photo Deleted'))
        redirect = (
            reverse('users.admin_edit', kwargs={'user_id': user.id})
            if not_mine else reverse('users.edit')
        )
        return http.HttpResponseRedirect(redirect + '#user-profile')

    return render(request, 'users/delete_photo.html', {'target_user': user})


@use_primary_db
@login_required
def edit(request):
    # Don't use request.user since it has too much caching.
    amouser = UserProfile.objects.get(pk=request.user.id)
    if request.method == 'POST':
        # ModelForm alters the instance you pass in.  We need to keep a copy
        # around in case we need to use it below (to email the user)
        form = forms.UserEditForm(request.POST, request.FILES, request=request,
                                  instance=amouser)
        if form.is_valid():
            messages.success(request, ugettext('Profile Updated'))
            form.save()
            return redirect('users.edit')
        else:
            messages.error(
                request,
                ugettext('Errors Found'),
                ugettext('There were errors in the changes you made. '
                         'Please correct them and resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser, request=request)
    return render(request, 'users/edit.html',
                  {'form': form, 'amouser': amouser})


@use_primary_db
@login_required
@permission_required(amo.permissions.USERS_EDIT)
@user_view
def admin_edit(request, user):
    if request.method == 'POST':
        form = forms.AdminUserEditForm(request.POST, request.FILES,
                                       request=request, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, ugettext('Profile Updated'))
            return http.HttpResponseRedirect(reverse('zadmin.index'))
    else:
        form = forms.AdminUserEditForm(instance=user, request=request)
    return render(request, 'users/edit.html', {'form': form, 'amouser': user})


def _clean_next_url(request):
    gets = request.GET.copy()
    url = gets.get('to', settings.LOGIN_REDIRECT_URL)

    if not is_safe_url(url):
        log.info(u'Unsafe redirect to %s' % url)
        url = settings.LOGIN_REDIRECT_URL

    domain = gets.get('domain', None)
    if domain in settings.VALID_LOGIN_REDIRECTS.keys():
        url = settings.VALID_LOGIN_REDIRECTS[domain] + url

    gets['to'] = url
    request.GET = gets
    return request


def login(request):
    return render(request, 'users/login.html')


def logout(request):
    user = request.user
    if not user.is_anonymous():
        log.debug(u"User (%s) logged out" % user)

    if 'to' in request.GET:
        request = _clean_next_url(request)

    next = request.GET.get('to')
    if not next:
        next = settings.LOGOUT_REDIRECT_URL
        prefixer = get_url_prefix()
        if prefixer:
            next = prefixer.fix(next)

    response = http.HttpResponseRedirect(next)

    logout_user(request, response)

    # Fire logged out signal.
    logged_out.send(None, request=request, response=response)
    return response


@user_view
@non_atomic_requests
def profile(request, user):
    # Get user's own and favorite collections, if they allowed that.
    own_coll = fav_coll = []
    if user.display_collections:
        own_coll = (Collection.objects.listed().filter(author=user)
                    .order_by('-created'))[:10]
    if user.display_collections_fav:
        fav_coll = (Collection.objects.listed()
                    .filter(following__user=user)
                    .order_by('-following__created'))[:10]

    edit_any_user = acl.action_allowed(request, amo.permissions.USERS_EDIT)
    own_profile = (request.user.is_authenticated() and
                   request.user.id == user.id)

    addons = []
    personas = []
    limited_personas = False
    if user.is_developer:
        addons = user.addons.public().filter(
            addonuser__user=user, addonuser__listed=True)

        personas = addons.filter(type=amo.ADDON_PERSONA).order_by(
            '-persona__popularity')
        if personas.count() > THEMES_LIMIT:
            limited_personas = True
            personas = personas[:THEMES_LIMIT]

        addons = addons.exclude(type=amo.ADDON_PERSONA).order_by(
            '-weekly_downloads')
        addons = amo.utils.paginate(request, addons, 5)

    reviews = amo.utils.paginate(request, user.ratings.all())

    data = {'profile': user, 'own_coll': own_coll, 'reviews': reviews,
            'fav_coll': fav_coll, 'edit_any_user': edit_any_user,
            'addons': addons, 'own_profile': own_profile,
            'personas': personas, 'limited_personas': limited_personas,
            'THEMES_LIMIT': THEMES_LIMIT}
    if not own_profile:
        data['abuse_form'] = AbuseForm(request=request)

    return render(request, 'users/profile.html', data)


@user_view
@non_atomic_requests
def themes(request, user, category=None):
    cats = Category.objects.filter(type=amo.ADDON_PERSONA)

    ctx = {
        'profile': user,
        'categories': sorted(cats, key=attrgetter('weight', 'name')),
        'search_cat': 'themes'
    }

    if user.is_artist:
        base = user.addons.public().filter(
            type=amo.ADDON_PERSONA,
            addonuser__user=user, addonuser__listed=True)

        if category:
            qs = cats.filter(slug=category)
            ctx['category'] = cat = get_list_or_404(qs)[0]
            base = base.filter(categories__id=cat.id)

    else:
        base = Addon.objects.none()

    filter_ = PersonasFilter(request, base, key='sort',
                             default='popular')
    addons = amo.utils.paginate(request, filter_.qs, 30,
                                count=base.count())

    ctx.update({
        'addons': addons,
        'filter': filter_,
        'sorting': filter_.field,
        'sort_opts': filter_.opts
    })

    return render(request, 'browse/personas/grid.html', ctx)


@user_view
def report_abuse(request, user):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        send_abuse_report(request, user, form.cleaned_data['text'])
        messages.success(request, ugettext('User reported.'))
    else:
        return render(request, 'users/report_abuse_full.html',
                      {'profile': user, 'abuse_form': form})
    return redirect(user.get_url_path())


@never_cache
def unsubscribe(request, hash=None, token=None, perm_setting=None):
    """
    Pulled from django contrib so that we can add user into the form
    so then we can show relevant messages about the user.
    """
    assert hash is not None and token is not None
    user = None

    try:
        email = UnsubscribeCode.parse(token, hash)
        user = UserProfile.objects.get(email=email)
    except (ValueError, UserProfile.DoesNotExist):
        pass

    perm_settings = []
    if user is not None and perm_setting is not None:
        unsubscribed = True
        perm_setting = notifications.NOTIFICATIONS_BY_SHORT[perm_setting]
        UserNotification.objects.update_or_create(
            user=user, notification_id=perm_setting.id,
            defaults={'enabled': False})
        perm_settings = [perm_setting]
    else:
        unsubscribed = False
        email = ''

    return render(request, 'users/unsubscribe.html',
                  {'unsubscribed': unsubscribed, 'email': email,
                   'perm_settings': perm_settings})
