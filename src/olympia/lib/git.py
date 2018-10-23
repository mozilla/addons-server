# -*- coding: utf-8 -*-
import uuid
import os
import shutil
import tempfile

import pygit2

from django.conf import settings
from django.utils import translation
from django.utils.functional import cached_property

import olympia.core.logger

from olympia import amo
from olympia.files.utils import SafeZip

log = olympia.core.logger.getLogger('z.git_storage')


BRANCHES = {
    amo.RELEASE_CHANNEL_LISTED: 'listed',
    amo.RELEASE_CHANNEL_UNLISTED: 'unlisted'
}


class TemporaryWorktree(object):
    def __init__(self, repository):
        self.git_repository = repository
        self.name = uuid.uuid4().hex
        self.temp_directory = tempfile.mkdtemp(dir=settings.TMP_PATH)
        self.path = os.path.join(self.temp_directory, self.name)
        self.obj = None
        self.repo = None

    def __enter__(self):
        self.obj = self.git_repository.add_worktree(self.name, self.path)
        self.repo = pygit2.Repository(self.obj.path)

        # Clean the workdir
        for entry in self.repo[self.repo.head.target].tree:
            path = os.path.join(self.path, entry.name)

            if os.path.isfile(path):
                os.unlink(path)
            else:
                shutil.rmtree(path)

        return self

    def __exit__(self, type, value, traceback):
        # Remove temp directory
        shutil.rmtree(self.temp_directory)

        # Prune temp worktree
        if self.obj is not None:
            self.obj.prune(True)

        # Remove worktree ref in upstream repository
        self.git_repository.lookup_branch(self.name).delete()


class AddonGitRepository(object):

    def __init__(self, addon_id, package_type='package'):
        assert package_type in ('package', 'source')

        self.git_repository_path = os.path.join(
            settings.GIT_FILE_STORAGE_PATH,
            str(addon_id),
            package_type)

    @cached_property
    def git_repository(self):
        if not os.path.exists(self.git_repository_path):
            os.makedirs(self.git_repository_path)
            git_repository = pygit2.init_repository(
                path=self.git_repository_path,
                bare=False)
            # Write first commit to 'master' to act as HEAD
            tree = self.git_repository.TreeBuilder().write()
            git_repository.create_commit(
                'HEAD',  # ref
                self.get_author(),  # author, using addons-robot
                self.get_author(),  # commiter, using addons-robot
                'Initializing repository',  # message
                tree,  # tree
                [])  # parents

            log.debug('Initialized git repository {path}'.format(
                path=self.git_repository_path))
        else:
            git_repository = pygit2.Repository(self.git_repository_path)

        return git_repository

    @classmethod
    def extract_and_commit_from_file_obj(cls, file_obj, channel, author=None):
        """Extract all files from `file_obj` and comit them.

        This is doing the following:

        * Create a temporary `git worktree`_
        * Remove all files in that worktree
        * Extract the zip behind `file_obj` into the worktree
        * Commit all files

        Kinda like doing::

            $ workdir_name=$(uuid)
            $ mkdir /tmp/$workdir_name
            $ git worktree add /tmp/$workdir_name
            Preparing worktree (new branch 'af4172e4-d8c7…')
            HEAD is now at 8c5223e Initial commit

            $ git worktree list
            /tmp/addon-repository                      8c5223e [master]
            /tmp/af4172e4-d8c7-4486-a5f2-316458da91ff  8c5223e [af4172e4-d8c7…]

            $ unzip dingrafowl-falcockalo-lockapionk.zip -d /tmp/$workdir_name
            Archive:  dingrafowl-falcockalo-lockapionk.zip
             extracting: /tmp/af4172e4-d8c7…/manifest.json

            $ pushd /tmp/$workdir_name
            /tmp/af4172e4-d8c7-4486-a5f2-316458da91ff /tmp/addon-repository

            $ git status
            On branch af4172e4-d8c7-4486-a5f2-316458da91ff
            Untracked files:
              (use "git add <file>..." to include in what will be committed)

                    manifest.json

            $ git add *
            $ git commit -a -m "Creating new version"
            [af4172e4-d8c7-4486-a5f2-316458da91ff c4285f8] Creating new version
            …
            $ cd addon-repository
            $ git checkout -b listed
            Switched to a new branch 'listed'

            # We don't technically do a full cherry-pick but it's close enough
            # and does almost what we do. We are technically commiting
            # directly on top of the branch as if we checked out the branch
            # in the worktree (via -b) but pygit doesn't properly support that
            # so we "simply" set the parents correctly.
            $ git cherry-pick c4285f8
            [listed a4d0f63] Creating new version…

        This ignores the fact that there may be a race-condition of two
        versions being created at the same time. Since all relevant file based
        work is done in a temporary worktree there won't be any conflicts and
        usually the last upload simply wins the race and we're setting the
        HEAD of the branch (listed/unlisted) to that specific commit.

        .. _`git worktree`: https://git-scm.com/docs/git-worktree
        """
        # Make sure we're always using the en-US locale by default
        translation.activate('en-US')

        addon = file_obj.version.addon
        repo = cls(addon.id)

        branch = repo.find_or_create_branch(BRANCHES[channel])

        # Create a temporary worktree that we can use to unpack the zip
        # without disturbing the current git workdir since it creates a new
        # temporary directory where we extract to.
        with TemporaryWorktree(repo.git_repository) as worktree:
            # Now extract the zip to the workdir
            zip_file = SafeZip(file_obj.current_file_path, force_fsync=True)
            zip_file.extract_to_dest(worktree.path)

            # Stage changes, `TemporaryWorktree` always cleans the whole
            # directory so we can simply add all changes and have the correct
            # state.

            # Add all changes to the index (git add ...)
            worktree.repo.index.add_all()
            worktree.repo.index.write()

            tree = worktree.repo.index.write_tree()

            # Now create an commit directly on top of the respective branch

            message = (
                'Create new version {version} ({version_id}) for '
                '{addon} from {file_obj}'.format(
                    version=repr(file_obj.version),
                    version_id=file_obj.version.id,
                    addon=repr(addon),
                    file_obj=repr(file_obj)))

            oid = worktree.repo.create_commit(
                None,
                # author, using the actual uploading user
                repo.get_author(author),
                # committer, using addons-robot because that's the user
                # actually doing the commit.
                repo.get_author(),  # commiter, using addons-robot
                message,
                tree,
                # Set the current branch HEAD as the parent of this commit
                # so that it'll go straight into the branches commit log
                [branch.target]
            )

            # Fetch the commit object
            commit = worktree.repo.get(oid)

            # And set the commit we just created as HEAD of the relevant
            # branch, and updates the reflog. This does not require any
            # merges.
            branch.set_target(commit.hex)

        # Set the latest git hash on the related version.
        file_obj.version.update(git_hash=commit.hex)
        return repo

    def get_author(self, user=None):
        if user is not None:
            author_name = user.name
            author_email = user.email
        else:
            author_name = 'Mozilla Add-ons Robot'
            author_email = 'addons-dev-automation+github@mozilla.com'
        return pygit2.Signature(name=author_name, email=author_email)

    def find_or_create_branch(self, name):
        """Lookup or create the branch named `name`"""
        branch = self.git_repository.branches.get(name)

        if branch is None:
            branch = self.git_repository.create_branch(
                name, self.git_repository.head.peel())

        return branch
