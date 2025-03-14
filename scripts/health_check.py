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

    def _fetch(self, path: str):
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

        if data is None:
            return {}

        if self.verbose:
            print(json.dumps(data, indent=2))

        return {'url': url, 'data': data}

    def version(self):
        return self._fetch('__version__')

    def heartbeat(self):
        return self._fetch('__heartbeat__')

    def monitors(self):
        return self._fetch('services/__heartbeat__')


def main(env: ENV_ENUM, verbose: bool, retries: int = 0, attempt: int = 0):
    fetcher = Fetcher(env, verbose)

    version_data = fetcher.version()
    heartbeat_data = fetcher.heartbeat()
    monitors_data = fetcher.monitors()

    combined_data = {
        'heartbeat': heartbeat_data,
        'monitors': monitors_data,
    }

    has_failures = any(
        monitor['state'] is False
        for data in combined_data.values()
        for monitor in data.get('data', {}).values()
    )

    if has_failures and attempt < retries:
        wait_for = 2**attempt
        if verbose:
            print(f'waiting for {wait_for} seconds')
        time.sleep(wait_for)
        return main(env, verbose, retries, attempt + 1)

    results = {
        'version': version_data,
        'heartbeat': heartbeat_data,
        'monitors': monitors_data,
    }

    return results, has_failures


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument(
        '--env', type=str, choices=list(ENV_ENUM.__members__.keys()), required=True
    )
    args.add_argument('--output', type=str)
    args.add_argument('--verbose', action='store_true')
    args.add_argument('--retries', type=int, default=3)
    args = args.parse_args()

    data, has_failures = main(args.env, args.verbose, args.retries)

    if args.output:
        with open(args.output, 'w') as f:
            json_data = json.dumps(data, indent=2)
            f.write(json_data)
        if args.verbose:
            print(f'Health check data saved to {args.output}')

    if has_failures:
        raise ValueError(f'Health check failed: {data}')
