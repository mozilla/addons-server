import mimetypes
import os
import shutil
import sys
import tempfile
import uuid
from collections import namedtuple
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connections
from django.utils import translation
from django.utils.functional import cached_property

import pygit2
from celery import current_task
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.amo.utils import id_to_path
from olympia.files.utils import extract_extension_to_dest, get_all_files
from olympia.versions.models import Version

from .models import GitExtractionEntry


log = olympia.core.logger.getLogger('z.git_storage')

# A mixture of Blob and TreeEntry
TreeEntryWrapper = namedtuple('Entry', 'tree_entry, path, blob')

BRANCHES = {
    amo.CHANNEL_LISTED: 'listed',
    amo.CHANNEL_UNLISTED: 'unlisted',
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
    GIT_DIFF_LINE_CONTEXT_EOFNL: 'normal-eofnl',
    GIT_DIFF_LINE_ADD_EOFNL: 'insert-eofnl',
    GIT_DIFF_LINE_DEL_EOFNL: 'delete-eofnl',
}

# Prefix folder name we are using to store extracted add-on data to avoid any
# clashes, e.g with .git folders.
EXTRACTED_PREFIX = 'extracted'

# Rename and copy threshold, 50% is the default git threshold
SIMILARITY_THRESHOLD = 50


# Some official mimetypes belong to the `text` category, even though their
# names don't include `text/`.
MIMETYPE_CATEGORY_MAPPING = {
    'application/json': 'text',
    'application/xml': 'text',
}


# Some mimetypes need to be hanged to some other mimetypes.
MIMETYPE_COMPAT_MAPPING = {
    # See: https://github.com/mozilla/addons-server/issues/11382
    'image/svg': 'image/svg+xml',
    # See: https://github.com/mozilla/addons-server/issues/11383
    'image/x-ms-bmp': 'image/bmp',
    # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types#textjavascript  # noqa
    'application/javascript': 'text/javascript',
}


class BrokenRefError(RuntimeError):
    pass


class MissingMasterBranchError(RuntimeError):
    pass


def get_mime_type_for_blob(tree_or_blob, name):
    """Returns the mimetype and type category for a git blob.

    The type category can be ``image``, ``directory``, ``text`` or ``binary``.
    """
    if tree_or_blob == pygit2.GIT_OBJ_TREE:
        return 'application/octet-stream', 'directory'

    (mimetype, _) = mimetypes.guess_type(name)
    # We use `text/plain` as default.
    mimetype = MIMETYPE_COMPAT_MAPPING.get(mimetype, mimetype or 'text/plain')
    known_type_cagegories = ('image', 'text')
    default_type_category = 'binary'
    # If mimetype has an explicit category, use it.
    type_category = (
        MIMETYPE_CATEGORY_MAPPING.get(mimetype, mimetype.split('/')[0])
        if mimetype
        else default_type_category
    )

    return (
        mimetype,
        default_type_category
        if type_category not in known_type_cagegories
        else type_category,
    )


class TemporaryWorktree:
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


