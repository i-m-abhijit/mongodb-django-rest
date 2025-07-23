"""
Helper functions for creating user-friendly representations
of serializer classes and serializer fields.
"""

import re

from django.utils.encoding import force_str
from rest_framework.fields import Field

from mongodb.base.document import BaseDocument
from mongodb.fields import BaseField
from mongodb.queryset import QuerySet


def manager_repr(value):
    document = value._document
    return f'{document.__name__}.objects'


def mongo_field_repr(value):
    # mimic django models.Field.__repr__
    path = f'{value.__class__.__module__}.{value.__class__.__name__}'
    name = getattr(value, 'name', None)
    return f'<{path}: {name}>' if name is not None else f'<{path}>'


def mongo_doc_repr(value):
    # mimic django models.Model.__repr__
    try:
        u = str(value)
    except (UnicodeEncodeError, UnicodeDecodeError):
        u = '[Bad Unicode data]'
    return force_str(f'<{value.__class__.__name__}: {u}>')


uni_lit_re = re.compile("u'(.*?)'")


def smart_repr(value):
    if isinstance(value, QuerySet):
        return manager_repr(value)

    if isinstance(value, (BaseField, BaseDocument)):
        return mongo_field_repr(value)

    if isinstance(value, Field):
        return field_repr(value)

    value = repr(value)

    # Representations like u'help text'
    # should simply be presented as 'help text'
    value = uni_lit_re.sub("'\\1'", value)

    # Representations like
    # <django.core.validators.RegexValidator object at 0x1047af050>
    # Should be presented as
    # <django.core.validators.RegexValidator object>
    value = re.sub(' at 0x[0-9a-f]{4,32}>', '>', value)

    return value


def field_repr(field, force_many=False):
    kwargs = field._kwargs
    if force_many:
        kwargs = kwargs.copy()
        kwargs['many'] = True
        kwargs.pop('child', None)

    arg_string = ', '.join([smart_repr(val) for val in field._args])
    kwarg_string = ', '.join([
        f'{key}={smart_repr(val)}'
        for key, val in sorted(kwargs.items())
    ])
    if arg_string and kwarg_string:
        arg_string += ', '

    if force_many:
        class_name = force_many.__class__.__name__
    else:
        class_name = field.__class__.__name__

    return f"{class_name}({arg_string}{kwarg_string})"


def serializer_repr(serializer, indent, force_many=None):
    ret = f'{field_repr(serializer, force_many)}:'
    indent_str = '    ' * indent

    fields = force_many.fields if force_many else serializer.fields
    for field_name, field in fields.items():
        ret += '\n' + indent_str + field_name + ' = '
        if hasattr(field, 'fields'):
            ret += serializer_repr(field, indent + 1)
        else:
            ret += field_repr(field)

    if serializer.validators:
        ret += f'''\n{indent_str}class Meta:\n{indent_str}
           validators = {smart_repr(serializer.validators)}'''

    if len(fields) == 0:
        ret += "\npass"

    return ret
