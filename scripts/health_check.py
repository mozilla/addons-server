#!/usr/bin/env python3

import argparse
import json
import time
from enum import Enum
from functools import cached_property

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


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

    @cached_property
    def client(self):
        session = Session()
        retries = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[502, 503, 504],
            allowed_methods={'GET'},
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount(self.environment.value, adapter)
        return session

    def log(self, *args):
        if self.verbose:
            print(*args)

    def _fetch(self, path: str):
        url = f'{self.environment.value}/{path}'
        self.log(f'Requesting {url} for {self.environment.name}')
        response = self.client.get(url, allow_redirects=False)
        data = response.json()
        self.log(json.dumps(data, indent=2))
        return {'url': url, 'data': data}

    def version(self):
        return self._fetch('__version__')

    def monitors(self):
        return self._fetch('services/monitor.json')


def main(env: ENV_ENUM, verbose: bool = False, retries: int = 0, attempt: int = 0):
    fetcher = Fetcher(env, verbose)

    version_data = fetcher.version()
    monitors_data = fetcher.monitors()

    has_failures = any(
        monitor['state'] is False for monitor in monitors_data.get('data', {}).values()
    )

    if has_failures and attempt < retries:
        wait_for = 2**attempt
        if verbose:
            print(f'waiting for {wait_for} seconds')
        time.sleep(wait_for)
        return main(env, verbose, retries, attempt + 1)

    results = {
        'environment': env,
        'version': version_data,
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
