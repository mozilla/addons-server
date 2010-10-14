import datetime

from django.db import connection, transaction
from django.db.models import Sum, Max

import commonware.log
from celery.decorators import task
from celery.messaging import establish_connection

import amo
from addons.models import Addon
from bandwagon.models import Collection, CollectionAddon
from stats.models import Contribution
from reviews.models import Review
from users.models import UserProfile
from versions.models import Version
from .models import UpdateCount, DownloadCount, AddonCollectionCount

log = commonware.log.getLogger('z.task')


@task
def addon_total_contributions(*addons):
    "Updates the total contributions for a given addon."

    log.info('[%s@%s] Updating total contributions.' %
             (len(addons), addon_total_contributions.rate_limit))
    # Only count uuid=None; those are verified transactions.
    stats = (Contribution.objects.filter(addon__in=addons, uuid=None)
             .values_list('addon').annotate(Sum('amount')))

    for addon, total in stats:
        Addon.objects.filter(id=addon).update(total_contributions=total)


@task(rate_limit='10/m')
def cron_total_contributions(*addons):
    "Rate limited version of `addon_total_contributions` suitable for cron."
    addon_total_contributions(*addons)


@task(rate_limit='10/m')
def update_addons_collections_downloads(data, **kw):
    log.info("[%s@%s] Updating addons+collections download totals." %
                  (len(data), update_addons_collections_downloads.rate_limit))
    for var in data:
        (CollectionAddon.objects.filter(addon=var['addon'],
                                        collection=var['collection'])
                                .update(downloads=var['sum']))


@task(rate_limit='15/m')
def update_collections_total(data, **kw):
    log.info("[%s@%s] Updating collections' download totals." %
                   (len(data), update_collections_total.rate_limit))
    for var in data:
        (Collection.objects.filter(pk=var['collection_id'])
         .update(downloads=var['sum']))


@task(rate_limit='20/h')
def update_global_totals(job, date):
    log.info("[%s] Updating global statistics totals (%s) for (%s)" %
                   (update_global_totals.rate_limit, job, date))

    jobs = _get_daily_jobs()
    jobs.update(_get_metrics_jobs())

    num = jobs[job]()

    q = """REPLACE INTO
                global_stats(`name`, `count`, `date`)
            VALUES
                (%s, %s, %s)"""
    p = [job, num or 0, date]

    cursor = connection.cursor()
    cursor.execute(q, p)
    transaction.commit_unless_managed()


def _get_daily_jobs(date=None):
    """Return a dictionary of statisitics queries.

    If a date is specified and applies to the job it will be used.  Otherwise
    the date will default to today().
    """

    if not date:
        date = datetime.date.today()

    extra = dict(where=['DATE(created)=%s'], params=[date])

    # If you're editing these, note that you are returning a function!  This
    # cheesy hackery was done so that we could pass the queries to celery
    # lazily and not hammer the db with a ton of these all at once.
    stats = {
        # Add-on Downloads
        'addon_total_downloads': lambda: DownloadCount.objects.filter(
                date__lte=date).aggregate(sum=Sum('count'))['sum'],
        'addon_downloads_new': lambda: DownloadCount.objects.filter(
                date=date).aggregate(sum=Sum('count'))['sum'],

        # Add-on counts
        'addon_count_public': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_PUBLIC, inactive=0).count,
        'addon_count_pending': Version.objects.filter(
                created__lte=date, files__status=amo.STATUS_PENDING).count,
        'addon_count_experimental': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_UNREVIEWED,
                inactive=0).count,
        'addon_count_nominated': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_NOMINATED,
                inactive=0).count,
        'addon_count_new': Addon.objects.extra(**extra).count,

        # Version counts
        'version_count_new': Version.objects.extra(**extra).count,

        # User counts
        'user_count_total': UserProfile.objects.filter(
                created__lte=date).count,
        'user_count_new': UserProfile.objects.extra(**extra).count,

        # Review counts
        'review_count_total': Review.objects.filter(created__lte=date,
                                                    editorreview=0).count,
        'review_count_new': Review.objects.filter(editorreview=0).extra(
                **extra).count,

        # Collection counts
        'collection_count_total': Collection.objects.filter(
                created__lte=date).count,
        'collection_count_new': Collection.objects.extra(**extra).count,
        'collection_count_private': Collection.objects.filter(listed=0).count,
        'collection_count_public': Collection.objects.filter(
                created__lte=date, listed=1).count,
        'collection_count_autopublishers': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_SYNCHRONIZED).count,
        'collection_count_editorspicks': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_FEATURED).count,
        'collection_count_normal': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_NORMAL).count,

        'collection_addon_downloads': (lambda:
            AddonCollectionCount.objects.filter(date__lte=date).aggregate(
                sum=Sum('count'))['sum']),
    }

    return stats


