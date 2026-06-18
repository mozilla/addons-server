# This file's contents were copied from
# https://github.com/Zegocover/enmerkar/blob/master/enmerkar/extract.py as that
# package is not actively maintained.
#
# Copyright (C) 2013-2014 django-babel Team
# Copyright (C) 2019 Extracover Holdings Limited
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  1. Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#  2. Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in
#     the documentation and/or other materials provided with the
#     distribution.
#  3. The name of the author may not be used to endorse or promote
#     products derived from this software without specific prior
#     written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS
# OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
# GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
# IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from django.template.base import Lexer, TokenType
from django.utils.encoding import smart_str
from django.utils.translation import trim_whitespace
from django.utils.translation.template import (
    block_re,
    constant_re,
    endblock_re,
    inline_re,
    plural_re,
)


TOKEN_TEXT = TokenType.TEXT
TOKEN_VAR = TokenType.VAR
TOKEN_BLOCK = TokenType.BLOCK


def join_tokens(tokens, trim=False):
    message = ''.join(tokens)
    if trim:
        message = trim_whitespace(message)
    return message


def strip_quotes(s):
    if (s[0] == s[-1]) and s.startswith(("'", '"')):
        return s[1:-1]
    return s


def extract_django(fileobj, keywords, comment_tags, options):
    """Extract messages from Django template files.

    :param fileobj: the file-like object the messages should be extracted from
    :param keywords: a list of keywords (i.e. function names) that should
                     be recognized as translation functions
    :param comment_tags: a list of translator tags to search for and
                         include in the results
    :param options: a dictionary of additional options (optional)
    :return: an iterator over ``(lineno, funcname, message, comments)``
             tuples
    :rtype: ``iterator``
    """
    intrans = False
    inplural = False
    trimmed = False
    message_context = None
    singular = []
    plural = []
    lineno = 1

    encoding = options.get('encoding', 'utf8')
    text = fileobj.read().decode(encoding)

    try:
        text_lexer = Lexer(text)
    except TypeError:
        # Django 1.9 changed the way we invoke Lexer; older versions
        # require two parameters.
        text_lexer = Lexer(text, None)

    for t in text_lexer.tokenize():
        lineno += t.contents.count('\n')
        if intrans:
            if t.token_type == TOKEN_BLOCK:
                endbmatch = endblock_re.match(t.contents)
                pluralmatch = plural_re.match(t.contents)
                if endbmatch:
                    if inplural:
                        if message_context:
                            yield (
                                lineno,
                                'npgettext',
                                [
                                    smart_str(message_context),
                                    smart_str(join_tokens(singular, trimmed)),
                                    smart_str(join_tokens(plural, trimmed)),
                                ],
                                [],
                            )
                        else:
                            yield (
                                lineno,
                                'ngettext',
                                (
                                    smart_str(join_tokens(singular, trimmed)),
                                    smart_str(join_tokens(plural, trimmed)),
                                ),
                                [],
                            )
                    else:
                        if message_context:
                            yield (
                                lineno,
                                'pgettext',
                                [
                                    smart_str(message_context),
                                    smart_str(join_tokens(singular, trimmed)),
                                ],
                                [],
                            )
                        else:
                            yield (
                                lineno,
                                None,
                                smart_str(join_tokens(singular, trimmed)),
                                [],
                            )

                    intrans = False
                    inplural = False
                    message_context = None
                    singular = []
                    plural = []
                elif pluralmatch:
                    inplural = True
                else:
                    raise SyntaxError(
                        'Translation blocks must not include '
                        'other block tags: %s' % t.contents
                    )
            elif t.token_type == TOKEN_VAR:
                if inplural:
                    plural.append('%%(%s)s' % t.contents)
                else:
                    singular.append('%%(%s)s' % t.contents)
            elif t.token_type == TOKEN_TEXT:
                if inplural:
                    plural.append(t.contents)
                else:
                    singular.append(t.contents)
        else:
            if t.token_type == TOKEN_BLOCK:
                imatch = inline_re.match(t.contents)
                bmatch = block_re.match(t.contents)
                cmatches = constant_re.findall(t.contents)
                if imatch:
                    g = imatch.group(1)
                    g = strip_quotes(g)
                    message_context = imatch.group(3)
                    if message_context:
                        # strip quotes
                        message_context = message_context[1:-1]
                        yield (
                            lineno,
                            'pgettext',
                            [smart_str(message_context), smart_str(g)],
                            [],
                        )
                        message_context = None
                    else:
                        yield lineno, None, smart_str(g), []
                elif bmatch:
                    if bmatch.group(2):
                        message_context = bmatch.group(2)[1:-1]
                    for fmatch in constant_re.findall(t.contents):
                        stripped_fmatch = strip_quotes(fmatch)
                        yield lineno, None, smart_str(stripped_fmatch), []
                    intrans = True
                    inplural = False
                    trimmed = 'trimmed' in t.split_contents()
                    singular = []
                    plural = []
                elif cmatches:
                    for cmatch in cmatches:
                        stripped_cmatch = strip_quotes(cmatch)
                        yield lineno, None, smart_str(stripped_cmatch), []
            elif t.token_type == TOKEN_VAR:
                parts = t.contents.split('|')
                cmatch = constant_re.match(parts[0])
                if cmatch:
                    stripped_cmatch = strip_quotes(cmatch.group(1))
                    yield lineno, None, smart_str(stripped_cmatch), []
                for p in parts[1:]:
                    if p.find(':_(') >= 0:
                        p1 = p.split(':', 1)[1]
                        if p1[0] == '_':
                            p1 = p1[1:]
                        if p1[0] == '(':
                            p1 = p1.strip('()')
                        p1 = strip_quotes(p1)
                        yield lineno, None, smart_str(p1), []
