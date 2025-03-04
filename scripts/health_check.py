#!/usr/bin/env python3

import argparse
import json
from enum import Enum
import time

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
                print({
                    'error': e,
                    'data': data,
                    'response': response,
                })

        if self.verbose and data is not None:
            print(json.dumps(data, indent=2))

        return data

    def version(self):
        return self._fetch('__version__')

    def healthcheck(self):
        return self._fetch('__healthcheck__?verbose=true')


def main(env: ENV_ENUM, verbose: bool = False):
    fetcher = Fetcher(env, verbose)

    version_data = fetcher.version()
    healthcheck_data = fetcher.healthcheck()

    if version_data is None:
        raise ValueError('Error fetching version data')

    if healthcheck_data is None:
        raise ValueError('Error fetching healthcheck data')

    if healthcheck_data is not None:
        if any(monitor['state'] is False for monitor in healthcheck_data.values()):
            raise ValueError(f'Some monitors are failing {healthcheck_data.keys()}')


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
            time.sleep(2 ** attempt)
            attempt += 1