class AddonGitRepository:
    GIT_DESCRIPTION = '.git/description'

    def __init__(self, addon_or_id, package_type='addon'):
        from olympia.addons.models import Addon

        assert package_type in ('addon',)

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
        pygit2.option(
            pygit2.GIT_OPT_SET_SEARCH_PATH, pygit2.GIT_CONFIG_LEVEL_GLOBAL, git_home
        )

        # This will cause .keep file existence checks to be skipped when
        # accessing packfiles, which can help performance with remote
        # filesystems.
        # See: https://github.com/mozilla/addons-server/issues/13019
        pygit2.option(pygit2.GIT_OPT_DISABLE_PACK_KEEP_FILE_CHECKS, True)

        # Enable calling fsync() for various operations touching .git
        pygit2.option(pygit2.GIT_OPT_ENABLE_FSYNC_GITDIR, True)

        self.addon_id = (
            addon_or_id.pk if isinstance(addon_or_id, Addon) else addon_or_id
        )

        self.git_repository_path = os.path.join(
            settings.GIT_FILE_STORAGE_PATH,
            id_to_path(self.addon_id, breadth=2),
            package_type,
        )

    @property
    def is_extracted(self):
        return os.path.exists(self.git_repository_path)

    @property
    def is_recent(self):
        git_description_path = os.path.join(
            self.git_repository_path, self.GIT_DESCRIPTION
        )
        if not self.is_extracted or not os.path.exists(git_description_path):
            return False
        # A git repository is recent when it was created less than 1 hour ago.
        an_hour_ago = datetime.utcnow() - timedelta(hours=1)
        mtime = datetime.utcfromtimestamp(
            os.path.getmtime(
                # There is no way to get the creation time of a file/folder on
                # most UNIX systems, so we use a file that is created by
                # default but never modified (GIT_DESCRIPTION) to determine
                # whether a git repository is recent or not.
                git_description_path
            )
        )
        return mtime > an_hour_ago

    @cached_property
    def git_repository(self):
        if not self.is_extracted:
            os.makedirs(self.git_repository_path)
            git_repository = pygit2.init_repository(
                path=self.git_repository_path, bare=False
            )
            # Write first commit to 'master' to act as HEAD
            tree = git_repository.TreeBuilder().write()
            git_repository.create_commit(
                'HEAD',  # ref
                self.get_author(),  # author, using addons-robot
                self.get_author(),  # commiter, using addons-robot
                'Initializing repository',  # message
                tree,  # tree
                [],
            )  # parents

            log.info('Initialized git repository "%s"', self.git_repository_path)
        else:
            git_repository = pygit2.Repository(self.git_repository_path)

            # We have to verify that the 'master' branch exists because we
            # might have mis-initialized repositories in the past.
            # See: https://github.com/mozilla/addons-server/issues/14127
            try:
                master_ref = 'refs/heads/master'
                git_repository.lookup_reference(master_ref)
            except KeyError:
                message = f'Reference "{master_ref}" not found'
                log.exception(message)
                raise MissingMasterBranchError(message)

        return git_repository

    def delete(self):
        if not self.is_extracted:
            log.error('called delete() on a non-extracted git repository')
            return
        # Reset the git hash of each version of the add-on related to this git
        # repository.
        Version.unfiltered.filter(addon_id=self.addon_id).update(git_hash='')
        shutil.rmtree(self.git_repository_path)

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
            branch = repo.find_or_create_branch(BRANCHES[version.channel])
            note = f' ({note})' if note else ''

            commit = repo._commit_through_worktree(
                file_obj=version.file,
                message=(
                    'Create new version {version} ({version_id}) for '
                    '{addon} from {file_obj}{note}'.format(
                        version=repr(version),
                        version_id=version.id,
                        addon=repr(version.addon),
                        file_obj=repr(version.file),
                        note=note,
                    )
                ),
                author=author,
                branch=branch,
            )

            if (
                current_task
                and current_task.request.id is not None
                and not current_task.request.is_eager
            ):
                # Extraction might have taken a while, and our connection might
                # be gone and we haven't realized it. Django cleans up
                # connections after CONN_MAX_AGE but only during the
                # request/response cycle, so if we're inside a task let's do it
                # ourselves before using the database again - it will
                # automatically reconnect if needed (use 'default' since we
                # want the primary db where writes go).
                connections['default'].close_if_unusable_or_obsolete()

            # Set the latest git hash on the related version.
            version.update(git_hash=commit.hex)
        finally:
            translation.activate(current_language)
        return repo

    def get_author(self, user=None):
        if user is not None:
            author_name = f'User {user.id}'
            author_email = user.email
        else:
            author_name = 'Mozilla Add-ons Robot'
            author_email = 'addons-dev-automation+github@mozilla.com'
        return pygit2.Signature(name=author_name, email=author_email)

    def find_or_create_branch(self, name):
        """Lookup or create the branch named `name`"""
        try:
            branch = self.git_repository.branches.get(name)
        except pygit2.GitError:
            message = f'Reference for branch "{name}" is broken'
            log.exception(message)
            raise BrokenRefError(message)

        if branch is None:
            branch = self.git_repository.create_branch(
                name, self.git_repository.head.peel()
            )

        return branch

    def _commit_through_worktree(self, file_obj, message, author, branch):
        """
        Create a temporary worktree that we can use to unpack the extension
        without disturbing the current git workdir since it creates a new
        temporary directory where we extract to.
        """
        with TemporaryWorktree(self.git_repository) as worktree:
            if file_obj:
                # Now extract the extension to the workdir
                extract_extension_to_dest(
                    source=file_obj.file.path,
                    dest=worktree.extraction_target_path,
                    force_fsync=True,
                )

            # Stage changes, `TemporaryWorktree` always cleans the whole
            # directory so we can simply add all changes and have the correct
            # state.

            # Fetch all files and strip the absolute path but keep the
            # `extracted/` prefix
            files = get_all_files(worktree.extraction_target_path, worktree.path, '')

            # Make sure the index is up to date
            worktree.repo.index.read()

            # For security reasons git doesn't allow adding .git subdirectories
            # anywhere in the repository. So we're going to rename them and add
            # a random postfix.
            # In order to disable the effect of the special git config files,
            # we also have to postfix them.
            files_to_rename = (
                '.git',
                '.gitattributes',
                '.gitconfig',
                '.gitignore',
                '.gitmodules',
            )
            # Sort files by path length to rename the deepest files first.
            files.sort(key=len, reverse=True)
            for filename in files:
                if os.path.basename(filename) in files_to_rename:
                    renamed = f'{filename}.{uuid.uuid4().hex[:8]}'
                    shutil.move(
                        os.path.join(worktree.path, filename),
                        os.path.join(worktree.path, renamed),
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
                #
                # We use `lookup_reference` to fetch the most up-to-date
                # reference to the branch in order to avoid an error described
                # in: https://github.com/mozilla/addons-server/issues/13932
                [self.git_repository.lookup_reference(branch.name).target],
            )

            # Fetch the commit object
            commit = worktree.repo.get(oid)

            # And set the commit we just created as HEAD of the relevant
            # branch, and updates the reflog. This does not require any
            # merges.
            #
            # We use `lookup_reference` to fetch the most up-to-date reference
            # to the branch in order to avoid an error described in:
            # https://github.com/mozilla/addons-server/issues/13932
            self.git_repository.lookup_reference(branch.name).set_target(commit.hex)

        return commit

    def get_root_tree(self, commit):
        """Return the root tree object.

        This doesn't contain the ``EXTRACTED_PREFIX`` prefix folder.
        """
        # When `commit` is a commit hash, e.g passed to us through the API
        # serializers we have to fetch the actual commit object to proceed.
        if isinstance(commit, str):
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
                    blob=None, tree_entry=tree_entry, path=tree_entry.name
                )
                for child in self.iter_tree(tree_or_blob):
                    yield TreeEntryWrapper(
                        blob=child.blob,
                        tree_entry=child.tree_entry,
                        path=os.path.join(tree_entry.name, child.path),
                    )
            else:
                yield TreeEntryWrapper(
                    blob=tree_or_blob, tree_entry=tree_entry, path=tree_entry.name
                )

    def get_raw_diff(self, commit, parent=None, include_unmodified=False):
        """Return the raw diff object.

        This is cached as we'll be calling it multiple times, e.g
        once to render the actual diff and again to fetch specific
        status information (added, removed etc) in a later step.
        """
        diff_cache = getattr(self, '_diff_cache', {})

        flags = pygit2.GIT_DIFF_NORMAL | pygit2.GIT_DIFF_IGNORE_WHITESPACE_CHANGE

        if include_unmodified:
            flags |= pygit2.GIT_DIFF_INCLUDE_UNMODIFIED

        try:
            return diff_cache[(commit, parent, include_unmodified)]
        except KeyError:
            if parent is None:
                retval = self.get_root_tree(commit).diff_to_tree(
                    # We always show the whole file by default
                    context_lines=sys.maxsize,
                    interhunk_lines=0,
                    flags=flags,
                    swap=True,
                )
            else:
                retval = self.git_repository.diff(
                    self.get_root_tree(parent),
                    self.get_root_tree(commit),
                    # We always show the whole file by default
                    context_lines=sys.maxsize,
                    flags=flags,
                    interhunk_lines=0,
                )

            diff_cache[(commit, parent, include_unmodified)] = retval
            self._diff_cache = diff_cache

        return retval

    def get_diff(self, commit, parent=None, pathspec=None):
        """Get a diff from `parent` to `commit`.

        If `parent` is not given we assume it's the first commit and handle
        it accordingly.

        :param pathspec: If a list of files is given we only retrieve a list
                         for them.
        """
        diff = self.get_raw_diff(
            commit, parent=parent, include_unmodified=pathspec is not None
        )

        changes = []

        for patch in diff:
            # Support for this hasn't been implemented upstream yet, we'll
            # work on this upstream if needed but for now just selecting
            # files based on `pathspec` works for us.
            if pathspec and patch.delta.old_file.path not in pathspec:
                continue

            if parent is None:
                changes.append(self._render_patch(patch, commit, commit, pathspec))
            else:
                changes.append(self._render_patch(patch, commit, parent, pathspec))
        return changes

    def get_deltas(self, commit, parent, pathspec=None):
        """Only fetch deltas from `parent` to `commit`.

        This method specifically does not render any textual changes
        but fetches as few details as possible to use a different
        `pygit2` API to retrieve changes and to improve performance
        significantly.

        The entries returned are fairly similar to what `get_diff`
        returns but don't include `hunks`, `lines_deleted` / `lines_added`
        as well as `new_ending_new_line` and `old_ending_new_line`

        We also don't expose `size` and `is_binary` as it's unreliable since
        the `deltas` iterator tries to not examine the files content if
        possible - so they might have wrong values.
        """
        diff = self.get_raw_diff(
            commit, parent=parent, include_unmodified=pathspec is not None
        )

        deltas = []

        for delta in diff.deltas:
            if pathspec and delta.old_file.path not in pathspec:
                continue

            deltas.append(
                {
                    'path': delta.new_file.path,
                    'mode': delta.status_char(),
                    'old_path': delta.old_file.path,
                    'parent': commit if parent is None else parent,
                    'hash': commit,
                }
            )

        return deltas

    def _render_patch(self, patch, commit, parent, pathspec=None):
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
                elif origin == GIT_DIFF_LINE_ADD_EOFNL:
                    old_ending_new_line = False
                elif origin == GIT_DIFF_LINE_DEL_EOFNL:
                    new_ending_new_line = False

                changes.append(
                    {
                        'content': line.content.rstrip('\r\n'),
                        'type': GIT_DIFF_LINE_MAPPING[origin],
                        # Can be `-1` for additions
                        'old_line_number': line.old_lineno,
                        'new_line_number': line.new_lineno,
                    }
                )

            hunks.append(
                {
                    'header': hunk.header.rstrip('\r\n'),
                    'old_start': hunk.old_start,
                    'new_start': hunk.new_start,
                    'old_lines': hunk.old_lines,
                    'new_lines': hunk.new_lines,
                    'changes': changes,
                }
            )

        # We are exposing unchanged files fully to the frontend client
        # so that it can show them for an better review experience.
        # We are using the "include unmodified"-flag for git but that
        # doesn't render any hunks and there's no way to enforce it.
        # Unfortunately that means we have to simulate line changes and
        # hunk data for unmodified files.
        # Unchanged files are *only* exposed in case of explicitly requesting
        # a diff view for an file. That way we increase performance for
        # reguar unittests and full-tree diffs.
        generate_unmodified_fake_diff = (
            not patch.delta.is_binary
            and pathspec is not None
            and (
                patch.delta.status == pygit2.GIT_DELTA_UNMODIFIED
                or (
                    # See:
                    # https://github.com/mozilla/addons-server/issues/15966
                    patch.delta.status == pygit2.GIT_DELTA_MODIFIED
                    and len(hunks) == 0
                )
            )
        )

        if generate_unmodified_fake_diff:
            tree = self.get_root_tree(commit)
            blob_or_tree = tree[patch.delta.new_file.path]
            actual_blob = self.git_repository[blob_or_tree.oid]
            mime_category = get_mime_type_for_blob(
                blob_or_tree.type, patch.delta.new_file.path
            )[1]

            if mime_category == 'text':
                data = actual_blob.data
                changes = [
                    {
                        'content': line,
                        'type': GIT_DIFF_LINE_MAPPING[GIT_DIFF_LINE_CONTEXT],
                        'old_line_number': lineno,
                        'new_line_number': lineno,
                    }
                    for lineno, line in enumerate(data.split(b'\n'), start=1)
                ]

                hunks.append(
                    {
                        'header': '@@ -0 +0 @@',
                        'old_start': 0,
                        'new_start': 0,
                        'old_lines': changes[-1]['old_line_number'],
                        'new_lines': changes[-1]['new_line_number'],
                        'changes': changes,
                    }
                )

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


