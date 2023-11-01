from django.conf import settings

import requests


class Cinder:
    # This queue is for reports that T&S / TaskUs look at
    queue = 'amo-content-infringement'
    type = None  # Needs to be defined by subclasses

    @property
    def id(self):
        # Ideally override this in subclasses to be more efficient
        return str(self.get_attributes().get('id', ''))

    def get_attributes(self):
        raise NotImplementedError

    def get_context(self):
        raise NotImplementedError

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

    def build_report_payload(self, *, report_text, category, reporter):
        context = self.get_context()
        if reporter:
            context['entities'] += [reporter.get_entity_data()]
            context['relationships'] += [
                reporter.get_relationship_data(self, 'amo_reporter_of')
            ]
        return {
            'queue_slug': self.queue,
            'entity_type': self.type,
            'entity': self.get_attributes(),
            'reasoning': report_text,
            # FIXME: pass category in report_metadata ?
            # 'report_metadata': ??
            'context': context,
        }

    def report(self, *, report_text, category, reporter):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}create_report'
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }
        data = self.build_report_payload(
            report_text=report_text, category=category, reporter=reporter
        )
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            return response.json().get('job_id')
        else:
            raise ConnectionError(response.content)

    def appeal(self, *, decision_id, appeal_text, appealer):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}appeal'
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }
        data = {
            'queue_slug': self.queue,
            'appealer_entity_type': appealer.type,
            'appealer_entity': appealer.get_attributes(),
            'reasoning': appeal_text,
            'decision_to_appeal_id': decision_id,
        }
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            return response.json().get('external_id')
        else:
            raise ConnectionError(response.content)


class CinderUser(Cinder):
    type = 'amo_user'

    def __init__(self, user):
        self.user = user

    @property
    def id(self):
        return str(self.user.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'name': self.user.display_name,
            'email': self.user.email,
            'fxa_id': self.user.fxa_id,
        }

    def get_context(self):
        addons = [CinderAddon(addon) for addon in self.user.addons.all()]
        return {
            'entities': [addon.get_entity_data() for addon in addons],
            'relationships': [
                self.get_relationship_data(addon, 'amo_author_of') for addon in addons
            ],
        }


class CinderUnauthenticatedReporter(Cinder):
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

    def get_context(self):
        return {}

    def report(self, *args, **kwargs):
        # It doesn't make sense to report a non fxa user
        raise NotImplementedError

    def appeal(self, *args, **kwargs):
        # It doesn't make sense to report a non fxa user
        raise NotImplementedError


class CinderAddon(Cinder):
    type = 'amo_addon'

    def __init__(self, addon):
        self.addon = addon

    @property
    def id(self):
        return str(self.addon.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'guid': self.addon.guid,
            'slug': self.addon.slug,
            'name': str(self.addon.name),
        }

    def get_context(self):
        authors = [CinderUser(author) for author in self.addon.authors.all()]
        return {
            'entities': [author.get_entity_data() for author in authors],
            'relationships': [
                author.get_relationship_data(self, 'amo_author_of')
                for author in authors
            ],
        }


class CinderAddonByReviewers(CinderAddon):
    # This queue is not monitored on cinder - reports are resolved via AMO instead
    queue = 'amo-addon-infringement'

    def flag_for_human_review(self, appeal=False):
        from olympia.reviewers.models import NeedsHumanReview

        reason = (
            NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION_APPEAL
            if appeal
            else NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION
        )
        self.addon.set_needs_human_review_on_latest_versions(reason=reason)

    def report(self, *args, **kwargs):
        self.flag_for_human_review(appeal=False)
        return super().report(*args, **kwargs)

    def appeal(self, *args, **kwargs):
        self.flag_for_human_review(appeal=True)
        return super().appeal(*args, **kwargs)
