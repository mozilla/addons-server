# -*- coding: utf-8 -*-
import uuid
import os
import shutil
import tempfile

import pygit2

from django.conf import settings

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

        if not os.path.exists(self.git_repository_path):
            os.makedirs(self.git_repository_path)
            self.git_repository = pygit2.init_repository(
                path=self.git_repository_path,
                bare=False)
            # Write first commit to 'master' to act as HEAD
            tree = self.git_repository.TreeBuilder().write()
            self.git_repository.create_commit(
                'HEAD',  # ref
                self.get_author(),  # author
                self.get_author(),  # commitor
                'Initializing repository',  # message
                tree,  # tree
                [])  # parents

            log.debug('Initialized git repository {path}'.format(
                path=self.git_repository_path))
        else:
            self.git_repository = pygit2.Repository(self.git_repository_path)

    @classmethod
    def extract_and_commit_from_file_obj(cls, file_obj, channel):
        """Extract all files from `file_obj` and comit them.

        This is doing the following:

        * Create a temporary `git worktree`_
        * Remove all files in that worktree
        * Extract the zip behind `file_obj` into the worktree
        * Commit all files

        Kinda like doing...

        * rm -rf worktree/*
        * unzip file.zip -d worktree/
        * git commit -a worktree/*

        This ignores the fact that there may be a race-condition of two
        versions being created at the same time. Since all relevant file based
        work is done in a temporary worktree there won't be any conflicts and
        usually the last upload simply wins the race and we're setting the
        HEAD of the branch (listed/unlisted) to that specific commit.

        .. _`git worktree`: https://git-scm.com/docs/git-worktree
        """
        addon = file_obj.version.addon
        repo = cls(addon.id)

        with TemporaryWorktree(repo.git_repository) as worktree:
            # Now extract the zip to the workdir
            zip_file = SafeZip(file_obj.current_file_path, force_fsync=True)
            zip_file.extract_to_dest(worktree.path)

            # Stage changes
            worktree.repo.index.add_all()
            worktree.repo.index.write()
            tree = worktree.repo.index.write_tree()

            # Create an orphaned commit
            message = (
                'Create new version {version} ({version_id}) for '
                '{addon} from {file_obj}'.format(
                    version=repr(file_obj.version),
                    version_id=file_obj.version.id,
                    addon=repr(addon),
                    file_obj=repr(file_obj)))

            oid = worktree.repo.create_commit(
                None,
                repo.get_author(), repo.get_author(),
                message,
                tree,
                []
            )

            commit = repo.git_repository.get(oid)

        branch = repo.find_or_create_branch(BRANCHES[channel])
        branch.set_target(commit.hex)

        # Set the latest git hash on the related version.
        file_obj.version.update(git_hash=commit.hex)
        return repo

    def get_author(self):
        return pygit2.Signature(
            name='Mozilla Add-ons Robot',
            email='addons-dev-automation+github@mozilla.com')

    def find_or_create_branch(self, name):
        """Lookup or create the branch named `name`"""
        branch = self.git_repository.branches.get(name)

        if branch is None:
            branch = self.git_repository.create_branch(
                name, self.git_repository.head.peel())

        return branch
