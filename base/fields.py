import collections.abc
import operator

from bson import DBRef

from mongodb.base.datastructures import BaseDict, BaseList
from mongodb.errors import ValidationError
from mongodb.queryset.transform import UPDATE_OPERATORS


class BaseField:
    """Base class for all basic field types in MongoDB document"""

    name = None  # set in TopLevelDocumentMetaclass

    # These track each time a Field instance is created. Used to retain order.
    # The auto_creation_counter is used for fields that mongodb implicitly
    # creates, creation_counter is used for all user-specified fields.
    creation_counter = 0
    auto_creation_counter = -1

    def __init__(
        self,
        db_column=None,
        required=False,
        default=None,
        primary_key=False,
        validation=None,
        choices=None,
        null=False,
        **kwargs,
    ):
        """
        :param db_column: The database field to store this field in
            (defaults to the name of the field)
        :param required: If the field is required. Whether it has to have a
            value or not. Defaults to False.
        :param default: (optional) The default value for this field if no value
            has been set (or if the value has been unset).  It can be a
            callable.
        :param primary_key: Mark this field as the primary key.
            Defaults to False.
        :param validation: (optional) A callable to validate the value of the
            field.  The callable takes the value as parameter and should raise
            a ValidationError if validation fails
        :param choices: (optional) The valid choices
        :param null: (optional) If the field value can be null.
            If no and there is a default value then the default value is set
        """
        self.db_column = "_id" if primary_key else db_column
        self.required = required or primary_key
        self.default = default
        self.primary_key = primary_key
        self.validators = validation
        if isinstance(choices, collections.abc.Iterator):
            choices = list(choices)
        self.choices = choices
        self.null = null

        # Make sure db_column is a string (if it's explicitly defined).
        if self.db_column is not None and not isinstance(self.db_column, str):
            raise TypeError("db_column should be a string.")

        # Make sure db_column doesn't contain any forbidden characters.
        if isinstance(self.db_column, str) and (
            "." in self.db_column
            or "\0" in self.db_column
            or self.db_column.startswith("$")
        ):
            raise ValueError(
                'field names cannot contain dots (".") or null characters '
                '("\\0"), and they must not start with a dollar sign ("$").'
            )

        if conflicts := set(dir(self)) & set(kwargs):
            raise TypeError(
                f'{self.__class__.__name__} already has attribute(s): {", ".join(conflicts)}'
            )

        # Assign metadata to the instance
        # This efficient method is available because no __slots__ are defined.
        self.__dict__.update(kwargs)

        # Adjust the appropriate creation counter, and save our local copy.
        if self.db_column == "_id":
            self.creation_counter = BaseField.auto_creation_counter
            BaseField.auto_creation_counter -= 1
        else:
            self.creation_counter = BaseField.creation_counter
            BaseField.creation_counter += 1

    def __get__(self, instance, owner):
        """Descriptor for retrieving a value from a field in a document."""
        return self if instance is None else instance._data.get(self.name)

    def __set__(self, instance, value):
        """Descriptor for assigning a value to a field in a document."""
        # If setting to None and there is a default value provided for this
        # field, then set the value to the default value.
        if value is None:
            if self.null:
                value = None
            elif self.default is not None:
                value = self.default
                if callable(value):
                    value = value()

        if instance._initialised:
            try:
                value_has_changed = (
                    self.name not in instance._data
                    or instance._data[self.name] != value
                )
                if value_has_changed:
                    instance._mark_as_changed(self.name)
            except Exception:
                # Some values can't be compared and throw an error when we
                # attempt to do so (e.g. tz-naive and tz-aware datetimes).
                # Mark the field as changed in such cases.
                instance._mark_as_changed(self.name)

        instance._data[self.name] = value

    def error(self, message="", errors=None, field_name=None):
        """Raise a ValidationError."""
        field_name = field_name or self.name
        raise ValidationError(message, errors=errors, field_name=field_name)

    def to_python(self, value):
        """Convert a MongoDB-compatible type to a Python type."""
        return value

    def to_mongo(self, value):
        """Convert a Python type to a MongoDB-compatible type."""
        return self.to_python(value)

    def _to_mongo_safe_call(self, value, use_db_field=True, fields=None):
        """Helper method to call to_mongo with proper inputs."""
        f_inputs = self.to_mongo.__code__.co_varnames
        ex_vars = {}
        if "fields" in f_inputs:
            ex_vars["fields"] = fields

        if "use_db_field" in f_inputs:
            ex_vars["use_db_field"] = use_db_field

        return self.to_mongo(value, **ex_vars)

    def prepare_query_value(self, op, value):
        """Prepare a value that is being used in a query for PyMongo."""
        if op in UPDATE_OPERATORS:
            self.validate(value)
        return value

    def validate(self, value, clean=True):
        """Perform validation on a value."""
        pass

    def _validate_choices(self, value):
        from mongodb.document import Document

        choice_list = []
        if self.choices is not None:
            choice_list.extend(
                choice[0]
                for choice in self.choices
                if isinstance(choice, (list, tuple))
            )
        # Choices which are other types of Documents
        if isinstance(value, (Document,)):
            if not any(isinstance(value, c) for c in choice_list):
                self.error(f"Value must be an instance of {choice_list}")
        else:
            values = value if isinstance(value, (list, tuple)) else [value]
            if len(set(values) - set(choice_list)):
                self.error(f"Value must be one of {choice_list}")

    def _validate(self, value, **kwargs):
        # Check the Choices Constraint
        if self.choices:
            self._validate_choices(value)

        # check validation argument
        if self.validators is not None:
            if not callable(self.validators):
                raise ValueError(
                    f'validation argument for `"{self.name}"` must be callable'
                )

            try:
                self.validators(value)
            except ValidationError as ex:
                self.error(str(ex))
        self.validate(value, **kwargs)