def _get_metrics_jobs(date=None):
    """Return a dictionary of statisitics queries.

    If a date is specified and applies to the job it will be used.  Otherwise
    the date will default to the last date metrics put something in the db.
    """

    if not date:
        date = UpdateCount.objects.aggregate(max=Max('date'))['max']

    # If you're editing these, note that you are returning a function!
    stats = {
        'addon_total_updatepings': lambda: UpdateCount.objects.filter(
                date=date).aggregate(sum=Sum('count'))['sum'],
        'collector_updatepings': lambda: UpdateCount.objects.get(
                addon=11950, date=date).count,
    }

    return stats


@task(rate_limit='100/m')
def update_to_json(max_objs=None, classes=(), ids=()):
    """Updates database objects to use JSON instead of phpserialized
    data"""

    def after_max_redo(msg):
        log.info('Completed run: %s' % msg)
        with establish_connection() as conn:
            update_to_json.apply_async(max_objs=max_objs,
                                       connection=conn)

    updater = _JSONUpdater(max_objs, log, after_max_redo,
                           classes=classes, ids=ids)
    updater.run()


class _JSONUpdateMaxedOut(Exception):
    """Raised when _JSONUpdater has reached max_objs"""


class _JSONUpdater(object):
    """Run by update_to_json task (or manage.py convert_stats_to_json)
    to perform the actual update of objects."""

    def __init__(self, max_objs, logger, after_max,
                 classes=(), ids=(), simulate=False):
        self.handled_objs = self.max_objs = max_objs
        self.logger = logger
        self.after_max = after_max
        self.classes = classes
        self.ids = ids
        self.simulate = simulate

    def run(self):
        try:
            self.update_all_models()
        except _JSONUpdateMaxedOut, e:
            if self.after_max is not None:
                self.after_max(str(e))

    def stub_out_tasks(self):
        """There's a post-save hook that sends something to amqp, but for
        this case this isn't useful or important."""
        from stats import tasks

        def null(*addons):
            pass

        null.delay = null
        tasks.addon_total_contributions = null

    def report(self, msg):
        self.logger.debug(msg)

    def obj_handled(self):
        if self.handled_objs is not None:
            self.handled_objs -= 1
            if not self.handled_objs:
                raise _JSONUpdateMaxedOut(
                    'Reached maximum number of objects (%s)'
                    % self.max_objs)

    def all_models(self):
        """Returns all model classes"""
        from stats import models
        from django.db.models import Model
        for name in dir(models):
            obj = getattr(models, name)
            if isinstance(obj, type) and issubclass(obj, Model):
                if self.classes and obj.__name__ not in self.classes:
                    self.report('Skipping model %s' % obj)
                    continue
                yield obj

    def models_with_stats_dict(self, classes=None):
        """Returns (model, field_name) for all models that have a StatsDictField"""
        from stats.models import StatsDictField
        if classes is None:
            classes = self.all_models()
        for model in classes:
            for field in model._meta.fields:
                if isinstance(field, StatsDictField):
                    yield (model, field.name)

    def update_objs(self, model, field_name):
        """Update all the objects for this model and field name.

        This selects all the objects with non-JSON fields, then resaves
        the object, and saves it.
        """
        import decimal
        kw1 = {'%s__startswith' % field_name: '{'}
        kw2 = {'%s__startswith' % field_name: '['}
        kw3 = {field_name: None}
        kw4 = {'%s__exact' % field_name: ''}
        qs = model.objects.exclude(**kw1)
        qs = qs.exclude(**kw2)
        qs = qs.exclude(**kw3)
        qs = qs.exclude(**kw4)
        if self.ids:
            qs = qs.filter(addon__in=self.ids)
        if self.handled_objs is not None:
            qs = qs[:self.handled_objs]
        self.report(str(qs.query))
        any_objs = False
        for obj in qs:
            any_objs = True
            try:
                value = getattr(obj, field_name)
                if not value:
                    continue
                self.obj_handled()
                if self.simulate:
                    return
                setattr(obj, field_name, value)
                try:
                    obj.save()
                except Exception, e:
                    self.report('Object %s(%s) is invalid' % (model.__name__, obj.id))
                    continue
                if self.max_objs is not None:
                    self.report('Updated %s(%s).%s (%8i/%s)'
                                % (model.__name__, obj.id, field_name, self.max_objs - self.handled_objs, self.max_objs))
                else:
                    self.report('Update %s(%s).%s'
                                % (model.__name__, obj.id, field_name))
            except decimal.InvalidOperation, e:
                # There are occasional objects that cause decimal errors
                self.report('Encountered bad object in %s: %s' % (model.__name__, e))
        if not any_objs:
            self.report('No %s updating needed' % model.__name__)

    def update_all_models(self):
        """Updates all the records from all the models"""
        self.stub_out_tasks()
        all_models = list(self.models_with_stats_dict())
        for count, (model, field_name) in enumerate(all_models):
            self.report('Updating model %s.%s (%s/%s)'
                        % (model.__name__, field_name, count + 1, len(all_models)))
            self.update_objs(model, field_name)
