# -*- coding: utf-8 -*-
from collections import namedtuple
import uuid
import os
import shutil
import tempfile
import sys

import six
import pygit2

from django.conf import settings
from django.utils import translation
from django.utils.functional import cached_property

import olympia.core.logger

from olympia import amo
from olympia.files.utils import (
    id_to_path, extract_extension_to_dest, get_all_files)


log = olympia.core.logger.getLogger('z.git_storage')

# A mixture of Blob and TreeEntry
TreeEntryWrapper = namedtuple('Entry', 'tree_entry, path, blob')

BRANCHES = {
    amo.RELEASE_CHANNEL_LISTED: 'listed',
    amo.RELEASE_CHANNEL_UNLISTED: 'unlisted'
}

# Constants from libgit2 includes/git2/diff.h
# while they're not in upstream pygit2 I added them here (cgrebs)
# We don't have all line constants here though since we don't
# really make use of them in the frontend.
GIT_DIFF_LINE_CONTEXT = ' '
GIT_DIFF_LINE_ADDITION = '+'
GIT_DIFF_LINE_DELETION = '-'
# Both files have no LF at end
GIT_DIFF_LINE_CONTEXT_EOFNL = '='
# Old has no LF at end, new does
GIT_DIFF_LINE_ADD_EOFNL = '>'
# Old has LF at end, new does not
GIT_DIFF_LINE_DEL_EOFNL = '<'

# This matches typing in addons-frontend
GIT_DIFF_LINE_MAPPING = {
    GIT_DIFF_LINE_CONTEXT: 'normal',
    GIT_DIFF_LINE_ADDITION: 'insert',
    GIT_DIFF_LINE_DELETION: 'delete',
}

# Prefix folder name we are using to store extracted add-on or source
# data to avoid any clashes, e.g with .git folders.
EXTRACTED_PREFIX = 'extracted'

# Rename and copy threshold, 50% is the default git threshold
SIMILARITY_THRESHOLD = 50


