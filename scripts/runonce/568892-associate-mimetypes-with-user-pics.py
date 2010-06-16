"""This script will scan all of the users with pictures that are uploaded and,
after looking at the file extension, will update the database with the
appropriate mimetype.  This is bug 568892.

Caveat:  It turns out, remora has everything hardcoded to .png and the only
reason mimetypes work at all is because Apache is serving them.  If a user
uploaded different file types they will get multiple files on disk.  That result
is undetermined with this script, however, remora is clearly not using the
picture_type field at all, so I'm skipping it in this script.

This script is safe to run multiple times.  In testing, it took around 90
seconds to complete."""

import os
import sys

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, ROOT)

from manage import settings
from django.db import connection, transaction

goldmine = settings.USERPICS_PATH

if not os.path.isdir(goldmine):
    print "Can't find the uploads path! (%s)" % goldmine
    sys.exit()

total_processed = 0

extensions = {'.jpg': 'image/jpeg',
              '.png': 'image/png',
              '.gif': 'image/gif',
}

cursor = connection.cursor()

# Reset all picture types.  There is some weird stuff in there because Remora
# isn't filtering it.
print "Resetting current users..."
cursor.execute("UPDATE users SET picture_type=''")
transaction.commit_unless_managed()

print "Walking the tree..."
for root, dir, files in os.walk(goldmine):
    # The files are in a crazy directory structure, but only the bottom level
    # has files, and the filename is the complete user id, and that's all we
    # care about.  EasyBreezy++
    pile_of_ids = []
    for file in files:
        user_id, type = os.path.splitext(file)

        if user_id in pile_of_ids:
            # It appears that there are ~50 users who have multiple images on
            # disk with different extensions.
            print ("User:%s has multiple images on disk.  Look in %s. "
                   "Unspecified results ahead. Thanks Remora." %
                   (user_id, root))
        pile_of_ids.append(user_id)

        if type in extensions:
            # I didn't get importing UserProfile to work, so
            # we'll just do this manually.
            cursor.execute("UPDATE users SET picture_type=%s WHERE id=%s",
                           [extensions[type], user_id])
        else:
            print "Unknown type: (user:%s) (type:%s)" % (user_id, type)

        total_processed += 1
        if total_processed % 1000 == 0:
            print "Processed %s..." % total_processed

    # Commit between each directory - might be a little excessive
    transaction.commit_unless_managed()

print "Total: %s" % total_processed
print "Done."
