import collections
import datetime
import json
import sys
import traceback

from django import http
from django.conf import settings
from django.forms.formsets import formset_factory
from django.db.models import Q
from django.db.transaction import commit_on_success
from django.shortcuts import get_object_or_404, redirect
from django.utils.datastructures import MultiValueDictKeyError

import commonware.log
import jingo
import requests
from tower import ugettext as _
from waffle.decorators import waffle_switch

import amo
from abuse.models import AbuseReport
from access import acl
from addons.decorators import addon_view
from addons.models import AddonDeviceType, Persona, Version
from amo import messages
from amo.decorators import json_view, permission_required, post_required
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import (escape_all, HttpResponseSendFile, JSONEncoder, paginate,
                       smart_decode)
from editors.forms import MOTDForm
from editors.models import (EditorSubscription, EscalationQueue, RereviewQueue,
                            ReviewerScore)
from editors.views import reviewer_required
from files.models import File
from reviews.forms import ReviewFlagFormSet
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from zadmin.models import get_config, set_config

import mkt.constants.reviewers as rvw
from mkt.developers.models import ActivityLog
from mkt.site.helpers import product_as_dict
from mkt.webapps.models import Webapp

from . import forms
from .models import AppCannedResponse, ThemeLock


QUEUE_PER_PAGE = 100
log = commonware.log.getLogger('z.reviewers')


@reviewer_required
def home(request):
    durations = (('new', _('New Apps (Under 5 days)')),
                 ('med', _('Passable (5 to 10 days)')),
                 ('old', _('Overdue (Over 10 days)')))

    progress, percentage = _progress()

    data = context(
        reviews_total=ActivityLog.objects.total_reviews(webapp=True)[:5],
        reviews_monthly=ActivityLog.objects.monthly_reviews(webapp=True)[:5],
        #new_editors=EventLog.new_editors(),  # Bug 747035
        #eventlog=ActivityLog.objects.editor_events()[:6],  # Bug 746755
        progress=progress,
        percentage=percentage,
        durations=durations
    )
    return jingo.render(request, 'reviewers/home.html', data)


def queue_counts():
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)

    counts = {
        'pending': Webapp.uncached
                         .exclude(id__in=excluded_ids)
                         .filter(type=amo.ADDON_WEBAPP,
                                 disabled_by_user=False,
                                 status=amo.STATUS_PENDING)
                         .count(),
        'rereview': RereviewQueue.uncached
                                 .exclude(addon__in=excluded_ids)
                                 .filter(addon__disabled_by_user=False)
                                 .count(),
        # This will work as long as we disable files of existing unreviewed
        # versions when a new version is uploaded.
        'updates': File.uncached
                       .exclude(version__addon__id__in=excluded_ids)
                       .filter(version__addon__type=amo.ADDON_WEBAPP,
                               version__addon__disabled_by_user=False,
                               version__addon__is_packaged=True,
                               version__addon__status=amo.STATUS_PUBLIC,
                               status=amo.STATUS_PENDING)
                       .count(),
        'escalated': EscalationQueue.uncached
                                    .filter(addon__disabled_by_user=False)
                                    .count(),
        'moderated': Review.uncached.filter(addon__type=amo.ADDON_WEBAPP,
                                            reviewflag__isnull=False,
                                            editorreview=True)
                                    .count(),
        'themes': Persona.objects.no_cache()
                                 .filter(addon__status=amo.STATUS_PENDING)
                                 .count(),
    }
    rv = {}
    if isinstance(type, basestring):
        return counts[type]
    for k, v in counts.items():
        if not isinstance(type, list) or k in type:
            rv[k] = v
    return rv