class TemporaryWorktree(object):
    def __init__(self, repository):
        self.git_repository = repository
        self.name = uuid.uuid4().hex
        self.temp_directory = tempfile.mkdtemp(dir=settings.TMP_PATH)
        self.path = os.path.join(self.temp_directory, self.name)
        self.extraction_target_path = os.path.join(self.path, EXTRACTED_PREFIX)
        self.obj = None
        self.repo = None

    def __enter__(self):
        self.obj = self.git_repository.add_worktree(self.name, self.path)
        self.repo = pygit2.Repository(self.obj.path)

        # Clean the workdir (of the newly created worktree)
        for entry in self.repo[self.repo.head.target].tree:
            path = os.path.join(self.path, entry.name)

            if os.path.isfile(path):
                os.unlink(path)
            else:
                shutil.rmtree(path)

        os.makedirs(self.extraction_target_path)

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

    def __init__(self, addon_or_id, package_type='addon'):
        from olympia.addons.models import Addon
        assert package_type in ('addon', 'source')

        # Always enforce the search path being set to our ROOT
        # setting. This is sad, libgit tries to fetch the global git
        # config file (~/.gitconfig) and falls over permission errors while
        # doing so in our web-environment.
        # We are setting this here to avoid creating a unnecessary global
        # state but since this is overwriting a global value in pygit2 it
        # affects all pygit2 calls.

        # https://github.com/libgit2/pygit2/issues/339
        # https://github.com/libgit2/libgit2/issues/2122
        git_home = settings.ROOT
        pygit2.settings.search_path[pygit2.GIT_CONFIG_LEVEL_GLOBAL] = git_home

        addon_id = (
            addon_or_id.pk
            if isinstance(addon_or_id, Addon)
            else addon_or_id)

        self.git_repository_path = os.path.join(
            settings.GIT_FILE_STORAGE_PATH,
            id_to_path(addon_id),
            package_type)

    @property
    def is_extracted(self):
        return os.path.exists(self.git_repository_path)

    @cached_property
    def git_repository(self):
        if not self.is_extracted:
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
    def extract_and_commit_from_version(cls, version, author=None, note=None):
        """Extract the XPI from `version` and comit it.

        This is doing the following:

        * Create a temporary `git worktree`_
        * Remove all files in that worktree
        * Extract the xpi behind `version` into the worktree
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
        current_language = translation.get_language()

        try:
            # Make sure we're always using the en-US locale by default
            # to have unified commit messages and avoid any __str__
            # to give us wrong results
            translation.activate('en-US')

            repo = cls(version.addon.id, package_type='addon')
            file_obj = version.all_files[0]
            branch = repo.find_or_create_branch(BRANCHES[version.channel])
            note = ' ({})'.format(note) if note else ''

            commit = repo._commit_through_worktree(
                path=file_obj.current_file_path,
                message=(
                    'Create new version {version} ({version_id}) for '
                    '{addon} from {file_obj}{note}'.format(
                        version=repr(version),
                        version_id=version.id,
                        addon=repr(version.addon),
                        file_obj=repr(file_obj),
                        note=note)),
                author=author,
                branch=branch)

            # Set the latest git hash on the related version.
            version.update(git_hash=commit.hex)
        finally:
            translation.activate(current_language)
        return repo

    @classmethod
    def extract_and_commit_source_from_version(cls, version, author=None):
        """Extract the source file from `version` and comit it.

        This is doing the following:

        * Create a temporary `git worktree`_
        * Remove all files in that worktree
        * Extract the xpi behind `version` into the worktree
        * Commit all files

        See `extract_and_commit_from_version` for more details.
        """
        repo = cls(version.addon.id, package_type='source')
        branch = repo.find_or_create_branch(BRANCHES[version.channel])

        commit = repo._commit_through_worktree(
            path=version.source.path,
            message=(
                'Create new version {version} ({version_id}) for '
                '{addon} from source file'.format(
                    version=repr(version),
                    version_id=version.id,
                    addon=repr(version.addon))),
            author=author,
            branch=branch)

        # Set the latest git hash on the related version.
        version.update(source_git_hash=commit.hex)

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

    def _commit_through_worktree(self, path, message, author, branch):
        """
        Create a temporary worktree that we can use to unpack the extension
        without disturbing the current git workdir since it creates a new
        temporary directory where we extract to.
        """
        with TemporaryWorktree(self.git_repository) as worktree:
            # Now extract the extension to the workdir
            extract_extension_to_dest(
                source=path,
                dest=worktree.extraction_target_path,
                force_fsync=True)

            # Stage changes, `TemporaryWorktree` always cleans the whole
            # directory so we can simply add all changes and have the correct
            # state.

            # Fetch all files and strip the absolute path but keep the
            # `extracted/` prefix
            files = get_all_files(
                worktree.extraction_target_path,
                worktree.path,
                '')

            # Make sure the index is up to date
            worktree.repo.index.read()

            for filename in files:
                if os.path.basename(filename) == '.git':
                    # For security reasons git doesn't allow adding
                    # .git subdirectories anywhere in the repository.
                    # So we're going to rename them and add a random
                    # postfix
                    renamed = '{}.{}'.format(filename, uuid.uuid4().hex[:8])
                    shutil.move(
                        os.path.join(worktree.path, filename),
                        os.path.join(worktree.path, renamed)
                    )

            # Add all changes to the index (git add --all ...)
            worktree.repo.index.add_all()
            worktree.repo.index.write()

            tree = worktree.repo.index.write_tree()

            # Now create an commit directly on top of the respective branch
            oid = worktree.repo.create_commit(
                None,
                # author, using the actual uploading user if possible.
                self.get_author(author),
                # committer, using addons-robot because that's the user
                # actually doing the commit.
                self.get_author(),
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

        return commit

    def get_root_tree(self, commit):
        """Return the root tree object.

        This doesn't contain the ``EXTRACTED_PREFIX`` prefix folder.
        """
        # When `commit` is a commit hash, e.g passed to us through the API
        # serializers we have to fetch the actual commit object to proceed.
        if isinstance(commit, six.string_types):
            commit = self.git_repository.revparse_single(commit)

        return self.git_repository[commit.tree[EXTRACTED_PREFIX].oid]

    def iter_tree(self, tree):
        """Recursively iterate through a tree.
        This includes the directories.
        """
        for tree_entry in tree:
            tree_or_blob = self.git_repository[tree_entry.oid]

            if isinstance(tree_or_blob, pygit2.Tree):
                yield TreeEntryWrapper(
                    blob=None,
                    tree_entry=tree_entry,
                    path=tree_entry.name)
                for child in self.iter_tree(tree_or_blob):
                    yield TreeEntryWrapper(
                        blob=child.blob,
                        tree_entry=child.tree_entry,
                        path=os.path.join(tree_entry.name, child.path))
            else:
                yield TreeEntryWrapper(
                    blob=tree_or_blob,
                    tree_entry=tree_entry,
                    path=tree_entry.name)

    def get_diff(self, commit, parent=None, pathspec=None):
        """Get a diff from `parent` to `commit`.

        If `parent` is not given we assume it's the first commit and handle
        it accordingly.

        We are resolving renames and copies according to a 50% similarity
        threshold.

        :param pathspec: If a list of files is given we only retrieve a list
                         for them.
        """
        if parent is None:
            return self.get_diff_for_initial_commit(commit, pathspec=pathspec)

        changes = []
        diff = self.git_repository.diff(
            self.get_root_tree(parent),
            self.get_root_tree(commit),
            # We always show the whole file by default
            context_lines=sys.maxsize,
            interhunk_lines=0)

        for patch in diff:
            # Support for this hasn't been implemented upstream yet, we'll
            # work on this upstream if needed but for now just selecting
            # files based on `pathspec` works for us.
            if pathspec and patch.delta.old_file.path not in pathspec:
                continue

            changes.append(self._render_patch(patch, commit, parent))
        return changes

    def get_diff_for_initial_commit(self, commit, pathspec=None):
        # Initial commits are special since they're comparing against
        # an empty tree.
        diff = self.get_root_tree(commit).diff_to_tree(
            context_lines=sys.maxsize,
            interhunk_lines=1,
            swap=True)

        changes = []

        for patch in diff:
            # Support for this hasn't been implemented upstream yet, we'll
            # work on this upstream if needed but for now just selecting
            # files based on `pathspec` works for us.
            if pathspec and patch.delta.old_file.path not in pathspec:
                continue

            changes.append(self._render_patch(patch, commit, commit))

        return changes

    def _render_patch(self, patch, commit, parent):
        """
        This will be moved to a proper drf serializer in the future
        but until the format isn't set we'll keep it like that to simplify
        experimentation.
        """
        old_ending_new_line = True
        new_ending_new_line = True

        hunks = []

        for hunk in patch.hunks:
            changes = []

            for line in hunk.lines:
                # Properly set line ending changes. We can do it directly
                # in the for-loop as line-ending changes should always be
                # present at the very end of a file so there's no risk of
                # these values being overwritten.
                origin = line.origin

                if origin == GIT_DIFF_LINE_CONTEXT_EOFNL:
                    old_ending_new_line = new_ending_new_line = False
                    origin = ' '
                elif origin == GIT_DIFF_LINE_ADD_EOFNL:
                    old_ending_new_line = False
                    origin = '+'
                elif origin == GIT_DIFF_LINE_DEL_EOFNL:
                    new_ending_new_line = False
                    origin = '-'

                changes.append({
                    'content': line.content.rstrip('\r\n'),
                    'type': GIT_DIFF_LINE_MAPPING[origin],
                    # Can be `-1` for additions
                    'old_line_number': line.old_lineno,
                    'new_line_number': line.new_lineno,
                })

            hunks.append({
                'header': hunk.header.rstrip('\r\n'),
                'old_start': hunk.old_start,
                'new_start': hunk.new_start,
                'old_lines': hunk.old_lines,
                'new_lines': hunk.new_lines,
                'changes': changes
            })

        entry = {
            'path': patch.delta.new_file.path,
            'size': patch.delta.new_file.size,
            'lines_added': patch.line_stats[1],
            'lines_deleted': patch.line_stats[2],
            'is_binary': patch.delta.is_binary,
            'mode': patch.delta.status_char(),
            'hunks': hunks,
            'old_path': patch.delta.old_file.path,
            'parent': parent,
            'hash': commit,
            'new_ending_new_line': new_ending_new_line,
            'old_ending_new_line': old_ending_new_line,
        }

        return entry
