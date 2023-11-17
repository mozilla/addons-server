from olympia import amo
from olympia.activity import log_create
from olympia.addons.models import Addon
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


class CinderAction:
    description = 'Action has been taken'

    def __init__(self, cinder_report):
        self.cinder_report = cinder_report
        self.abuse_report = cinder_report.abuse_report

    def process(self):
        raise NotImplementedError

    def notify_targets(self, targets):
        # TODO: notify target
        pass

    def notify_reporter(self):
        if self.abuse_report.reporter or self.abuse_report.reporter_email:
            # TODO: notify reporter
            pass


class CinderActionBanUser(CinderAction):
    description = 'Account has been banned'

    def process(self):
        if user := self.abuse_report.user:
            log_create(amo.LOG.ADMIN_USER_BANNED, user)
            UserProfile.ban_and_disable_related_content_bulk([user], move_files=True)
            self.notify_reporter()
            self.notify_targets([user])


class CinderActionDisableAddon(CinderAction):
    description = 'Add-on has been disabled'

    def process(self):
        addon = Addon.unfiltered.filter(guid=self.abuse_report.guid).first()
        if addon and addon.status != amo.STATUS_DISABLED:
            addon.force_disable()
            self.notify_reporter()
            self.notify_targets(addon.authors.all())


class CinderActionEscalateAddon(CinderAction):
    def process(self):
        from olympia.reviewers.models import NeedsHumanReview

        addon = Addon.unfiltered.filter(guid=self.abuse_report.guid).first()
        if addon:
            reason = NeedsHumanReview.REASON_CINDER_ESCALATION
            version_obj = (
                self.abuse_report.addon_version
                and addon.versions(manager='unfiltered_for_relations')
                .filter(version=self.abuse_report.addon_version)
                .no_transforms()
                .first()
            )
            if version_obj:
                NeedsHumanReview.objects.create(
                    version=version_obj, reason=reason, is_active=True
                )
            else:
                addon.set_needs_human_review_on_latest_versions(
                    reason=reason, ignore_reviewed=False, unique_reason=True
                )


class CinderActionDeleteCollection(CinderAction):
    description = 'Collection has been deleted'

    def process(self):
        if collection := self.abuse_report.collection:
            log_create(amo.LOG.COLLECTION_DELETED, collection)
            collection.delete(clear_slug=False)
            self.notify_reporter()
            self.notify_targets([collection.author])


class CinderActionDeleteRating(CinderAction):
    description = 'Rating has been deleted'

    def process(self):
        if rating := self.abuse_report.rating:
            rating.delete(clear_flags=False)
            self.notify_reporter()
            self.notify_targets([rating.user])


class CinderActionApprove(CinderAction):
    description = 'Reported content is within policy'

    def process(self):
        self.notify_reporter()
        target = self.abuse_report.target
        if isinstance(target, Addon) and target.status == amo.STATUS_DISABLED:
            target.force_enable()
            self.notify_targets(target.authors.all())

        elif isinstance(target, UserProfile) and target.banned:
            # TODO: un-ban the user
            self.notify_targets([target])

        elif isinstance(target, Collection) and target.deleted:
            target.undelete()
            log_create(amo.LOG.COLLECTION_UNDELETED, target)
            self.notify_targets([target.author])

        elif isinstance(target, Rating) and target.deleted:
            target.undelete()
            self.notify_targets([target.user])


class CinderActionNotImplemented(CinderAction):
    def process(self):
        pass
