import re

from django.utils.functional import cached_property


BIGINT_POSITIVE_MAX = 2**63 - 1
APP_MAJOR_VERSION_PART_MAX = 2**16 - 1
APP_MINOR_VERSION_PART_MAX = 99

version_re = re.compile(
    r"""(?P<major>\d+|\*)      # major (x in x.y)
                            \.?(?P<minor1>\d+|\*)? # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version
                        """,
    re.VERBOSE,
)

LETTERS = ['alpha', 'pre']
NUMBERS = ['major', 'minor1', 'minor2', 'minor3', 'alpha_ver', 'pre_ver']
ASTERISK = '*'


def version_dict(version):
    """Turn a version string into a dict with major/minor/... info."""
    match = version_re.match(version or '')

    if match:
        vdict = match.groupdict()
        for letter in LETTERS:
            vdict[letter] = vdict[letter] if vdict[letter] else None
        for num in NUMBERS:
            if vdict[num] != ASTERISK:
                vdict[num] = int(vdict[num]) if vdict[num] else None
    else:
        vdict = {number_part: None for number_part in NUMBERS}
        vdict.update((letter_part, None) for letter_part in LETTERS)
    return vdict


def seq_get(sequence, index, default):
    return sequence[index] if index < len(sequence) else default


class VersionString(str):
    class Part:
        """Each version part is itself parsed as a sequence of four parts:
        <number-a><string-b><number-c><string-d>. Each of the parts is optional.
        Numbers are integers base 10 (may be negative), strings are non-numeric
        ASCII characters. Missing version parts are treated as if they were 0 or ''.
        """

        a = 0
        b = ''
        c = 0
        d = ''

        SPLIT_INT_REGEX = re.compile(r' *(?P<int>\-?[\d]+)(?P<rest>.*)')
        SPLIT_STR_REGEX = re.compile(r'(?P<str>[^\d\-]+)(?P<int>\-?[\d]*)(?P<rest>.*)')

        def __init__(self, part_string=''):
            if not part_string:
                return

            # If the version part is a single asterisk, it is interpreted as an
            # infinitely-large number.
            if part_string == ASTERISK:
                self.a = ASTERISK
                return

            split = self.SPLIT_INT_REGEX.match(part_string)
            if not split:
                return
            try:
                self.a = int(split['int'])
            except ValueError:
                return
            rest = split['rest']

            # If b starts with a plus sign, a is incremented to be compatible with
            # the Firefox 1.0.x version format.
            if rest.startswith('+'):
                self.a += 1
                self.b = 'pre'
            elif rest:
                split = self.SPLIT_STR_REGEX.match(rest)
                if not split:
                    self.b = rest
                else:
                    self.b = split['str']
                    if split['int'] is not None:
                        try:
                            self.c = int(split['int'])
                        except ValueError:
                            return
                        self.d = split['rest']

        def __eq__(self, other):
            return all(
                getattr(self, sub) == getattr(other, sub, None) for sub in 'abcd'
            )

        def __gt__(self, other):
            if self.a == ASTERISK:
                return other.a != ASTERISK
            if other.a == ASTERISK:
                return False

            for subpart in 'abcd':
                self_subpart = getattr(self, subpart)
                other_subpart = getattr(other, subpart)
                if subpart != 'a' and not self_subpart:
                    return bool(other_subpart)
                elif subpart != 'a' and not other_subpart:
                    return False
                elif self_subpart != other_subpart:
                    return self_subpart > other_subpart
            return False

        def __ge__(self, other):
            return self.__eq__(other) or self.__gt__(other)

        def __lt__(self, other):
            return not self.__ge__(other)

        def __le__(self, other):
            return not self.__gt__(other)

        def asdict(self):
            return {key: getattr(self, key) for key in 'abcd'}

        def __repr__(self):
            return f'{self.asdict()}'

        def __str__(self):
            return f'{self.a}{self.b}{(self.c or "")}{self.d}'

    @cached_property
    def vparts(self):
        return tuple(self.Part(vpart) for vpart in self.split('.'))

    def __eq__(self, other):
        if other is None or (bool(self) ^ bool(other)):
            return False
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        self_part = self.Part('')
        other_part = self.Part('')
        for idx in range(0, max(len(self.vparts), len(other.vparts))):
            self_part = seq_get(
                self.vparts, idx, self_part if self_part.a == ASTERISK else self.Part()
            )
            other_part = seq_get(
                other.vparts,
                idx,
                other_part if other_part.a == ASTERISK else self.Part(),
            )
            if self_part != other_part:
                return False
        return True

    def __gt__(self, other):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        for idx in range(0, max(len(self.vparts), len(other.vparts))):
            self_part = seq_get(self.vparts, idx, self.Part())
            other_part = seq_get(other.vparts, idx, self.Part())
            if self_part != other_part:
                return self_part > other_part
        return False

    def __ge__(self, other):
        return self.__gt__(other) or self.__eq__(other)

    def __lt__(self, other):
        return not self.__ge__(other)

    def __le__(self, other):
        return not self.__gt__(other)

    __hash__ = str.__hash__


def version_int(version):
    """This is used for converting an app version's version string into a
    single number for comparison.  To maintain compatibility the minor parts
    are limited to 99 making it unsuitable for comparing addon version strings.
    """
    vdict = version_dict(str(version))
    last_part_value = None
    for part in NUMBERS:
        # reset last_part_value once we get to the alpha/pre parts
        if part in ('alpha_ver', 'pre_ver'):
            last_part_value = None
        if vdict[part] is None:
            # if the part was missing it's 0, unless the last part was *;
            # then it inherits the * and is max value.
            vdict[part] = ASTERISK if last_part_value == ASTERISK else 0
        else:
            last_part_value = vdict[part]

        max_num = (
            APP_MAJOR_VERSION_PART_MAX
            if part == 'major'
            else APP_MINOR_VERSION_PART_MAX
        )
        vdict[part] = max_num if vdict[part] == ASTERISK else min(vdict[part], max_num)
    vdict['alpha'] = {'a': 0, 'b': 1}.get(vdict['alpha'], 2)
    vdict['pre'] = 0 if vdict['pre'] else 1

    vint = '%d%02d%02d%02d%d%02d%d%02d' % (
        vdict['major'],
        vdict['minor1'],
        vdict['minor2'],
        vdict['minor3'],
        vdict['alpha'],
        vdict['alpha_ver'],
        vdict['pre'],
        vdict['pre_ver'],
    )
    return min(int(vint), BIGINT_POSITIVE_MAX)
