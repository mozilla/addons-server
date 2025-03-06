#!/usr/bin/env python3

import argparse
import json
import time
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

        data = None
        # We return 500 if any of the monitors are failing.
        # So instead of raising, we should try to form valid JSON
        # and determine if we should raise later based on the json values.
        try:
            response = requests.get(url, allow_redirects=False)
            data = response.json()
        except (requests.exceptions.HTTPError, json.JSONDecodeError) as e:
            if self.verbose:
                print(
                    {
                        'error': e,
                        'data': data,
                        'response': response,
                    }
                )

        if self.verbose and data is not None:
            print(json.dumps(data, indent=2))

        return data

    def version(self):
        return self._fetch('__version__')

    def heartbeat(self):
        return self._fetch('__heartbeat__')

    def monitors(self):
        return self._fetch('services/__heartbeat__')


def main(env: ENV_ENUM, verbose: bool = False):
    fetcher = Fetcher(env, verbose)

    version_data = fetcher.version()
    heartbeat_data = fetcher.heartbeat()
    monitors_data = fetcher.monitors()

    if version_data is None:
        raise ValueError('Error fetching version data')

    if heartbeat_data is None:
        raise ValueError('Error fetching heartbeat data')

    if monitors_data is None:
        raise ValueError('Error fetching monitors data')

    combined_data = {**heartbeat_data, **monitors_data}
    failing_monitors = [
        name for name, monitor in combined_data.items() if monitor['state'] is False
    ]

    if len(failing_monitors) > 0:
        raise ValueError(f'Some monitors are failing {failing_monitors}')


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument(
        '--env', type=str, choices=list(ENV_ENUM.__members__.keys()), required=True
    )
    args.add_argument('--verbose', action='store_true')
    args.add_argument('--retries', type=int, default=3)
    args = args.parse_args()

    attempt = 1

    while attempt <= args.retries:
        try:
            main(args.env, args.verbose)
            break
        except Exception as e:
            print(f'Error: {e}')
            if attempt == args.retries:
                raise
            time.sleep(2**attempt)
            attempt += 1
