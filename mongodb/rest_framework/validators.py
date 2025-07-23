from rest_framework import validators
from rest_framework.exceptions import ValidationError

from mongodb.rest_framework.repr import smart_repr


class MongoValidatorMixin():
    def exclude_current_instance(self, queryset, instance):
        return queryset if instance is None else queryset.filter(pk__ne=instance.pk)


class UniqueValidator(MongoValidatorMixin, validators.UniqueValidator):
    """ Replacement of DRF UniqueValidator.

    Used by :class:`DocumentSerializer` for fields, present in unique indexes.
    """

    def __init__(self, queryset, message=None, lookup=''):
        """
        Setting empty string as default lookup for UniqueValidator.
        """
        super().__init__(queryset, message, lookup)

    def __call__(self, value, serializer_field):
        # Determine the underlying document field name. This may not be the
        # same as the serializer field name if `source=<>` is set.
        field_name = serializer_field.source_attrs[-1]
        # Determine the existing instance, if this is an update operation.
        instance = getattr(serializer_field.parent, 'instance', None)

        queryset = self.queryset
        queryset = self.filter_queryset(value, queryset, field_name)
        queryset = self.exclude_current_instance(queryset, instance)

        if queryset.first():
            raise ValidationError(self.message.format())

    def __repr__(self):
        return f'<{self.__class__.__name__}(queryset={smart_repr(self.queryset)})>'
