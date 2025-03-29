#!/usr/bin/env python3

import argparse
import json


def format_monitors(data: dict):
    monitors = data.get('monitors', {}).get('data', {})

    return [
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
        for name, monitor in monitors.items()
        if not monitor['state']
    ]


def format_context(data: dict):
    elements = [
        f'<{data["url"]}|{name.capitalize()}>'
        for name, data in data.items()
        if name in ['version', 'monitors']
    ] + [
        f'{key}: {value}'
        for key, value in data.get('version', {}).get('data', {}).items()
        if value and key in ['version', 'commit']
    ]

    return {
        'type': 'context',
        'elements': [
            {
                'type': 'mrkdwn',
                'text': element,
            }
            for element in elements
        ],
    }


def format_header(emoji: str, environment: str):
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
                        'text': f' [{environment}] ',
                        'style': {'bold': True},
                    },
                    {
                        'type': 'text',
                        'text': 'Some health checks are failing!',
                    },
                ],
            }
        ],
    }


def create_blocks(health_data: dict):
    """Create a Slack message from health check data."""
    if len(failures := format_monitors(health_data)) == 0:
        return []

    return [
        format_header('x', health_data['environment']),
        format_context(health_data),
        {
            'type': 'divider',
        },
        {
            'type': 'rich_text',
            'elements': [
                {
                    'type': 'rich_text_list',
                    'elements': failures,
                    'style': 'bullet',
                    'indent': 0,
                    'border': 1,
                },
            ],
        },
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
