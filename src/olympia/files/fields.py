import os
import os.path

# FieldFile is the underyling File proxy, FileField is the database field.
from django.db.models.fields.files import FieldFile, FileField


class _FileNameFieldFile(FieldFile):
    """Custom django FieldFile to go with LegacyFilenameFileField. When
    instantiated with a pre-migration `name` value coming from the database
    without containing directories, adds <addonid>/ prefix automatically.

    Temporary while we are migrating files under a new directory structure:
    once everything is migrated this will go away."""

    def __init__(self, instance, field, name):
        if name and '/' not in name:
            # pre-migrated value, we stored just the name without the leading
            # directory so we need to add it so that Django finds the File.
            # It's just the add-on id.
            name = os.path.join(str(instance.version.addon_id), name)
        super().__init__(instance, field, name)


class FilenameFileField(FileField):
    """A django FileField that stores the basename in the database for
    pre-migrated files, reconstructing the full path through FileNameFieldFile
    when converted back to python.

    Temporary while we are migrating files under a new directory structure:
    once everything is migrated we'll be able to use a regular FileField."""

    attr_class = _FileNameFieldFile

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value.count('/') == 1:
            # If we only have one slash, that means the file hasn't been
            # migrated. Return the basename for backwards-compatibility.
            value = os.path.basename(value)
        return value
