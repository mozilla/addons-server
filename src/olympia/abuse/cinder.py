import mimetypes

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.functional import classproperty

import requests
import waffle

import olympia
from olympia import activity, amo, core
from olympia.amo.utils import (
    backup_storage_enabled,
    chunked,
    copy_file_to_backup_storage,
    create_signed_url_for_file_backup,
)
from olympia.users.utils import get_task_user


log = olympia.core.logger.getLogger('z.abuse')


class CinderEntity:
    queue_suffix = None  # Needs to be defined by subclasses
    type = None  # Needs to be defined by subclasses
    # Number of relationships to send by default in each Cinder request.
    RELATIONSHIPS_BATCH_SIZE = 25

    @property
    def queue(self):
        return f'{settings.CINDER_QUEUE_PREFIX}{self.queue_suffix}'

    @property
    def id(self):
        # Ideally override this in subclasses to be more efficient
        return self.get_str(self.get_attributes().get('id', ''))

    def get_str(self, field_content):
        return str(field_content or '').strip()

    def get_attributes(self):
        raise NotImplementedError

    def get_context_generator(self):
        raise NotImplementedError

    def get_empty_context(self):
        return {'entities': [], 'relationships': []}

    def get_entity_data(self):
        return {'entity_type': self.type, 'attributes': self.get_attributes()}

    def get_relationship_data(self, to, relationship_type):
        return {
            'source_id': self.id,
            'source_type': self.type,
            'target_id': to.id,
            'target_type': to.type,
            'relationship_type': relationship_type,
        }

    def get_extended_attributes(self):
        # Extended attributes are only returned with reports (not as part of
        # relationships or reporter data for instance) as they require as they
        # are more expensive to compute. Media that we need to make a copy of
        # are typically returned there instead of in get_attributes().
        return {}

    def get_cinder_http_headers(self):
        return {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }

    def build_report_payload(self, *, report, reporter):
        generator = self.get_context_generator()
        context = next(generator, self.get_empty_context())
        if report:
            context['entities'] += [report.get_entity_data()]
            context['relationships'] += [
                report.get_relationship_data(self, 'amo_report_of')
            ]
            if reporter:
                reporter_entity_data = reporter.get_entity_data()
                # Avoid duplicate entities: the reporter could be reporting
                # themselves or an add-on they are an author of, for instance.
                if reporter_entity_data not in context['entities']:
                    context['entities'] += [reporter.get_entity_data()]
                context['relationships'] += [
                    reporter.get_relationship_data(report, 'amo_reporter_of')
                ]
            message = report.abuse_report.message
        else:
            message = ''
        entity_attributes = {**self.get_attributes(), **self.get_extended_attributes()}
        return {
            'queue_slug': self.queue,
            'entity_type': self.type,
            'entity': entity_attributes,
            'reasoning': self.get_str(message),
            'context': context,
        }

    def report(self, *, report, reporter):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}create_report'
        data = self.build_report_payload(report=report, reporter=reporter)
        response = requests.post(url, json=data, headers=self.get_cinder_http_headers())
        if response.status_code == 201:
            return response.json().get('job_id')
        else:
            raise ConnectionError(response.content)

    def report_additional_context(self):
        context_generator = self.get_context_generator()
        # This is a new generator, so advance it once to avoid re-sending the
        # context already sent as part of the report.
        next(context_generator, {})

        for data in context_generator:
            # Note: Cinder URLS are inconsistent. Per their documentation, that
            # one needs a trailing slash.
            url = f'{settings.CINDER_SERVER_URL}graph/'
            response = requests.post(
                url, json=data, headers=self.get_cinder_http_headers()
            )
            if response.status_code != 202:
                raise ConnectionError(response.content)

    def appeal(self, *, decision_cinder_id, appeal_text, appealer):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}appeal'
        data = {
            'queue_slug': self.queue,
            'appealer_entity_type': appealer.type,
            'appealer_entity': appealer.get_attributes(),
            'reasoning': self.get_str(appeal_text),
            'decision_to_appeal_id': decision_cinder_id,
        }
        response = requests.post(url, json=data, headers=self.get_cinder_http_headers())
        if response.status_code == 201:
            return response.json().get('external_id')
        else:
            raise ConnectionError(response.content)

    def _send_create_decision(self, url, data, action, reasoning, policy_uuids):
        data = {
            **data,
            'reasoning': self.get_str(reasoning),
            'policy_uuids': policy_uuids,
            'enforcement_actions_slugs': [action],
            'enforcement_actions_update_strategy': 'set',
        }
        response = requests.post(url, json=data, headers=self.get_cinder_http_headers())
        if response.status_code == 201:
            return response.json().get('uuid')
        else:
            raise ConnectionError(response.content)

    def create_decision(self, *, action, reasoning, policy_uuids):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}create_decision'
        data = {
            'entity_type': self.type,
            'entity': self.get_attributes(),
        }
        return self._send_create_decision(url, data, action, reasoning, policy_uuids)

    def create_job_decision(self, *, action, reasoning, policy_uuids, job_id):
        url = f'{settings.CINDER_SERVER_URL}jobs/{job_id}/decision'
        return self._send_create_decision(url, {}, action, reasoning, policy_uuids)

    def close_job(self, *, job_id):
        url = f'{settings.CINDER_SERVER_URL}jobs/{job_id}/cancel'
        response = requests.post(url, headers=self.get_cinder_http_headers())
        if response.status_code == 200:
            return response.json().get('external_id')
        else:
            raise ConnectionError(response.content)


