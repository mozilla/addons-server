import os
import subprocess
from itertools import product

import pytest


options = (False, True)
keys = ('DOCKER_VERSION', 'HOST_UID', 'SUPERUSER_EMAIL', 'SUPERUSER_USERNAME')
root_path = os.path.join(os.path.dirname(__file__), '..')
env_path = os.path.join(root_path, '.env')


def clean_env():
    if os.path.exists(env_path):
        os.remove(env_path)

    env_vars = os.environ.copy()
    for key in keys:
        env_vars.pop(key, None)

    return env_vars


def read_env():
    if not os.path.exists(env_path):
        return {}
    with open(env_path) as f:
        return dict(line.split('=') for line in f.read().splitlines())


def run_make_command(name, use_file=False, use_env=False, use_args=False):
    env = clean_env()

    args = ['make', '-f', 'Makefile-os', 'create_env_file']

    if use_file:
        with open(env_path, 'w') as f:
            f.write(f'{name}=file')
    if use_env:
        env[name] = 'env'
    if use_args:
        args.append(f'{name}=args')

    # Debug before running the command
    print(f'name: {name}')
    print(f'use_file: {use_file} use_env: {use_env} use_args: {use_args}')
    print(f'command: {args}')
    print(f'env: {env.get(name, None)}')
    print(f'env_file: {read_env().get(name, None)}')

    command = subprocess.run(
        args, env=env, capture_output=True, text=True, cwd=root_path
    )
    command.check_returncode()

    result = read_env().get(name, None)

    # Debug after running the command
    print(f'result: {result}')

    clean_env()
    return result


default_values = {key: run_make_command(key) for key in keys}


@pytest.mark.parametrize(
    'name,use_file,use_env,use_args',
    [
        (name, use_file, use_env, use_args)
        for name in keys
        for use_file, use_env, use_args in product(options, repeat=3)
    ],
    ids=[
        f'test_permutations_{name}_use_file:{use_file}_use_env:{use_env}_use_args:{use_args}'
        for name in keys
        for use_file, use_env, use_args in product(options, repeat=3)
    ],
)
def test_permutations(name, use_file, use_env, use_args):
    expected_value = default_values.get(name)

    if not expected_value:
        raise ValueError(f'expected_value is None for {name}')

    if use_file:
        expected_value = 'file'
    if use_env:
        expected_value = 'env'
    if use_args:
        expected_value = 'args'

    actual_value = run_make_command(
        name, use_file=use_file, use_env=use_env, use_args=use_args
    )

    assert actual_value == expected_value
