from collections import OrderedDict, namedtuple

from mongodb import fields

FieldInfo = namedtuple('FieldResult', [
    'pk',  # Model field instance
    'fields',  # Dict of field name -> model field instance
    'fields_and_pk',  # Shortcut for 'pk' + 'fields'
])

COMPOUND_FIELD_TYPES = (
    fields.DictField,
    fields.ListField
)


def is_abstract_document(document):
    return hasattr(document, 'meta') and document.meta.get('abstract', False)


def get_field_kwargs(document_field):
    """
    Creating a default instance of a basic non-relational field.
    """
    kwargs = {}

    if document_field.primary_key or document_field.db_column == '_id':
        # If this field is read-only, then return early.
        # Further keyword arguments are not valid.
        kwargs['read_only'] = True
        return kwargs

    if document_field.null:
        kwargs['allow_null'] = True
        if isinstance(document_field, fields.CharField):
            kwargs['allow_blank'] = True

    if document_field.choices:
        # If this document field contains choices, then return early.
        # Further keyword arguments are not valid.
        kwargs['choices'] = document_field.choices
        return kwargs

    if isinstance(document_field, (fields.CharField)):
        if document_field.regex:
            kwargs['regex'] = document_field.regex
        max_length = getattr(document_field, 'max_length', None)
        min_length = getattr(document_field, 'min_length', None)
        if max_length:
            kwargs['max_length'] = max_length
        if min_length:
            kwargs['min_length'] = min_length

    if isinstance(document_field, (fields.IntegerField, fields.FloatField)):
        max_value = getattr(document_field, 'max_value', None)
        min_value = getattr(document_field, 'min_value', None)
        if max_value:
            kwargs['max_value'] = max_value
        if min_value:
            kwargs['min_value'] = min_value

    return kwargs


def has_default(document_field):
    return document_field.default is not None or document_field.null


def get_field_info(document):
    """
    Given a document class, returns a `FieldInfo` instance, which is a
    `namedtuple`, containing metadata about the various field types on
    the document including information about their relationships.
    """
    # Deal with the primary key.
    pk = document._fields[document._meta['id_field']]

    # Deal with regular fields.
    fields = OrderedDict()

    def add_field(name, field):
        if isinstance(field, COMPOUND_FIELD_TYPES):
            fields[name] = field
            if field.field:
                add_field(f'{name}.child', field.field)
        elif field == pk:
            return
        else:
            fields[name] = field

    for field_name in document._fields_ordered:
        add_field(field_name, document._fields[field_name])

    # Shortcut that merges both regular fields and the pk,
    # for simplifying regular field lookup.
    fields_and_pk = OrderedDict()
    fields_and_pk['pk'] = pk
    fields_and_pk[getattr(pk, 'name', 'pk')] = pk
    fields_and_pk.update(fields)

    return FieldInfo(pk, fields, fields_and_pk)
