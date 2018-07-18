"""
Utilities for working with the Django Storage API.

A lot of these methods assume the use of a storage backend that does not
require leading directories to exist. The default Django file system storage
*will* sometimes require leading directories to exist.
"""

from django.core.files.storage import default_storage
from django.utils.encoding import force_bytes


DEFAULT_CHUNK_SIZE = 64 * 2 ** 10  # 64kB


def walk_storage(
    path,
    topdown=True,
    onerror=None,
    followlinks=False,
    storage=default_storage,
):
    """
    Generate the file names in a stored directory tree by walking the tree
    top-down.

    For each directory in the tree rooted at the directory top (including top
    itself), it yields a 3-tuple (dirpath, dirnames, filenames).

    This is intended for use with an implementation of the Django storage API.
    You can specify something other than the default storage instance with
    the storage keyword argument.
    """
    if not topdown:
        raise NotImplementedError
    if onerror:
        raise NotImplementedError
    roots = [path]
    while len(roots):
        new_roots = []
        for root in roots:
            dirs, files = storage.listdir(root)
            files = [force_bytes(f) for f in files]
            dirs = [force_bytes(d) for d in dirs]
            yield root, dirs, files
            for dn in dirs:
                new_roots.append('%s/%s' % (root, dn))
        roots[:] = new_roots


def copy_stored_file(
    src_path, dest_path, storage=default_storage, chunk_size=DEFAULT_CHUNK_SIZE
):
    """
    Copy one storage path to another storage path.

    Each path will be managed by the same storage implementation.
    """
    if src_path == dest_path:
        return
    with storage.open(src_path, 'rb') as src:
        with storage.open(dest_path, 'wb') as dest:
            done = False
            while not done:
                chunk = src.read(chunk_size)
                if chunk != '':
                    dest.write(chunk)
                else:
                    done = True


def move_stored_file(
    src_path, dest_path, storage=default_storage, chunk_size=DEFAULT_CHUNK_SIZE
):
    """
    Move a storage path to another storage path.

    The source file will be copied to the new path then deleted.
    This attempts to be compatible with a wide range of storage backends
    rather than attempt to be optimized for each individual one.
    """
    copy_stored_file(
        src_path, dest_path, storage=storage, chunk_size=chunk_size
    )
    storage.delete(src_path)


def rm_stored_dir(dir_path, storage=default_storage):
    """
    Removes a stored directory and all files stored beneath that path.
    """
    empty_dirs = []
    # Delete all files first then all empty directories.
    for root, dirs, files in walk_storage(dir_path):
        for fn in files:
            storage.delete('%s/%s' % (root, fn))
        empty_dirs.insert(0, root)
    empty_dirs.append(dir_path)
    for dn in empty_dirs:
        storage.delete(dn)