class CinderUser(CinderEntity):
    type = 'amo_user'
    queue_suffix = 'users'

    def __init__(self, user):
        self.user = user
        self.related_addons = (
            self.user.addons.all().only_translations().select_related('promotedaddon')
        )

    @property
    def id(self):
        return self.get_str(self.user.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'created': self.get_str(self.user.created),
            'email': self.user.email,
            'fxa_id': self.user.fxa_id,
            'name': self.user.display_name,
        }

    def get_extended_attributes(self):
        data = {}
        if (
            self.user.picture_type
            and backup_storage_enabled()
            and storage.exists(self.user.picture_path)
        ):
            filename = copy_file_to_backup_storage(
                self.user.picture_path, self.user.picture_type
            )
            data['avatar'] = {
                'value': create_signed_url_for_file_backup(filename),
                'mime_type': self.user.picture_type,
            }
        data.update(
            {
                'average_rating': self.user.averagerating,
                'num_addons_listed': self.user.num_addons_listed,
                'biography': self.get_str(self.user.biography),
                'homepage': self.get_str(self.user.homepage) or None,
                'location': self.get_str(self.user.location),
                'occupation': self.get_str(self.user.occupation),
            }
        )
        return data

    def get_context_generator(self):
        cinder_addons = [CinderAddon(addon) for addon in self.related_addons]
        for chunk in chunked(cinder_addons, self.RELATIONSHIPS_BATCH_SIZE):
            yield {
                'entities': [cinder_addon.get_entity_data() for cinder_addon in chunk],
                'relationships': [
                    self.get_relationship_data(cinder_addon, 'amo_author_of')
                    for cinder_addon in chunk
                ],
            }


class CinderUnauthenticatedReporter(CinderEntity):
    type = 'amo_unauthenticated_reporter'

    def __init__(self, name, email):
        self.name = name
        self.email = email

    def get_attributes(self):
        return {
            'id': f'{self.name} : {self.email}',
            'name': self.name,
            'email': self.email,
        }

    def report(self, *args, **kwargs):
        # It doesn't make sense to report a non fxa user
        raise NotImplementedError

    def appeal(self, *args, **kwargs):
        # It doesn't make sense to report a non fxa user
        raise NotImplementedError


