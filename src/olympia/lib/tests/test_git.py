import os
import subprocess

import pytest

from django.conf import settings

from olympia import amo
from olympia.amo.tests import addon_factory, version_factory, user_factory
from olympia.lib.git import AddonGitRepository, TemporaryWorktree


def test_temporary_worktree():
    repo = AddonGitRepository(1)

    env = {'GIT_DIR': repo.git_repository.path}

    output = subprocess.check_output('git worktree list', shell=True, env=env)
    assert output.startswith(repo.git_repository.path)

    with TemporaryWorktree(repo.git_repository) as worktree:
        assert worktree.temp_directory.startswith(settings.TMP_PATH)
        assert worktree.path == os.path.join(
            worktree.temp_directory, worktree.name)

        output = subprocess.check_output(
            'git worktree list', shell=True, env=env)
        assert worktree.name in output

    # Test that it cleans up properly
    assert not os.path.exists(worktree.temp_directory)
    output = subprocess.check_output('git worktree list', shell=True, env=env)
    assert worktree.name not in output


def test_git_repo_init():
    repo = AddonGitRepository(1)

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, str(1), 'package')

    assert not os.path.exists(repo.git_repository_path)

    # accessing repo.git_repository creates the directory
    assert sorted(os.listdir(repo.git_repository.path)) == sorted([
        'objects', 'refs', 'hooks', 'info', 'description', 'config',
        'HEAD', 'logs'])


def test_git_repo_init_opens_existing_repo():
    expected_path = os.path.join(
        settings.GIT_FILE_STORAGE_PATH, str(1), 'package')

    assert not os.path.exists(expected_path)
    repo = AddonGitRepository(1)
    assert not os.path.exists(expected_path)

    # accessing repo.git_repository creates the directory
    repo.git_repository
    assert os.path.exists(expected_path)

    repo2 = AddonGitRepository(1)
    assert repo.git_repository.path == repo2.git_repository.path


@pytest.mark.django_db
def test_extract_and_commit_from_file_obj():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        addon.current_version.all_files[0],
        amo.RELEASE_CHANNEL_LISTED)

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, str(addon.id), 'package')
    assert os.listdir(repo.git_repository_path) == ['.git']

    # Verify via subprocess to make sure the repositories are properly
    # read by the regular git client
    env = {'GIT_DIR': repo.git_repository.path}

    output = subprocess.check_output('git branch', shell=True, env=env)
    assert 'listed' in output
    assert 'unlisted' not in output

    # Test that a new "unlisted" branch is created only if needed
    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        file_obj=addon.current_version.all_files[0],
        channel=amo.RELEASE_CHANNEL_UNLISTED)
    output = subprocess.check_output('git branch', shell=True, env=env)
    assert 'listed' in output
    assert 'unlisted' in output

    output = subprocess.check_output('git log listed', shell=True, env=env)
    expected = 'Create new version {} ({}) for {} from {}'.format(
        repr(addon.current_version), addon.current_version.id, repr(addon),
        repr(addon.current_version.all_files[0]))
    assert expected in output


@pytest.mark.django_db
def test_extract_and_commit_from_file_obj_set_git_hash():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

    assert addon.current_version.git_hash == ''

    AddonGitRepository.extract_and_commit_from_file_obj(
        file_obj=addon.current_version.all_files[0],
        channel=amo.RELEASE_CHANNEL_LISTED)

    addon.current_version.refresh_from_db()
    assert len(addon.current_version.git_hash) == 40


@pytest.mark.django_db
def test_extract_and_commit_from_file_obj_multiple_versions():
    addon = addon_factory(
        file_kw={'filename': 'webextension_no_id.xpi'},
        version_kw={'version': '0.1'})

    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        addon.current_version.all_files[0],
        amo.RELEASE_CHANNEL_LISTED)

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, str(addon.id), 'package')
    assert os.listdir(repo.git_repository_path) == ['.git']

    # Verify via subprocess to make sure the repositories are properly
    # read by the regular git client
    env = {'GIT_DIR': repo.git_repository.path}

    output = subprocess.check_output('git branch', shell=True, env=env)
    assert 'listed' in output

    output = subprocess.check_output('git log listed', shell=True, env=env)
    expected = 'Create new version {} ({}) for {} from {}'.format(
        repr(addon.current_version), addon.current_version.id, repr(addon),
        repr(addon.current_version.all_files[0]))
    assert expected in output

    # Create two more versions, check that they appear in the comitlog
    version = version_factory(
        addon=addon, file_kw={'filename': 'webextension_no_id.xpi'},
        version='0.2')
    AddonGitRepository.extract_and_commit_from_file_obj(
        file_obj=version.all_files[0],
        channel=amo.RELEASE_CHANNEL_LISTED)

    version = version_factory(
        addon=addon, file_kw={'filename': 'webextension_no_id.xpi'},
        version='0.3')
    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        file_obj=version.all_files[0],
        channel=amo.RELEASE_CHANNEL_LISTED)

    output = subprocess.check_output('git log listed', shell=True, env=env)
    assert output.count('Create new version') == 3
    assert '0.1' in output
    assert '0.2' in output
    assert '0.3' in output

    # 4 actual commits, including the repo initialization
    assert output.count('Mozilla Add-ons Robot') == 4

    # Make sure the commits didn't spill over into the master branch
    output = subprocess.check_output('git log', shell=True, env=env)
    assert output.count('Mozilla Add-ons Robot') == 1
    assert '0.1' not in output


@pytest.mark.django_db
def test_extract_and_commit_from_file_obj_use_applied_author():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    user = user_factory(
        email='fancyuser@foo.bar', display_name='Fancy Test User')

    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        file_obj=addon.current_version.all_files[0],
        channel=amo.RELEASE_CHANNEL_LISTED,
        author=user)

    env = {'GIT_DIR': repo.git_repository.path}

    output = subprocess.check_output(
        'git log --format=full listed', shell=True, env=env)
    assert 'Author: Fancy Test User <fancyuser@foo.bar>' in output
    assert (
        'Commit: Mozilla Add-ons Robot '
        '<addons-dev-automation+github@mozilla.com>'
        in output)


@pytest.mark.django_db
def test_extract_and_commit_from_file_obj_use_addons_robot_default():
    addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        file_obj=addon.current_version.all_files[0],
        channel=amo.RELEASE_CHANNEL_LISTED)

    env = {'GIT_DIR': repo.git_repository.path}

    output = subprocess.check_output(
        'git log --format=full listed', shell=True, env=env)
    assert (
        'Author: Mozilla Add-ons Robot '
        '<addons-dev-automation+github@mozilla.com>'
        in output)
    assert (
        'Commit: Mozilla Add-ons Robot '
        '<addons-dev-automation+github@mozilla.com>'
        in output)
