import copy
from collections import OrderedDict

from rest_framework import fields as drf_fields
from rest_framework import serializers
# ALL_FIELDS constant for compatibility
try:
    from rest_framework.serializers import ALL_FIELDS
except ImportError:
    # In newer versions of DRF, ALL_FIELDS is replaced with '__all__'
    ALL_FIELDS = '__all__'
from rest_framework.utils.field_mapping import ClassLookupDict

from mongodb import fields as me_fields
from mongodb.errors import ValidationError
from mongodb.rest_framework import fields as drfm_fields
from mongodb.rest_framework.repr import serializer_repr
from mongodb.rest_framework.utils import (COMPOUND_FIELD_TYPES, get_field_info,
                                          get_field_kwargs, has_default,
                                          is_abstract_document)
from mongodb.rest_framework.validators import UniqueValidator


def raise_errors_on_nested_writes(method_name, serializer, validated_data):
    assert not any(
        isinstance(field, serializers.BaseSerializer)
        and (key in validated_data)
        for key, field in serializer.fields.items()
    ), (
        f'The `.{method_name}()` method does not support writable nested'
        f'fields by default.\nWrite an explicit `.{method_name}()` method for '
        f'serializer `{serializer.__class__.__module__}.{serializer.__class__.__name__}`, '
        'or set `read_only=True` on nested serializer fields.'
    )

    assert not any(
        '.' in field.source and (key in validated_data)
        and isinstance(validated_data[key], (list, dict))
        for key, field in serializer.fields.items()
    ), (
        f'The `.{method_name}()` method does not support writable '
        f'dotted-source fields by default.\nWrite an explicit '
        f'`.{method_name}()` method for serializer '
        f'`{serializer.__class__.__module__}.{serializer.__class__.__name__}`, '
        'or set `read_only=True` on dotted-source serializer fields.'
    )