class CinderAddon(CinderEntity):
    type = 'amo_addon'

    def __init__(self, addon, version=None):
        self.addon = addon
        self.version = version
        self.related_users = self.addon.authors.all()

    @property
    def id(self):
        return self.get_str(self.addon.id)

    @property
    def queue_suffix(self):
        return 'themes' if self.addon.type == amo.ADDON_STATICTHEME else 'listings'

    def get_attributes(self):
        # We look at the promoted group to tell whether or not the add-on is
        # promoted in any way, but we don't care about the promotion being
        # approved for the current version, it would make more queries and it's
        # not useful for moderation purposes anyway.
        promoted_group = self.addon.promoted_group(currently_approved=False)
        data = {
            'id': self.id,
            'average_daily_users': self.addon.average_daily_users,
            'created': self.get_str(self.addon.created),
            'guid': self.addon.guid,
            'last_updated': self.get_str(self.addon.last_updated) or None,
            'name': self.get_str(self.addon.name),
            'slug': self.addon.slug,
            'summary': self.get_str(self.addon.summary),
            'promoted': self.get_str(promoted_group.name if promoted_group else ''),
        }
        return data

    def get_extended_attributes(self):
        data = {}
        if backup_storage_enabled():
            if self.addon.icon_type:
                icon_size = max(amo.ADDON_ICON_SIZES)
                icon_type, _ = mimetypes.guess_type(f'icon.{amo.ADDON_ICON_FORMAT}')
                icon_path = self.addon.get_icon_path(icon_size)
                if icon_type and storage.exists(icon_path):
                    filename = copy_file_to_backup_storage(icon_path, icon_type)
                    data['icon'] = {
                        'value': create_signed_url_for_file_backup(filename),
                        'mime_type': icon_type,
                    }
            previews = []
            for preview in self.addon.current_previews:
                if (
                    self.addon.type == amo.ADDON_STATICTHEME
                    and preview.position
                    != amo.THEME_PREVIEW_RENDERINGS['amo']['position']
                ):
                    # For themes, we automatically generate 2 previews with
                    # different sizes and format, we only need to expose one.
                    continue
                content_type, _ = mimetypes.guess_type(preview.thumbnail_path)
                if content_type and storage.exists(preview.thumbnail_path):
                    filename = copy_file_to_backup_storage(
                        preview.thumbnail_path, content_type
                    )
                    previews.append(
                        {
                            'value': create_signed_url_for_file_backup(filename),
                            'mime_type': content_type,
                        }
                    )
            if previews:
                data['previews'] = previews

        # Those fields are only shown on the detail page, so we only have them
        # in extended attributes to avoid sending them when we send an add-on
        # as a related entity to something else.
        data['description'] = self.get_str(self.addon.description)
        if self.addon.current_version:
            data['version'] = self.get_str(self.addon.current_version.version)
            data['release_notes'] = self.get_str(
                self.addon.current_version.release_notes
            )
        data['privacy_policy'] = self.get_str(self.addon.privacy_policy)
        # The URL/email fields can't be sent as empty strings as they would not
        # be considered valid by Cinder.
        data['homepage'] = self.get_str(self.addon.homepage) or None
        data['support_email'] = self.get_str(self.addon.support_email) or None
        data['support_url'] = self.get_str(self.addon.support_url) or None
        return data

    def get_context_generator(self):
        cinder_users = [CinderUser(author) for author in self.related_users]
        for chunk in chunked(cinder_users, self.RELATIONSHIPS_BATCH_SIZE):
            yield {
                'entities': [cinder_user.get_entity_data() for cinder_user in chunk],
                'relationships': [
                    cinder_user.get_relationship_data(self, 'amo_author_of')
                    for cinder_user in chunk
                ],
            }


class CinderRating(CinderEntity):
    type = 'amo_rating'
    queue_suffix = 'ratings'

    def __init__(self, rating):
        self.rating = rating

    @property
    def id(self):
        return self.get_str(self.rating.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'body': self.rating.body,
            'created': self.get_str(self.rating.created),
            'score': self.rating.rating,
        }

    def get_context_generator(self):
        # Note: we are not currently sending the add-on the rating is for as
        # part of the context.
        cinder_user = CinderUser(self.rating.user)
        context = {
            'entities': [cinder_user.get_entity_data()],
            'relationships': [
                cinder_user.get_relationship_data(self, 'amo_rating_author_of'),
            ],
        }
        if reply_to := getattr(self.rating, 'reply_to', None):
            cinder_reply_to = CinderRating(reply_to)
            context['entities'].append(cinder_reply_to.get_entity_data())
            context['relationships'].append(
                cinder_reply_to.get_relationship_data(self, 'amo_rating_reply_to')
            )
        yield context


