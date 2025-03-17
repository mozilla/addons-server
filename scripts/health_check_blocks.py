#!/usr/bin/env python3

import argparse
import json


def format_monitors(data: dict, source: str):
    monitors = data['data']
    failures = []

    for name, monitor in monitors.items():
        if not monitor['state']:
            failures.append(
                {
                    'type': 'rich_text_section',
                    'elements': [
                        {
                            'type': 'text',
                            'text': f'{name}: ',
                            'style': {
                                'bold': True,
                            },
                        },
                        {
                            'type': 'text',
                            'text': f'{monitor["status"]}',
                        },
                    ],
                }
            )

    if failures:
        return {
            'type': 'rich_text',
            'elements': [
                {
                    'type': 'rich_text_section',
                    'elements': [
                        {
                            'type': 'text',
                            'text': f'{source.capitalize()}:',
                            'style': {
                                'bold': True,
                            },
                        }
                    ],
                },
                {
                    'type': 'rich_text_list',
                    'elements': failures,
                    'style': 'bullet',
                    'indent': 0,
                    'border': 1,
                },
            ],
        }


def format_context(data: dict):
    version_data = data.get('version', {}).get('data', {})
    version_elements = [
        {'type': 'mrkdwn', 'text': f'{key.capitalize()}: {value} |'}
        for key, value in version_data.items()
        if value and key in ['version', 'commit', 'build']
    ]
    url_elements = [
        {'type': 'mrkdwn', 'text': f'<{data["url"]}|{name.capitalize()}> |'}
        for name, data in data.items()
    ]
    return {'type': 'context', 'elements': version_elements + url_elements}


def format_header(emoji: str, text: setattr):
    return {
        'type': 'rich_text',
        'elements': [
            {
                'type': 'rich_text_section',
                'elements': [
                    {
                        'type': 'emoji',
                        'name': emoji,
                    },
                    {
                        'type': 'text',
                        'text': 'Health Check Alert: ',
                        'style': {'bold': True},
                    },
                    {
                        'type': 'text',
                        'text': text,
                    },
                ],
            }
        ],
    }


def create_blocks(health_data: dict):
    """Create a Slack message from health check data."""
    failing_monitors = []

    for name, data in health_data.items():
        if name in ['monitors', 'heartbeat']:
            if monitors := format_monitors(data, name):
                failing_monitors.append(monitors)

    if not failing_monitors:
        return []

    return [
        format_header('x', 'Issues Detected'),
        *failing_monitors,
        format_context(health_data),
    ]


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--input', type=str, required=True)
    args.add_argument('--output', type=str, required=True)
    args.add_argument('--verbose', action='store_true')

    args = args.parse_args()

    with open(args.input) as f:
        health_data = json.load(f)

    if args.verbose:
        print(f'Health data loaded from {args.input}')

    blocks = create_blocks(health_data)
    with open(args.output, 'w') as f:
        json.dump(blocks, f)

    if args.verbose:
        print(f'Blocks saved to {args.output}')


if __name__ == '__main__':
    main()