def _progress():
    """Returns unreviewed apps progress.

    Return the number of apps still unreviewed for a given period of time and
    the percentage.
    """

    days_ago = lambda n: datetime.datetime.now() - datetime.timedelta(days=n)
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (Webapp.uncached.exclude(id__in=excluded_ids)
                         .filter(status=amo.STATUS_PENDING,
                                 disabled_by_user=False))
    progress = {
        'new': qs.filter(created__gt=days_ago(5)).count(),
        'med': qs.filter(created__range=(days_ago(10), days_ago(5))).count(),
        'old': qs.filter(created__lt=days_ago(10)).count(),
        'week': qs.filter(created__gte=days_ago(7)).count(),
    }

    # Return the percent of (p)rogress out of (t)otal.
    pct = lambda p, t: (p / float(t)) * 100 if p > 0 else 0

    percentage = {}
    total = progress['new'] + progress['med'] + progress['old']
    percentage = {}
    for duration in ('new', 'med', 'old'):
        percentage[duration] = pct(progress[duration], total)

    return (progress, percentage)


def context(**kw):
    ctx = dict(motd=get_config('mkt_reviewers_motd'),
               queue_counts=queue_counts())
    ctx.update(kw)
    return ctx


def _review(request, addon):
    version = addon.latest_version

    if not settings.ALLOW_SELF_REVIEWS and addon.has_author(request.amo_user):
        messages.warning(request, _('Self-reviews are not allowed.'))
        return redirect(reverse('reviewers.home'))

    if (addon.status == amo.STATUS_BLOCKED and
        not acl.action_allowed(request, 'Apps', 'ReviewEscalated')):
        messages.warning(
            request, _('Only senior reviewers can review blocklisted apps.'))
        return redirect(reverse('reviewers.home'))

    form = forms.get_review_form(request.POST or None, request=request,
                                 addon=addon, version=version)
    queue_type = form.helper.review_type
    redirect_url = reverse('reviewers.apps.queue_%s' % queue_type)
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')

    if request.method == 'POST' and form.is_valid():

        old_types = set(o.id for o in addon.device_types)
        new_types = set(form.cleaned_data.get('device_override'))

        if (form.cleaned_data.get('action') == 'public' and
            old_types != new_types):

            # The reviewer overrode the device types. We need to not publish
            # this app immediately.
            if addon.make_public == amo.PUBLIC_IMMEDIATELY:
                addon.update(make_public=amo.PUBLIC_WAIT)

            # And update the device types to what the reviewer set.
            AddonDeviceType.objects.filter(addon=addon).delete()
            for device in form.cleaned_data.get('device_override'):
                addon.addondevicetype_set.create(device_type=device)

            # Log that the reviewer changed the device types.
            added_devices = new_types - old_types
            removed_devices = old_types - new_types
            msg = _(u'Device(s) changed by reviewer: {0}').format(', '.join(
                [_(u'Added {0}').format(unicode(amo.DEVICE_TYPES[d].name))
                 for d in added_devices] +
                [_(u'Removed {0}').format(unicode(amo.DEVICE_TYPES[d].name))
                 for d in removed_devices]))
            amo.log(amo.LOG.REVIEW_DEVICE_OVERRIDE, addon,
                    addon.current_version, details={'comments': msg})

        form.helper.process()

        if form.cleaned_data.get('notify'):
            EditorSubscription.objects.get_or_create(user=request.amo_user,
                                                     addon=addon)

        messages.success(request, _('Review successfully processed.'))
        return redirect(redirect_url)

    canned = AppCannedResponse.objects.all()
    actions = form.helper.actions.items()

    try:
        show_diff = (addon.versions.exclude(id=version.id)
                                   .filter(files__isnull=False,
                                           created__lt=version.created,
                                           files__status=amo.STATUS_PUBLIC)
                                   .latest())
    except Version.DoesNotExist:
        show_diff = None

    # The actions we should show a minimal form from.
    actions_minimal = [k for (k, a) in actions if not a.get('minimal')]

    # We only allow the user to check/uncheck files for "pending"
    allow_unchecking_files = form.helper.review_type == "pending"

    versions = (Version.objects.filter(addon=addon)
                               .order_by('-created')
                               .transform(Version.transformer_activity)
                               .transform(Version.transformer))

    product_attrs = {
        'product': json.dumps(
            product_as_dict(request, addon, False, 'developer'),
            cls=JSONEncoder),
        'manifest_url': addon.manifest_url,
    }

    pager = paginate(request, versions, 10)

    num_pages = pager.paginator.num_pages
    count = pager.paginator.count

    ctx = context(version=version, product=addon, pager=pager,
                  num_pages=num_pages, count=count,
                  flags=Review.objects.filter(addon=addon, flag=True),
                  form=form, canned=canned, is_admin=is_admin,
                  status_types=amo.STATUS_CHOICES, show_diff=show_diff,
                  allow_unchecking_files=allow_unchecking_files,
                  actions=actions, actions_minimal=actions_minimal,
                  tab=queue_type, product_attrs=product_attrs)

    return jingo.render(request, 'reviewers/review.html', ctx)