def skip_git_extraction(version):
    return version.addon.type != amo.ADDON_EXTENSION


def create_git_extraction_entry(version):
    if skip_git_extraction(version):
        log.debug(
            'Skipping git extraction of add-on "%s" not a web-extension.',
            version.addon.id,
        )
        return

    log.info('Adding add-on "%s" to the git extraction queue.', version.addon.id)
    GitExtractionEntry.objects.create(addon=version.addon)


def extract_version_to_git(version_id):
    """Extract a `Version` into our git storage backend."""
    # We extract deleted or disabled versions as well so we need to make sure
    # we can access them.
    version = Version.unfiltered.get(pk=version_id)

    if skip_git_extraction(version):
        # We log a warning message because this should not happen (as the CRON
        # task should not select non-webextension versions).
        log.warning(
            'Skipping git extraction of add-on "%s": not a web-extension.',
            version.addon.id,
        )
        return

    log.info('Extracting version "%s" into git backend', version_id)

    try:
        with statsd.timer('git.extraction.version'):
            repo = AddonGitRepository.extract_and_commit_from_version(version=version)
        statsd.incr('git.extraction.version.success')
    except Exception as exc:
        statsd.incr('git.extraction.version.failure')
        raise exc

    log.info('Extracted version "%s" into "%s".', version_id, repo.git_repository_path)
