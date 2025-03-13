from unittest import TestCase

from scripts.health_check_blocks import create_blocks


class TestHealthCheckBlocks(TestCase):
    def setUp(self):
        self.base_data = {
            'version': {
                'data': {'version': '1.0.0'},
                'url': 'http://nginx/__version__',
            },
            'heartbeat': {
                'data': {'heartbeat': {'state': True, 'status': ''}},
                'url': 'http://nginx/__heartbeat__',
            },
            'monitors': {
                'data': {'memcache': {'state': True, 'status': ''}},
                'url': 'http://nginx/services/__heartbeat__',
            },
        }

    def _monitor(self, name: str, state: bool, status: str):
        return {name: {'state': state, 'status': status}}

    def test_no_failing_monitors(self):
        self.assertEqual(
            create_blocks(self.base_data),
            [],
        )

    def test_one_failing_monitor(self):
        data = dict(self.base_data)
        data.update(
            {
                'monitors': {
                    'data': self._monitor('memcache', False, 'Service is down'),
                    'url': 'http://nginx/services/__heartbeat__',
                },
            }
        )
        self.assertEqual(
            create_blocks(data),
            [
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'emoji',
                                    'name': 'x',
                                },
                                {
                                    'type': 'text',
                                    'text': 'Health Check Alert: ',
                                    'style': {'bold': True},
                                },
                                {
                                    'type': 'text',
                                    'text': 'Issues Detected',
                                },
                            ],
                        }
                    ],
                },
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'text',
                                    'text': 'Monitors:',
                                    'style': {
                                        'bold': True,
                                    },
                                }
                            ],
                        },
                        {
                            'type': 'rich_text_list',
                            'elements': [
                                {
                                    'type': 'rich_text_section',
                                    'elements': [
                                        {
                                            'type': 'text',
                                            'text': 'memcache: ',
                                            'style': {
                                                'bold': True,
                                            },
                                        },
                                        {
                                            'type': 'text',
                                            'text': 'Service is down',
                                        },
                                    ],
                                }
                            ],
                            'style': 'bullet',
                            'indent': 0,
                            'border': 1,
                        },
                    ],
                },
                {
                    'type': 'context',
                    'elements': [
                        {'type': 'mrkdwn', 'text': 'Version: 1.0.0 |'},
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/__version__|Version> |',
                        },
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/__heartbeat__|Heartbeat> |',
                        },
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/services/__heartbeat__|Monitors> |',
                        },
                    ],
                },
            ],
        )

    def test_multiple_failing_monitors(self):
        data = dict(self.base_data)
        data.update(
            {
                'heartbeat': {
                    'data': self._monitor('cinder', False, 'cinder is down'),
                    'url': 'http://nginx/__heartbeat__',
                },
                'monitors': {
                    'data': self._monitor('memcache', False, 'Service is down'),
                    'url': 'http://nginx/services/__heartbeat__',
                },
            }
        )
        self.assertEqual(
            create_blocks(data),
            [
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'emoji',
                                    'name': 'x',
                                },
                                {
                                    'type': 'text',
                                    'text': 'Health Check Alert: ',
                                    'style': {'bold': True},
                                },
                                {
                                    'type': 'text',
                                    'text': 'Issues Detected',
                                },
                            ],
                        }
                    ],
                },
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'text',
                                    'text': 'Heartbeat:',
                                    'style': {
                                        'bold': True,
                                    },
                                }
                            ],
                        },
                        {
                            'type': 'rich_text_list',
                            'elements': [
                                {
                                    'type': 'rich_text_section',
                                    'elements': [
                                        {
                                            'type': 'text',
                                            'text': 'cinder: ',
                                            'style': {
                                                'bold': True,
                                            },
                                        },
                                        {
                                            'type': 'text',
                                            'text': 'cinder is down',
                                        },
                                    ],
                                }
                            ],
                            'style': 'bullet',
                            'indent': 0,
                            'border': 1,
                        },
                    ],
                },
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'text',
                                    'text': 'Monitors:',
                                    'style': {
                                        'bold': True,
                                    },
                                }
                            ],
                        },
                        {
                            'type': 'rich_text_list',
                            'elements': [
                                {
                                    'type': 'rich_text_section',
                                    'elements': [
                                        {
                                            'type': 'text',
                                            'text': 'memcache: ',
                                            'style': {
                                                'bold': True,
                                            },
                                        },
                                        {
                                            'type': 'text',
                                            'text': 'Service is down',
                                        },
                                    ],
                                }
                            ],
                            'style': 'bullet',
                            'indent': 0,
                            'border': 1,
                        },
                    ],
                },
                {
                    'type': 'context',
                    'elements': [
                        {'type': 'mrkdwn', 'text': 'Version: 1.0.0 |'},
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/__version__|Version> |',
                        },
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/__heartbeat__|Heartbeat> |',
                        },
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/services/__heartbeat__|Monitors> |',
                        },
                    ],
                },
            ],
        )

    def test_version_with_empty_values(self):
        data = dict(self.base_data)
        data['version'] = {
            'data': {'version': '1.0.0', 'build': '', 'commit': None},
            'url': 'http://nginx/__version__',
        }
        data['monitors'] = {
            'data': self._monitor('memcache', False, 'Service is down'),
            'url': 'http://nginx/services/__heartbeat__',
        }
        self.assertEqual(
            create_blocks(data),
            [
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'emoji',
                                    'name': 'x',
                                },
                                {
                                    'type': 'text',
                                    'text': 'Health Check Alert: ',
                                    'style': {'bold': True},
                                },
                                {
                                    'type': 'text',
                                    'text': 'Issues Detected',
                                },
                            ],
                        }
                    ],
                },
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'text',
                                    'text': 'Monitors:',
                                    'style': {
                                        'bold': True,
                                    },
                                }
                            ],
                        },
                        {
                            'type': 'rich_text_list',
                            'elements': [
                                {
                                    'type': 'rich_text_section',
                                    'elements': [
                                        {
                                            'type': 'text',
                                            'text': 'memcache: ',
                                            'style': {
                                                'bold': True,
                                            },
                                        },
                                        {
                                            'type': 'text',
                                            'text': 'Service is down',
                                        },
                                    ],
                                }
                            ],
                            'style': 'bullet',
                            'indent': 0,
                            'border': 1,
                        },
                    ],
                },
                {
                    'type': 'context',
                    'elements': [
                        {'type': 'mrkdwn', 'text': 'Version: 1.0.0 |'},
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/__version__|Version> |',
                        },
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/__heartbeat__|Heartbeat> |',
                        },
                        {
                            'type': 'mrkdwn',
                            'text': '<http://nginx/services/__heartbeat__|Monitors> |',
                        },
                    ],
                },
            ],
        )

    def test_no_version_data(self):
        data = dict(self.base_data)
        data['version'] = {}
        self.assertEqual(
            create_blocks(data),
            [],
        )