class CinderCollection(CinderEntity):
    type = 'amo_collection'
    queue_suffix = 'collections'

    def __init__(self, collection):
        self.collection = collection

    @property
    def id(self):
        return self.get_str(self.collection.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'comments': self.collection.get_all_comments(),
            'created': self.get_str(self.collection.created),
            'description': self.get_str(self.collection.description),
            'modified': self.get_str(self.collection.modified),
            'name': self.get_str(self.collection.name),
            'slug': self.collection.slug,
        }

    def get_context_generator(self):
        cinder_user = CinderUser(self.collection.author)
        yield {
            'entities': [cinder_user.get_entity_data()],
            'relationships': [
                cinder_user.get_relationship_data(self, 'amo_collection_author_of')
            ],
        }


class CinderAddonHandledByReviewers(CinderAddon):
    # This queue is not monitored on cinder - reports are resolved via AMO instead
    queue_suffix = 'addon-infringement'

    @classproperty  # Special case, needs to be static for the webhook check.
    def queue(cls):
        return f'{settings.CINDER_QUEUE_PREFIX}{cls.queue_suffix}'

    def flag_for_human_review(self, appeal=False):
        from olympia.reviewers.models import NeedsHumanReview

        waffle_switch_name = (
            'dsa-appeals-review' if appeal else 'dsa-abuse-reports-review'
        )
        if not waffle.switch_is_active(waffle_switch_name):
            log.info(
                'Not adding %s to review queue despite %s because %s switch is off',
                self.addon,
                'appeal' if appeal else 'report',
                waffle_switch_name,
            )
            return

        reason = (
            NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL
            if appeal
            else NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )
        nhr_object = NeedsHumanReview(
            version=self.version, reason=reason, is_active=True
        )
        if self.version:
            if not NeedsHumanReview.objects.filter(
                version=self.version, reason=reason, is_active=True
            ).exists():
                nhr_object.save(_no_automatic_activity_log=True)
                versions_to_log = [self.version]
            else:
                versions_to_log = []
        else:
            versions_to_log = self.addon.set_needs_human_review_on_latest_versions(
                reason=reason,
                ignore_reviewed=False,
                unique_reason=True,
                skip_activity_log=True,
            )
        if versions_to_log:
            activity.log_create(
                amo.LOG.NEEDS_HUMAN_REVIEW_CINDER,
                *versions_to_log,
                details={'comments': nhr_object.get_reason_display()},
                user=core.get_user() or get_task_user(),
            )

    def report(self, *args, **kwargs):
        self.flag_for_human_review(appeal=False)
        return super().report(*args, **kwargs)

    def appeal(self, *args, **kwargs):
        self.flag_for_human_review(appeal=True)
        return super().appeal(*args, **kwargs)


class CinderReport(CinderEntity):
    type = 'amo_report'

    def __init__(self, abuse_report):
        self.abuse_report = abuse_report

    @property
    def id(self):
        return self.get_str(self.abuse_report.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'created': self.get_str(self.abuse_report.created),
            'reason': self.abuse_report.get_reason_display()
            if self.abuse_report.reason
            else None,
            'message': self.get_str(self.abuse_report.message),
            'locale': self.abuse_report.application_locale,
            # We need a boolean to expose specifically if the reporter
            # considered the content illegal, as that needs to be reflected in
            # the SOURCE_TYPE in the transparency database.
            'considers_illegal': self.abuse_report.reason
            == self.abuse_report.REASONS.ILLEGAL,
        }

    def report(self, *args, **kwargs):
        # It doesn't make sense to report this, it's just meant to be included
        # as a relationship.
        raise NotImplementedError

    def appeal(self, *args, **kwargs):
        # It doesn't make sense to report this, it's just meant to be included
        # as a relationship.
        raise NotImplementedError
