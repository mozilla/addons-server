class DynamicBoolFieldsMixin(object):

    def _fields(self):
        """Returns array of all field names starting with 'has'."""
        return [f.name for f in self._meta.fields if f.name.startswith('has')]

    def to_dict(self):
        return dict((f, getattr(self, f)) for f in self._fields())

    def to_keys(self):
        return [k for k, v in self.to_dict().iteritems() if v]

    def to_list(self):
        keys = self.to_keys()
        # Strip `has_` from each feature.
        field_names = [self.field_source[key[4:].upper()]['name']
                       for key in keys]
        return sorted(field_names)
