from django.conf import settings

import requests


class Cinder:
    QUEUE = 'amo-content-infringement'
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

    def build_report_payload(self, reason, reporter):
        context = self.get_context()
        if reporter:
            context['entities'] += [reporter.get_entity_data()]
            context['relationships'] += [
                reporter.get_relationship_data(self, 'amo_reporter_of')
            ]
        return {
            'queue_slug': self.QUEUE,
            'entity_type': self.type,
            'entity': self.get_attributes(),
            'reasoning': reason,
            # 'report_metadata': ??
            'context': context,
        }

    def report(self, reason, reporter_user):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        reporter = (
            reporter_user
            and not reporter_user.is_anonymous()
            and CinderUser(reporter_user)
        )
        url = f'{settings.CINDER_SERVER_URL}create_report'
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }
        data = self.build_report_payload(reason, reporter)
        print(data)
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            return response.json().get('job_id')
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
