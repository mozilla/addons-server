import os
import subprocess

import pytest

from django.conf import settings

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.lib.git import AddonGitRepository, TemporaryWorktree


def test_temporary_worktree():
    repo = AddonGitRepository(1)

    env = {'GIT_DIR': os.path.join(repo.git_repository_path, '.git')}

    output = subprocess.check_output('git worktree list', shell=True, env=env)
    assert output.startswith(repo.git_repository_path)
    assert output.endswith('[master]\n')

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
    # This actually works completely without any add-on object and only
    # creates the necessary file structure
    repo = AddonGitRepository(1)

    assert repo.git_repository_path == os.path.join(
        settings.GIT_FILE_STORAGE_PATH, str(1), 'package')
    assert os.listdir(repo.git_repository_path) == ['.git']


def test_git_repo_init_opens_existing_repo():
    expected_path = os.path.join(
        settings.GIT_FILE_STORAGE_PATH, str(1), 'package')

    assert not os.path.exists(expected_path)
    repo = AddonGitRepository(1)
    assert os.path.exists(expected_path)

    repo2 = AddonGitRepository(1)
    assert repo.git_repository_path == repo2.git_repository_path


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
    env = {'GIT_DIR': os.path.join(repo.git_repository_path, '.git')}

    output = subprocess.check_output('git branch', shell=True, env=env)
    assert 'listed' in output
    assert 'unlisted' not in output

    # Test that a new "unlisted" branch is created only if needed
    repo = AddonGitRepository.extract_and_commit_from_file_obj(
        addon.current_version.all_files[0],
        amo.RELEASE_CHANNEL_UNLISTED)
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
        addon.current_version.all_files[0],
        amo.RELEASE_CHANNEL_LISTED)

    addon.current_version.refresh_from_db()
    assert len(addon.current_version.git_hash) == 40