@commit_on_success
@permission_required('Apps', 'Review')
@addon_view
def app_review(request, addon):
    return _review(request, addon)


QueuedApp = collections.namedtuple('QueuedApp', 'app created')


def _queue(request, apps, tab, search_form=None, pager_processor=None):
    per_page = request.GET.get('per_page', QUEUE_PER_PAGE)
    pager = paginate(request, apps, per_page)

    searching, adv_searching = _check_if_searching(search_form)

    return jingo.render(request, 'reviewers/queue.html', context(**{
        'addons': pager.object_list,
        'pager': pager,
        'tab': tab,
        'search_form': search_form,
        'searching': searching,
        'adv_searching': adv_searching,
    }))


def _check_if_searching(search_form):
    """
    Presentation logic for showing 'clear search' and the adv. form.
    Needed to check that the form fields have non-empty value and to say
    that searching on 'text_query' only should not show adv. form.
    """
    searching = False
    adv_searching = False
    for field in search_form:
        if field.data:
            # If filtering, show 'clear search' button.
            searching = True
            if field.name != 'text_query':
                # If filtering by adv fields, don't hide the adv field form.
                adv_searching = True
                break
    return searching, adv_searching


@permission_required('Apps', 'Review')
def queue_apps(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (Webapp.uncached.filter(type=amo.ADDON_WEBAPP,
                                 disabled_by_user=False,
                                 status=amo.STATUS_PENDING)
                         .exclude(id__in=excluded_ids)
                         .order_by('created'))

    qs, search_form = _get_search_form(request, qs)

    apps = [QueuedApp(app, app.created) for app in qs]

    return _queue(request, apps, 'pending', search_form)


@permission_required('Apps', 'Review')
def queue_rereview(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    addon_ids = (RereviewQueue.uncached
                              .filter(addon__type=amo.ADDON_WEBAPP,
                                      addon__disabled_by_user=False)
                              .exclude(addon__in=excluded_ids)
                              .order_by('created')
                              .values_list('addon', flat=True))
    qs = Webapp.objects.filter(id__in=addon_ids)

    qs, search_form = _get_search_form(request, qs)

    apps = [QueuedApp(app, app.created) for app in qs]

    return _queue(request, apps, 'rereview', search_form)


@permission_required('Apps', 'Review')
def queue_updates(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    addon_ids = (File.objects.filter(status=amo.STATUS_PENDING,
                                     version__addon__is_packaged=True,
                                     version__addon__status=amo.STATUS_PUBLIC,
                                     version__addon__type=amo.ADDON_WEBAPP,
                                     version__addon__disabled_by_user=False)
                             .values_list('version__addon_id', flat=True))

    qs = (Webapp.uncached.exclude(id__in=excluded_ids)
                         .filter(id__in=addon_ids))
    qs, search_form = _get_search_form(request, qs)

    apps = Webapp.version_and_file_transformer(qs)

    apps = [QueuedApp(app, app.all_versions[0].all_files[0].created)
            for app in qs]
    apps = sorted(apps, key=lambda a: a.created)
    return _queue(request, apps, 'updates', search_form)


@permission_required('Apps', 'ReviewEscalated')
def queue_escalated(request):
    addon_ids = (EscalationQueue.uncached.filter(addon__type=amo.ADDON_WEBAPP,
                                                 addon__disabled_by_user=False)
                                .order_by('created')
                                .values_list('addon', flat=True))
    qs = Webapp.objects.filter(id__in=addon_ids)

    qs, search_form = _get_search_form(request, qs)

    apps = [QueuedApp(app, app.created) for app in qs]
    return _queue(request, apps, 'escalated', search_form)


@permission_required('Apps', 'Review')
def queue_moderated(request):
    rf = (Review.uncached.exclude(Q(addon__isnull=True) |
                                  Q(reviewflag__isnull=True))
                .filter(addon__type=amo.ADDON_WEBAPP,
                        editorreview=True)
                .order_by('reviewflag__created'))

    page = paginate(request, rf, per_page=20)
    flags = dict(ReviewFlag.FLAGS)
    reviews_formset = ReviewFlagFormSet(request.POST or None,
                                        queryset=page.object_list,
                                        request=request)

    if reviews_formset.is_valid():
        reviews_formset.save()
        return redirect(reverse('reviewers.apps.queue_moderated'))

    return jingo.render(request, 'reviewers/queue.html',
                        context(reviews_formset=reviews_formset,
                                tab='moderated', page=page, flags=flags))


def _get_search_form(request, qs):
    if request.GET:
        search_form = forms.AppQueueSearchForm(request.GET)
        if search_form.is_valid():
            qs = _filter(qs, search_form.cleaned_data)
        return qs, search_form
    else:
        return qs, forms.AppQueueSearchForm(request.GET)


def _filter(qs, data):
    """Handle search filters and queries for app queues."""
    # Turn the form filters into ORM queries and narrow the queryset.
    if data.get('text_query'):
        # icontains match on app name or author username/email.
        text = data['text_query']
        qs = qs.filter(Q(name__localized_string__icontains=text) |
                       Q(authors__username__icontains=text) |
                       Q(authors__email__icontains=text))
    if data.get('admin_review'):
        qs = qs.filter(admin_review=data['admin_review'])
    if data.get('has_editor_comment'):
        qs = qs.filter(_current_version__has_editor_comment=
                       data['has_editor_comment'])
    if data.get('has_info_request'):
        qs = qs.filter(_current_version__has_info_request=
                       data['has_info_request'])
    if data.get('waiting_time_days'):
        dt = (datetime.datetime.today() -
              datetime.timedelta(data['waiting_time_days']))
        qs = qs.filter(created__lte=dt)
    if data.get('device_type_ids', []):
        qs = qs.filter(addondevicetype__device_type__in=
                       data['device_type_ids'])
    if data.get('premium_type_ids', []):
        qs = qs.filter(premium_type__in=data['premium_type_ids'])
    return qs


@permission_required('Apps', 'Review')
def logs(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.ReviewAppLogForm(data)

    approvals = ActivityLog.objects.review_queue(webapp=True)

    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            approvals = approvals.filter(created__gte=data['start'])
        if data.get('end'):
            approvals = approvals.filter(created__lt=data['end'])
        if data.get('search'):
            term = data['search']
            approvals = approvals.filter(
                Q(commentlog__comments__icontains=term) |
                Q(applog__addon__name__localized_string__icontains=term) |
                Q(applog__addon__app_slug__icontains=term) |
                Q(user__display_name__icontains=term) |
                Q(user__username__icontains=term)).distinct()

    pager = paginate(request, approvals, 50)
    data = context(form=form, pager=pager, ACTION_DICT=amo.LOG_BY_ID)
    return jingo.render(request, 'reviewers/logs.html', data)


@reviewer_required
def motd(request):
    form = None
    motd = get_config('mkt_reviewers_motd')
    if acl.action_allowed(request, 'AppReviewerMOTD', 'Edit'):
        form = MOTDForm(request.POST or None, initial={'motd': motd})
    if form and request.method == 'POST' and form.is_valid():
        set_config(u'mkt_reviewers_motd', form.cleaned_data['motd'])
        return redirect(reverse('reviewers.apps.motd'))
    data = context(form=form)
    return jingo.render(request, 'reviewers/motd.html', data)


@permission_required('Apps', 'Review')
@addon_view
@json_view
def app_view_manifest(request, addon):
    if addon.is_packaged:
        version = addon.versions.latest()
        content = json.dumps(json.loads(_mini_manifest(addon, version.id)),
                             indent=4)
        return escape_all({'content': content, 'headers': '', 'success': True})

    else:  # Show the hosted manifest_url.
        content, headers, success = u'', {}, False
        if addon.manifest_url:
            try:
                req = requests.get(addon.manifest_url, verify=False)
                content, headers = req.content, req.headers
                success = True
            except Exception:
                content = u''.join(traceback.format_exception(*sys.exc_info()))

            try:
                # Reindent the JSON.
                content = json.dumps(json.loads(content), indent=4)
            except:
                # If it's not valid JSON, just return the content as is.
                pass
        return escape_all({'content': smart_decode(content),
                           'headers': headers,
                           'success': success})


@permission_required('Apps', 'Review')
@addon_view
def mini_manifest(request, addon, version_id):
    return http.HttpResponse(
        _mini_manifest(addon, version_id),
        content_type='application/x-web-app-manifest+json')


def _mini_manifest(addon, version_id):
    if not addon.is_packaged:
        raise http.Http404

    version = get_object_or_404(addon.versions, pk=version_id)
    file_ = version.all_files[0]
    manifest = addon.get_manifest_json(file_)

    data = {
        'name': addon.name,
        'version': version.version,
        'size': file_.size,
        'release_notes': version.releasenotes,
        'package_path': absolutify(
            reverse('reviewers.signed', args=[addon.app_slug, version.id]))
    }
    if 'icons' in manifest:
        data['icons'] = manifest['icons']
    if 'locales' in manifest:
        data['locales'] = manifest['locales']

    return json.dumps(data, cls=JSONEncoder)


@permission_required('Apps', 'Review')
@addon_view
def app_abuse(request, addon):
    reports = AbuseReport.objects.filter(addon=addon).order_by('-created')
    total = reports.count()
    reports = paginate(request, reports, count=total)
    return jingo.render(request, 'reviewers/abuse.html',
                        context(addon=addon, reports=reports, total=total))


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_queue(request):
    reviewer = request.amo_user
    theme_locks = ThemeLock.objects.filter(reviewer=reviewer)
    theme_locks_count = theme_locks.count()

    if theme_locks_count < rvw.THEME_INITIAL_LOCKS:
        themes = get_themes(
            reviewer, rvw.THEME_INITIAL_LOCKS - theme_locks_count)
    else:
        # Update the expiry on currently checked-out themes.
        theme_locks.update(expiry=get_updated_expiry())
    # Combine currently checked-out themes with newly checked-out ones by
    # re-evaluating theme_locks.
    themes = [theme_lock.theme for theme_lock in theme_locks]

    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(
        initial=[{'theme': theme.id} for theme in themes])

    # By default, redirect back to the queue after a commit.
    request.session['theme_redirect_url'] = reverse('reviewers.themes.'
                                                    'queue_themes')

    return jingo.render(request, 'reviewers/themes/queue.html', context(**{
        'formset': formset,
        'theme_formsets': zip(themes, formset),
        'reject_reasons': rvw.THEME_REJECT_REASONS.items(),
        'theme_count': len(themes),
        'max_locks': rvw.THEME_MAX_LOCKS,
        'more_url': reverse('reviewers.themes.more'),
        'actions': rvw.REVIEW_ACTIONS,
        'reviewable': True,
        'queue_counts': queue_counts(),
        'actions': get_actions_json(),
    }))


def get_themes(reviewer, num):
    # Check out themes from the pool if none or not enough checked out.
    themes = Persona.objects.no_cache().filter(
        addon__status=amo.STATUS_PENDING, themelock=None)[:num]

    # Set a lock on the checked-out themes
    expiry = get_updated_expiry()
    for theme in list(themes):
        ThemeLock.objects.create(theme=theme, reviewer=reviewer,
                                 expiry=expiry)

    # Empty pool? Go look for some expired locks.
    if not themes:
        expired_locks = (ThemeLock.objects.filter(
            expiry__lte=datetime.datetime.now())[:rvw.THEME_INITIAL_LOCKS])
        # Steal expired locks.
        for theme_lock in expired_locks:
            theme_lock.reviewer = reviewer
            theme_lock.expiry = expiry
            theme_lock.save()
            themes = [theme_lock.theme for theme_lock
                      in expired_locks]
    return themes


@waffle_switch('mkt-themes')
@post_required
@reviewer_required('persona')
def themes_commit(request):
    reviewer = request.amo_user
    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(request.POST)

    for form in formset:
        try:
            theme_lock = ThemeLock.objects.filter(
                theme_id=form.data[form.prefix + '-theme'],
                reviewer=reviewer)
        except MultiValueDictKeyError:
            # Address off-by-one error caused by management form.
            continue
        if theme_lock and form.is_valid():
            form.save()

    if 'theme_redirect_url' in request.session:
        return redirect(request.session['theme_redirect_url'])
    else:
        return redirect(reverse('reviewers.themes.queue_themes'))


@json_view
@reviewer_required('persona')
def themes_more(request):
    reviewer = request.amo_user
    theme_locks = ThemeLock.objects.filter(reviewer=reviewer)
    theme_locks_count = theme_locks.count()

    # Maximum number of locks.
    if theme_locks_count >= rvw.THEME_MAX_LOCKS:
        return {
            'themes': [],
            'message': _('You have reached the maximum number of Themes to '
                         'review at once. Please commit your outstanding '
                         'reviews.')}

    # Logic to not take over than the max number of locks. If the next checkout
    # round would cause the reviewer to go over the max, ask for fewer themes
    # from get_themes.
    if theme_locks_count > rvw.THEME_MAX_LOCKS - rvw.THEME_INITIAL_LOCKS:
        wanted_locks = rvw.THEME_MAX_LOCKS - theme_locks_count
    else:
        wanted_locks = rvw.THEME_INITIAL_LOCKS
    themes = get_themes(reviewer, wanted_locks)

    # Create forms, which will need to be manipulated to fit with the currently
    # existing forms.
    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(
        initial=[{'theme': theme.id} for theme in themes])

    html = jingo.render(request, 'reviewers/themes/themes.html', {
        'theme_formsets': zip(themes, formset),
        'max_locks': rvw.THEME_MAX_LOCKS,
        'reviewable': True,
        'initial_count': theme_locks_count
    }).content

    return {'html': html,
            'count': ThemeLock.objects.filter(reviewer=reviewer).count()}


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_single(request, slug):
    """
    Like a detail page, manually review a single theme if it is pending
    and isn't locked.
    """
    reviewer = request.amo_user
    reviewable = True

    # Don't review an already reviewed theme.
    theme = get_object_or_404(Persona, addon__slug=slug)
    if theme.addon.status != amo.STATUS_PENDING:
        reviewable = False

    # Don't review a locked theme (that's not locked to self).
    try:
        theme_lock = theme.themelock
        if (theme_lock.reviewer.id != reviewer.id and
            theme_lock.expiry > datetime.datetime.now()):
            reviewable = False
        elif (theme_lock.reviewer.id != reviewer.id and
              theme_lock.expiry < datetime.datetime.now()):
            # Steal expired lock.
            theme_lock.reviewer = reviewer,
            theme_lock.expiry = get_updated_expiry()
            theme_lock.save()
        else:
            # Update expiry.
            theme_lock.expiry = get_updated_expiry()
            theme_lock.save()
    except ThemeLock.DoesNotExist:
        # Create lock if not created.
        ThemeLock.objects.create(theme=theme, reviewer=reviewer,
                                 expiry=get_updated_expiry())

    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(initial=[{'theme': theme.id}])

    # Since we started the review on the single page, we want to return to the
    # single page rather than get shot back to the queue.
    request.session['theme_redirect_url'] = reverse('reviewers.themes.single',
                                                    args=[theme.addon.slug])

    return jingo.render(request, 'reviewers/themes/single.html', context(**{
        'formset': formset,
        'theme': theme,
        'theme_formsets': zip([theme], formset),
        'theme_reviews': paginate(request, ActivityLog.objects.filter(
            action=amo.LOG.THEME_REVIEW.id,
            _arguments__contains=theme.addon.id)),
        # Setting this to 0 makes sure more themes aren't loaded from more().
        'max_locks': 0,
        'actions': get_actions_json(),
        'theme_count': 1,
        'reviewable': reviewable,
        'reject_reasons': rvw.THEME_REJECT_REASONS.items(),
        'action_dict': rvw.REVIEW_ACTIONS,
    }))


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_logs(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.ReviewAppLogForm(data)

    theme_logs = ActivityLog.objects.filter(
        action=amo.LOG.THEME_REVIEW.id)

    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            theme_logs = theme_logs.filter(created__gte=data['start'])
        if data.get('end'):
            theme_logs = theme_logs.filter(created__lt=data['end'])
        if data.get('search'):
            term = data['search']
            theme_logs = theme_logs.filter(
                Q(_details__icontains=term) |
                Q(user__display_name__icontains=term) |
                Q(user__username__icontains=term)).distinct()

    pager = paginate(request, theme_logs, 30)
    data = context(form=form, pager=pager, ACTION_DICT=rvw.REVIEW_ACTIONS)
    return jingo.render(request, 'reviewers/themes/logs.html', data)


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_history(request, username):
    if not username:
        username = request.amo_user.username

    return jingo.render(request, 'reviewers/themes/history.html', context(**{
        'theme_reviews': paginate(request, ActivityLog.objects.filter(
            action=amo.LOG.THEME_REVIEW.id, user__username=username), 20),
        'user_history': True,
        'username': username,
        'reject_reasons': rvw.THEME_REJECT_REASONS.items(),
        'action_dict': rvw.REVIEW_ACTIONS,
    }))


def get_actions_json():
    return json.dumps({
        'moreinfo': rvw.ACTION_MOREINFO,
        'flag': rvw.ACTION_FLAG,
        'duplicate': rvw.ACTION_DUPLICATE,
        'reject': rvw.ACTION_REJECT,
        'approve': rvw.ACTION_APPROVE,
    })


def get_updated_expiry():
    return (datetime.datetime.now() +
            datetime.timedelta(minutes=rvw.THEME_LOCK_EXPIRY))


@permission_required('Apps', 'Review')
@addon_view
def get_signed_packaged(request, addon, version_id):
    get_object_or_404(addon.versions, pk=version_id)
    path = addon.sign_if_packaged(version_id, reviewer=True)
    if not path:
        raise http.Http404
    log.info('Returning signed package addon: %s, version: %s, path: %s' %
             (addon.pk, version_id, path))
    return HttpResponseSendFile(request, path, content_type='application/zip')


@permission_required('Apps', 'Review')
def performance(request, username=None):

    is_admin = acl.action_allowed(request, 'Admin', '%')

    if username:
        if username == request.amo_user.username:
            user = request.amo_user
        elif is_admin:
            user = get_object_or_404(UserProfile, username=username)
        else:
            raise http.Http404
    else:
        user = request.amo_user

    total = ReviewerScore.get_total(user)
    breakdown = ReviewerScore.get_breakdown(user)

    ctx = context(**{
        'profile': user,
        'total': total,
        'breakdown': breakdown,
    })

    return jingo.render(request, 'reviewers/performance.html', ctx)
