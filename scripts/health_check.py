#!/usr/bin/env python3

import argparse
import http.client
import json
import time
import urllib.error
import urllib.request
import urllib.response
from enum import Enum


ENV_ENUM = Enum(
    'ENV',
    [
        ('dev', 'https://addons-dev.allizom.org'),
        ('stage', 'https://addons.allizom.org'),
        ('prod', 'https://addons.mozilla.org'),
        # For local environments hit the nginx container as set in docker-compose.yml
        ('container', 'http://nginx'),
        ('host', 'http://127.0.0.1:80'),
    ],
)


class Fetcher:
    def __init__(
        self,
        env: ENV_ENUM,
        verbose: bool = False,
        retries: int = 5,
        backoff_factor: float = 0.1,
        status_forcelist: list[int] = None,
    ):
        self.environment = ENV_ENUM[env]
        self.verbose = verbose
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.status_forcelist = status_forcelist or [502, 503, 504]
        self.timeout = 10

    def log(self, *args):
        if self.verbose:
            print(*args)

    def _response(self, response):
        raw_data = response.read()
        encoding = response.info().get_content_charset('utf-8')
        decoded_data = raw_data.decode(encoding)
        data = json.loads(decoded_data)
        self.log(json.dumps(data, indent=2))
        return {'url': response.url, 'data': data}

    def _fetch(self, path: str):
        url = f'{self.environment.value}/{path}'
        last_exception = None

        for attempt in range(1, self.retries + 1):
            self.log(
                f'Attempt {attempt}/{self.retries}: '
                f'Requesting {url} for {self.environment.name}'
            )
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return self._response(response)

            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                TimeoutError,
            ) as e:
                last_exception = e
                should_retry = False
                log_reason = ''

                if isinstance(e, urllib.error.HTTPError):
                    log_reason = f'status {e.code}'
                    try:
                        self.log(
                            f'Request failed with {log_reason}, '
                            'attempting to parse error response body.'
                        )
                        return self._response(e)
                    except (
                        json.decoder.JSONDecodeError,
                        UnicodeDecodeError,
                    ) as parse_error:
                        self.log(f'Failed to parse error response body: {parse_error}')
                        if e.code in self.status_forcelist and attempt < self.retries:
                            should_retry = True
                else:
                    log_reason = str(e)
                    if attempt < self.retries:
                        should_retry = True

                if should_retry:
                    wait_time = self.backoff_factor * (2**attempt)
                    self.log(
                        f'Request failed with {log_reason}. '
                        f'Retrying in {wait_time:.2f} seconds...'
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    self.log(
                        f'Request failed with {log_reason}. '
                        'No more retries or not retryable.'
                    )
                    raise e

            except Exception as e:
                last_exception = e
                self.log(f'An unexpected error occurred: {e}. No more retries.')
                raise e

        raise last_exception or RuntimeError(
            f'Failed to fetch {url} after {self.retries + 1} attempts'
        )

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
            print(
                f'Monitors reported failures. Waiting {wait_for} seconds before '
                f'retrying check (attempt {attempt + 1}/{retries})...'
            )
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
    args.add_argument(
        '--retries',
        type=int,
        default=3,
        help=(
            'Number of times to retry the *entire* health check if monitors report '
            'failures. Default is 3.'
        ),
    )
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
