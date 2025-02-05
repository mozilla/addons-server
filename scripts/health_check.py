#!/usr/bin/env python3

import argparse
import json
from enum import Enum

import requests


ENV_ENUM = Enum(
    'ENV',
    [
        ('dev', 'https://addons-dev.allizom.org'),
        ('stage', 'https://addons.allizom.org'),
        ('prod', 'https://addons.mozilla.org'),
        # For local environments hit the nginx container as set in docker-compose.yml
        ('local', 'http://nginx'),
    ],
)


class Fetcher:
    def __init__(self, env: ENV_ENUM, verbose: bool = False):
        self.environment = ENV_ENUM[env]
        self.verbose = verbose

    def _fetch(self, path: str) -> dict[str, str] | None:
        url = f'{self.environment.value}/{path}'
        if self.verbose:
            print(f'Requesting {url} for {self.environment.name}')

        try:
            response = requests.get(url)
            response.raise_for_status()
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                if self.verbose:
                    print(f'Error decoding JSON for {url}: {e}')

        except requests.exceptions.HTTPError as e:
            if self.verbose:
                print(f'Error fetching {url}: {e}')

        if self.verbose and data is not None:
            print(json.dumps(data, indent=2))

        return data

    def version(self):
        if self.environment.name == 'test':
            return {}
        return self._fetch('__version__')

    def monitors(self):
        if self.environment.name == 'test':
            return {
                'up': {'state': True},
                'down': {'state': False, 'status': 'something is wrong'},
            }
        return self._fetch('services/monitor.json')


def main(env: ENV_ENUM, verbose: bool = False, output: str | None = None):
    fetcher = Fetcher(env, verbose)

    version_data = fetcher.version()
    monitors_data = fetcher.monitors()

    if output:
        with open(output, 'w') as f:
            json.dump({'version': version_data, 'monitors': monitors_data}, f, indent=2)
    elif monitors_data is not None:
        if any(monitor['state'] is False for monitor in monitors_data.values()):
            raise ValueError(f'Some monitors are failing {monitors_data}')


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument(
        '--env', type=str, choices=list(ENV_ENUM.__members__.keys()), required=True
    )
    args.add_argument('--verbose', action='store_true')
    args.add_argument('--output', type=str, required=False)
    args = args.parse_args()

    main(args.env, args.verbose, args.output)