class ComplexBaseField(BaseField):
    """Handles complex fields, such as lists / dictionaries.

    Allows for nesting of embedded documents inside complex types.
    Handles the lazy dereferencing of a queryset by lazily dereferencing all
    items in a list / dict rather than one at a time.
    """

    def __init__(self, field=None, **kwargs):
        self.field = field
        super().__init__(**kwargs)

    @staticmethod
    def _lazy_load_refs(instance, name, ref_values, *, max_depth):
        from mongodb.dereference import DeReference
        _dereference = DeReference()
        return _dereference(
            ref_values,
            max_depth=max_depth,
            instance=instance,
            name=name,
        )

    def __get__(self, instance, owner):
        """Descriptor to automatically dereference references."""
        if instance is None:
            # Document class being used rather than a document object
            return self

        dereference = self.field is None

        if (
            instance._initialised
            and dereference
            and instance._data.get(self.name)
            and not getattr(instance._data[self.name], "_dereferenced", False)
        ):
            ref_values = instance._data.get(self.name)
            instance._data[self.name] = self._lazy_load_refs(
                ref_values=ref_values,
                instance=instance,
                name=self.name, max_depth=1
            )
            if hasattr(instance._data[self.name], "_dereferenced"):
                instance._data[self.name]._dereferenced = True

        value = super().__get__(instance, owner)

        # Convert lists / values so we can watch for any changes on them
        if isinstance(value, (list, tuple)):
            if not isinstance(value, BaseList):
                value = BaseList(value, instance, self.name)
            instance._data[self.name] = value
        elif isinstance(value, dict) and not isinstance(value, BaseDict):
            value = BaseDict(value, instance, self.name)
            instance._data[self.name] = value

        if (
            instance._initialised
            and isinstance(value, (BaseList, BaseDict))
            and not value._dereferenced
        ):
            value = self._lazy_load_refs(
                ref_values=value,
                instance=instance,
                name=self.name, max_depth=1
            )
            instance._data[self.name] = value

        return value

    def to_python(self, value):
        """Convert a MongoDB-compatible type to a Python type."""
        from mongodb.document import BaseDocument
        if isinstance(value, (str, BaseDocument)):
            return value

        if hasattr(value, "to_python"):
            return value.to_python()

        is_list = False
        if not hasattr(value, "items"):
            try:
                is_list = True
                value = dict(enumerate(value))
            except TypeError:
                # If not iterable return the value
                return value
        return self._from_mongo_compatible_value_to_python_type_value_dict(
            value, is_list)

    def to_mongo(self, value, use_db_field=True, fields=None):
        """Convert a Python type to a MongoDB-compatible type."""
        if isinstance(value, str):
            return value

        if hasattr(value, "to_mongo"):
            return value.to_mongo(use_db_field, fields)

        is_list = False
        if not hasattr(value, "items"):
            try:
                is_list = True
                value = dict(enumerate(value))
            except TypeError:
                # if not iterable return the value
                return value
        return self._from_python_type_value_to_mongo_compatible_value_dict(
            value, is_list, use_db_field, fields)

    def validate(self, value):
        """If field is provided ensure the value is valid."""
        errors = {}
        if self.field:
            sequence = value.items() if hasattr(value, "items") \
                else enumerate(value)
            for k, v in sequence:
                try:
                    self.field._validate(v)
                except ValidationError as error:
                    errors[k] = error.errors or error
                except (ValueError, AssertionError) as error:
                    errors[k] = error

            if errors:
                field_class = self.field.__class__.__name__
                self.error(f"Invalid {field_class} item ({value})",
                           errors=errors)
        # Don't allow empty values if required
        if self.required and not value:
            self.error("Field is required and cannot be empty")

    def prepare_query_value(self, op, value):
        return self.to_mongo(value)

    def lookup_member(self, member_name):
        return self.field.lookup_member(member_name) if self.field else None

    def _set_owner_document(self, owner_document):
        if self.field:
            self.field.owner_document = owner_document
        self._owner_document = owner_document

    def _from_mongo_compatible_value_to_python_type_value_dict(
            self, value, is_list):
        from mongodb.document import Document
        if self.field:
            value_dict = {
                key: self.field.to_python(item) for key, item in value.items()
            }
        else:
            value_dict = {}
            for k, v in value.items():
                if isinstance(v, Document):
                    # We need the id from the saved object to create the DBRef
                    if v.pk is None:
                        self.error(
                            "You can only reference documents once they"
                            " have been saved to the database"
                        )
                    value_dict[k] = DBRef(v._get_collection_name(), v.pk)
                elif hasattr(v, "to_python"):
                    value_dict[k] = v.to_python()
                else:
                    value_dict[k] = self.to_python(v)

        if is_list:  # Convert back to a list
            return [
                v for _, v in sorted(value_dict.items(),
                                     key=operator.itemgetter(0))
            ]
        return value_dict

    def _from_python_type_value_to_mongo_compatible_value_dict(
            self, value, is_list, use_db_field, fields):
        from mongodb.document import Document
        if self.field:
            value_dict = {
                key: self.field._to_mongo_safe_call(item, use_db_field, fields)
                for key, item in value.items()
            }
        else:
            value_dict = {}
            for k, v in value.items():
                if isinstance(v, Document):
                    # We need the id from the saved object to create the DBRef
                    if v.pk is None:
                        self.error(
                            "You can only reference documents once they"
                            " have been saved to the database"
                        )
                    value_dict[k] = DBRef(v._get_collection_name(), v.pk)
                elif hasattr(v, "to_mongo"):
                    val = v.to_mongo(use_db_field, fields)
                    # If it's a document that is not inherited add _cls
                    if isinstance(v, (Document,)):
                        val["_cls"] = v.__class__.__name__
                    value_dict[k] = val
                else:
                    value_dict[k] = self.to_mongo(v, use_db_field, fields)

        if is_list:  # Convert back to a list
            return [
                v for _, v in sorted(
                    value_dict.items(), key=operator.itemgetter(0))
            ]
        return value_dict