class DocumentSerializer(serializers.ModelSerializer):
    """ Serializer for Documents.

    Recognized primitve fields:

        * ``CharField``
        * ``IntegerField``
        * ``DateTimeField``
        * ``ObjectIdField``
        * ``FloatField``
        * ``BooleanField``

    """

    serializer_field_mapping = {
        me_fields.CharField: drf_fields.CharField,
        me_fields.IntegerField: drf_fields.IntegerField,
        me_fields.DateTimeField: drf_fields.DateTimeField,
        me_fields.ObjectIdField: drfm_fields.ObjectIdField,
        me_fields.FloatField: drf_fields.FloatField,
        me_fields.BooleanField: drf_fields.BooleanField,
    }

    _saving_instances = True

    def create(self, validated_data):
        raise_errors_on_nested_writes(
            'create', self, validated_data)

        document = self.get_document()
        try:
            instance = self.recursive_save(validated_data)
        except TypeError as exc:
            raise TypeError(
                f"""
                    Got a `TypeError` when calling
                    `{document.__name__}.objects.create()`.
                    This may be because you have a writable
                    field on the serializer class that
                    is not a valid argument to
                    '`{document.__name__}.objects.create()`.
                    You may need to make the field read-only,
                    or override the {type(self).__name__}.create()
                    method to handle this correctly.\n
                    Original exception text was: {exc}.
                """
            ) from exc
        except ValidationError as exc:
            raise ValidationError(
                f"""
                    Got a `ValidationError` when calling
                    `{document.__name__}.objects.create()`.
                    This may be because request data satisfies
                    serializer validations but not mongodb`s.
                    You may need to check consistency between
                    {document.__name__} and {type(self).__name__}.\n
                    Original exception was: {exc}
                """
            ) from exc

        return instance

    def update(self, instance, validated_data):
        raise_errors_on_nested_writes('update', self, validated_data)
        instance = self.recursive_save(validated_data, instance)

        return instance

    def recursive_save(self, validated_data, instance=None):
        """
        Returns mongodb document instance.
        """

        data = {}

        for key, value in validated_data.items():
            try:
                data[key] = value
            except KeyError:  # this is dynamic data
                data[key] = value

        if not instance:
            instance = self.get_document()(**data)
        else:
            for key, value in data.items():
                setattr(instance, key, value)

        if self._saving_instances:
            instance.save()

        return instance

    def to_internal_value(self, data):
        """
        Calls super() from DRF.
        """

        return super().to_internal_value(data)

    def get_document(self):
        """
        By default returns the document defined in the Meta class.

        When customizing the behavior and the returned document may differ,
        overriding the 'fields' property will be necessary.
        'fields' is evaluated lazily and cached afterwards.
        """

        assert hasattr(self.Meta, 'model'), (
            f'''Class {self.__class__.__name__}
                missing "Meta.model" attribute'''
        )
        return self.Meta.model

    def get_fields(self):
        assert hasattr(self, 'Meta'), (
            'Class {serializer_class} missing "Meta" attribute'.format(
                serializer_class=self.__class__.__name__
            )
        )

        declared_fields = copy.deepcopy(self._declared_fields)
        model = self.get_document()

        if model is None:
            return {}

        if is_abstract_document(model):
            raise ValueError(
                'Cannot use DocumentSerializer with Abstract Documents.'
            )

        # Retrieve metadata about fields & relationships on the document class.
        self.field_info = get_field_info(model)
        field_names = self.get_field_names(declared_fields, self.field_info)
        # Determine any extra field arguments and hidden fields that
        # should be included
        extra_kwargs = self.get_extra_kwargs()
        extra_kwargs, hidden_fields = self.get_uniqueness_extra_kwargs(
            field_names, extra_kwargs)

        # Determine the fields that should be included on the serializer.
        fields = OrderedDict()

        for field_name in field_names:
            # If the field is explicitly declared on the class then use that.
            if field_name in declared_fields:
                fields[field_name] = declared_fields[field_name]
                # We assume that in this case no extra_kwargs etc.
                # should be considered No nested validators or
                # validate_*() methods need to be applied
                continue

            # Determine the serializer field class and keyword arguments.
            field_class, field_kwargs = self.build_field(
                field_name, self.field_info, model
            )

            extra_field_kwargs = extra_kwargs.get(field_name, {})
            field_kwargs = self.include_extra_kwargs(
                field_kwargs, extra_field_kwargs
            )

            # Create the serializer field.
            fields[field_name] = field_class(**field_kwargs)

        # Add in any hidden fields.
        fields.update(hidden_fields)

        return fields

    def get_field_names(self, declared_fields, info):
        """
        Returns the list of all field names that should be created when
        instantiating this serializer class. This is based on the default
        set of fields, but also takes into account the `Meta.fields` or
        `Meta.exclude` options if they have been specified.

        """
        fields = getattr(self.Meta, 'fields', None)
        exclude = getattr(self.Meta, 'exclude', None)

        if fields and fields != ALL_FIELDS and \
                not isinstance(fields, (list, tuple)):
            raise TypeError(
                'The `fields` option must be a list or tuple or "__all__". '
                f'Got {type(fields).__name__}.'
            )

        if exclude and not isinstance(exclude, (list, tuple)):
            raise TypeError(
                f'''The `exclude` option must be a list or tuple.
                Got {type(exclude).__name__}.'''
            )

        assert not fields or not exclude, (
            "Cannot set both 'fields' and 'exclude' options on "
            f"serializer {self.__class__.__name__}."
        )

        if fields == ALL_FIELDS:
            fields = self.get_default_field_names(declared_fields, info)
        elif fields is None:
            # Use the default set of field names
            # if `Meta.fields` is not specified.
            fields = self.get_default_field_names(declared_fields, info)

            if exclude is not None:
                # If `Meta.exclude` is included, then remove those fields.
                for field_name in exclude:
                    if '.' not in field_name:
                        # ignore customization of nested fields -
                        # they'll be handled separately
                        assert field_name in fields, (
                            f"The field '{field_name}' was included on "
                            f"serializer {self.__class__.__name__} in the "
                            "'exclude' option, but doesn't match any "
                            "document field."
                        )
                        fields.remove(field_name)

        else:
            # Ensure that all declared fields have also
            # been included in the `Meta.fields` option.

            required_field_names = set(declared_fields)
            for cls in self.__class__.__bases__:
                required_field_names -= set(
                    getattr(cls, '_declared_fields', []))

            for field_name in required_field_names:
                assert field_name in fields, (
                    f"The field '{field_name}' was declared on serializer "
                    f"{self.__class__.__name__}, but has not been included"
                    " in the 'fields' option."
                )
        # filter out child fields
        return [field_name for field_name in fields if '.' not in field_name]

    def get_default_field_names(self, declared_fields, document_info):
        return (
            [document_info.pk.name]
            + list(declared_fields.keys())
            + list(document_info.fields.keys())
        )

    def build_field(self, field_name, info, document_class):
        if field_name in info.fields_and_pk:
            document_field = info.fields_and_pk[field_name]
            if isinstance(document_field, COMPOUND_FIELD_TYPES):
                return self.build_compound_field(field_name, document_field)
            else:
                return self.build_standard_field(field_name, document_field)

        if hasattr(document_class, field_name):
            return self.build_property_field(field_name, document_class)

        return self.build_unknown_field(field_name, document_class)

    def build_standard_field(self, field_name, document_field):
        field_mapping = ClassLookupDict(self.serializer_field_mapping)

        field_class = field_mapping[document_field]
        field_kwargs = get_field_kwargs(document_field)

        if 'choices' in field_kwargs:
            # Fields with choices get coerced into `ChoiceField`
            # instead of using their regular typed field.
            field_class = self.serializer_choice_field
            # Some document fields may introduce kwargs that would not be valid
            # for the choice field. We need to strip these out.
            valid_kwargs = {
                'read_only', 'write_only',
                'required', 'default', 'initial', 'source',
                'error_messages', 'validators', 'allow_null', 'allow_blank',
                'choices'
            }
            for key in list(field_kwargs.keys()):
                if key not in valid_kwargs:
                    field_kwargs.pop(key)

        if 'regex' in field_kwargs:
            field_class = drf_fields.RegexField

        if not issubclass(field_class, drf_fields.CharField) and \
                not issubclass(field_class, drf_fields.ChoiceField):
            # `allow_blank` is only valid for textual fields.
            field_kwargs.pop('allow_blank', None)

        if field_class == drf_fields.BooleanField and \
                field_kwargs.get('allow_null', False):
            field_kwargs.pop('allow_null', None)
            field_kwargs.pop('default', None)
            field_class = drf_fields.NullBooleanField

        return field_class, field_kwargs

    def build_compound_field(self, field_name, document_field):
        if isinstance(document_field, me_fields.ListField):
            field_class = drf_fields.ListField
        elif isinstance(document_field, me_fields.DictField):
            field_class = drf_fields.DictField

        field_kwargs = get_field_kwargs(document_field)
        field_kwargs.pop('document_field', None)

        return field_class, field_kwargs

    def get_uniqueness_extra_kwargs(self, field_names, extra_kwargs):
        # extra_kwargs contains 'default',
        # 'required', 'validators=[UniqueValidator]'
        # hidden_fields contains fields involved in
        # constraints, but missing in serializer fields
        model = self.get_document()

        hidden_fields = {}

        field_names = set(field_names)
        unique_fields = set()
        unique_together_fields = set()

        uniq_extra_kwargs = {
            field_name: {
                'required': True,
                'validators': [UniqueValidator(queryset=model.objects)],
            }
            for field_name in unique_fields
        }
        for field_name in unique_together_fields:
            fld = model._fields[field_name]
            if has_default(fld):
                uniq_extra_kwargs[field_name] = {'default': fld.default}
            else:
                uniq_extra_kwargs[field_name] = {'required': True}

        # Update `extra_kwargs` with any new options.
        for key, value in uniq_extra_kwargs.items():
            if key in extra_kwargs:
                if key == 'validators':
                    extra_kwargs[key].append(value)
                extra_kwargs[key].update(value)
            else:
                extra_kwargs[key] = value

        return extra_kwargs, hidden_fields

    def __repr__(self):
        return serializer_repr(self, indent=1)

    def get_unique_together_validators(self):
        # implement unique feature later
        return []

    def get_unique_for_date_validators(self):
        # not supported in mongo
        return []
