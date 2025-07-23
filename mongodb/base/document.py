import contextlib
import numbers
import warnings
from functools import partial

from bson import SON, DBRef, ObjectId, json_util

from mongodb.base.common import get_document
from mongodb.errors import (FieldDoesNotExist, InvalidDocumentError,
                            LookUpError, ValidationError)
from mongodb.pymongo_support import LEGACY_JSON_OPTIONS

NON_FIELD_ERRORS = "__all__"


class BaseDocument:
    # Currently, handling of `_changed_fields` seems unnecessarily convoluted:
    # 1. `BaseDocument` defines `_changed_fields` in its `__slots__`, yet it's
    #    not setting it to `[]` (or any other value) in `__init__`.
    # 2. `Document` does NOT set `_changed_fields` upon initialization. The
    #    field is primarily set via `_from_son` or `_clear_changed_fields`,
    #    though there are also other methods that manipulate it.
    __slots__ = (
        "_changed_fields",
        "_initialised",
        "_created",
        "_data",
        "_db_field_map",
    )

    STRICT = False

    def __init__(self, *args, **values):
        """
        Initialise a document

        :param values: A dictionary of keys and values for the document.
            It may contain additional reserved keywords, e.g. "__auto_convert".
        :param __auto_convert: If True, supplied values will be converted
            to Python-type values via each field's `to_python` method.
        :param _created: Indicates whether this is a brand new document
            or whether it's already been persisted before. Defaults to true.
        """
        self._initialised = False
        self._created = True

        if args:
            raise TypeError(
                "Instantiating a document with positional arguments is not "
                "supported. Please use `field_name=value` keyword arguments."
            )

        __auto_convert = values.pop("__auto_convert", True)

        _created = values.pop("_created", True)

        # Check if there are undefined fields supplied to the constructor,
        # if so raise an Exception.

        if self._meta.get("strict", True) or _created:
            if _undefined_fields := set(values.keys()) - set(
                list(self._fields.keys()) + ["id", "pk", "_cls", "_text_score"]
            ):
                raise FieldDoesNotExist(
                    f'''The fields "{_undefined_fields}" do not exist
                    on the document "{self._class_name}"'''
                )

        self._data = {}

        # Assign default values for fields
        # not set in the constructor
        for field_name in self._fields:
            if field_name in values:
                continue
            value = getattr(self, field_name, None)
            setattr(self, field_name, value)

        if "_cls" not in values:
            self._cls = self._class_name

        # Set actual values
        for key, value in values.items():
            field = self._fields.get(key)
            if (
                (field or key in ("id", "pk", "_cls"))
                and __auto_convert
                and value is not None
                and field
            ):
                value = field.to_python(value)
            setattr(self, key, value)
            self._data[key] = value

        # Set any get_<field>_display methods
        self.__set_field_display()

        # Flag initialised
        self._initialised = True
        self._created = _created

    def __delattr__(self, *args, **kwargs):
        """Handle deletions of fields"""
        field_name = args[0]
        if field_name in self._fields:
            default = self._fields[field_name].default
            if callable(default):
                default = default()
            setattr(self, field_name, default)
        else:
            super().__delattr__(*args, **kwargs)

    def __setattr__(self, name, value):
        try:
            self__created = self._created
        except AttributeError:
            self__created = True

        try:
            self__initialised = self._initialised
        except AttributeError:
            self__initialised = False

        # Check if the user has created a new instance of a class
        if (
            self._is_document
            and self__initialised
            and self__created
            and name == self._meta.get("id_field")
        ):
            super().__setattr__("_created", False)

        super().__setattr__(name, value)

    def __getstate__(self):
        data = {
            k: getattr(self, k)
            for k in (
                "_changed_fields",
                "_initialised",
                "_created",
                "_fields_ordered",
            )
            if hasattr(self, k)
        }
        data["_data"] = self.to_mongo()
        return data

    def __setstate__(self, data):
        if isinstance(data["_data"], SON):
            data["_data"] = self.__class__._from_son(data["_data"])._data
        for k in ("_changed_fields", "_initialised", "_created", "_data"):
            if k in data:
                setattr(self, k, data[k])
        if "_fields_ordered" in data:
            _super_fields_ordered = type(self)._fields_ordered
            self._fields_ordered = _super_fields_ordered

    def __iter__(self):
        return iter(self._fields_ordered)

    def __getitem__(self, name):
        """Dictionary-style field access, return a field's value if present."""
        with contextlib.suppress(AttributeError):
            if name in self._fields_ordered:
                return getattr(self, name)
        raise KeyError(name)

    def __setitem__(self, name, value):
        """Dictionary-style field access, set a field's value."""
        # Ensure that the field exists before settings its value
        if name not in self._fields:
            raise KeyError(name)
        return setattr(self, name, value)

    def __contains__(self, name):
        try:
            val = getattr(self, name)
            return val is not None
        except AttributeError:
            return False

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        try:
            u = self.__str__()
        except (UnicodeEncodeError, UnicodeDecodeError):
            u = "[Bad Unicode data]"
        repr_type = str if u is None else type(u)
        return repr_type(f"<{self.__class__.__name__}: {u}>")

    def __str__(self):
        if hasattr(self, "__unicode__"):
            return self.__unicode__()
        return f"{self.__class__.__name__} object {self.pk}"

    def __eq__(self, other):
        if (
            isinstance(other, self.__class__)
            and hasattr(other, "id")
            and other.id is not None
        ):
            return self.id == other.id
        if isinstance(other, DBRef):
            return (
                self._get_collection_name() == other.collection
                and self.id == other.id
            )
        return self is other if self.id is None else False

    def __ne__(self, other):
        return not self.__eq__(other)

    def clean(self):
        """
        Hook for doing document level data cleaning
        (usually validation or assignment) before validation is run.

        Any ValidationError raised by this method will not be associated with
        a particular field; it will have a special-case association with the
        field defined by NON_FIELD_ERRORS.
        """
        pass

    def get_text_score(self):
        """
        Get text score from text query
        """

        if "_text_score" not in self._data:
            raise InvalidDocumentError(
                "This document is not originally built from a text query"
            )

        return self._data["_text_score"]

    def to_mongo(self, use_db_field=True, fields=None):
        """
        Return as SON data ready for use with MongoDB.
        """
        fields = fields or []

        data = SON()
        data["_id"] = None
        data["_cls"] = self._class_name

        # only root fields ['test1.a', 'test2'] => ['test1', 'test2']
        root_fields = {f.split(".")[0] for f in fields}

        for field_name in self:
            if root_fields and field_name not in root_fields:
                continue

            value = self._data.get(field_name, None)
            field = self._fields.get(field_name)

            if value is not None:
                f_inputs = field.to_mongo.__code__.co_varnames
                ex_vars = {}
                if fields and "fields" in f_inputs:
                    key = f"{field_name}."
                    embedded_fields = [
                        i.replace(key, "") for i in fields if i.startswith(key)
                    ]

                    ex_vars["fields"] = embedded_fields

                if "use_db_field" in f_inputs:
                    ex_vars["use_db_field"] = use_db_field

                value = field.to_mongo(value, **ex_vars)

            if value not in [None, [], {}, ()] or field.null:
                if use_db_field:
                    data[field.db_column] = value
                else:
                    data[field.name] = value

        data.pop("_cls")
        return data

    def validate(self, clean=True, insertion=False, data=None):
        """Ensure that all fields values are valid.

        Raises :class:`ValidationError` if any of the fields' values are found
        to be invalid.
        """
        # Ensure that each field is matched to a valid value
        errors = {}
        if clean:
            try:
                self.clean()
            except ValidationError as error:
                errors[NON_FIELD_ERRORS] = error

        # Get a list of tuples of field names and their current values
        fields = []
        fields = [(self._fields.get(key), value)
                  for key, value in data.items()] if insertion \
            else [(self._fields.get(name), self._data.get(name))
                  for name in self._fields_ordered]

        for field, value in fields:
            if value is not None:
                try:
                    field._validate(value)
                except ValidationError as error:
                    errors[field.name] = error.errors or error
                except (ValueError, AttributeError, AssertionError) as error:
                    errors[field.name] = error
            elif field.required:
                errors[field.name] = ValidationError("Field is required",
                                                     field_name=field.name)
        if errors:
            pk = getattr(self, "pk", getattr(self._instance, "pk", None)
                         if hasattr(self, "_instance") else None)
            raise ValidationError(
                f"ValidationError ({self._class_name}:{pk}) ", errors=errors)

    def to_json(self, *args, **kwargs):
        """Convert this document to JSON.

        :param use_db_field: Serialize field names as they appear in
            MongoDB (as opposed to attribute names on this document).
            Defaults to True.
        """
        use_db_field = kwargs.pop("use_db_field", True)
        if "json_options" not in kwargs:
            warnings.warn(
                "No 'json_options' are specified! Falling back to "
                "LEGACY_JSON_OPTIONS with uuid_representation=PYTHON_LEGACY. "
                "For use with other MongoDB drivers specify the UUID "
                "representation to use.",
                DeprecationWarning,
            )
            kwargs["json_options"] = LEGACY_JSON_OPTIONS
        return json_util.dumps(self.to_mongo(use_db_field), *args, **kwargs)

    @classmethod
    def from_json(cls, json_data, created=False, **kwargs):
        """Converts json data to a Document instance

        :param str json_data: The json data to load into the Document
        :param bool created: Boolean defining whether to consider the newly
            instantiated document as brand new or as persisted already:
            * If True, consider the document as brand new, no matter what data
              it's loaded with (i.e. even if an ID is loaded).
            * If False and an ID is NOT provided, consider the document as
              brand new.
            * If False and an ID is provided, assume that the object has
              already been persisted (this has an impact on the subsequent
              call to .save()).
            * Defaults to ``False``.
        """
        # TODO should `created` default to False? If the object already exists
        # in the DB, you would likely retrieve it from MongoDB itself through
        # a query, not load it from JSON data.
        if "json_options" not in kwargs:
            warnings.warn(
                "No 'json_options' are specified! Falling back to "
                "LEGACY_JSON_OPTIONS with uuid_representation=PYTHON_LEGACY. "
                "For use with other MongoDB drivers specify the UUID "
                "representation to use.",
                DeprecationWarning,
            )
            kwargs["json_options"] = LEGACY_JSON_OPTIONS
        return cls._from_son(
            json_util.loads(json_data, **kwargs),
            created=created)

    def _mark_as_changed(self, key):
        """Mark a key as explicitly changed by the user."""
        if not key or not hasattr(self, "_changed_fields"):
            return

        if "." in key:
            key, rest = key.split(".", 1)
            key = f"{self._db_field_map.get(key, key)}.{rest}"
        else:
            key = self._db_field_map.get(key, key)

        if key not in self._changed_fields:
            levels, idx = key.split("."), 1
            while idx <= len(levels):
                if ".".join(levels[:idx]) in self._changed_fields:
                    break
                idx += 1
            else:
                self._changed_fields.append(key)
                # remove lower level changed fields
                level = ".".join(levels[:idx]) + "."
                remove = self._changed_fields.remove
                for field in self._changed_fields[:]:
                    if field.startswith(level):
                        remove(field)

    def _clear_changed_fields(self):
        """Using _get_changed_fields iterate and remove any fields that
        are marked as changed.
        """

        for changed in self._get_changed_fields():
            data = self
            for part in changed.split("."):
                if isinstance(data, list):
                    try:
                        data = data[int(part)]
                    except IndexError:
                        data = None
                elif isinstance(data, dict):
                    data = data.get(part, None)
                else:
                    field_name = data._reverse_db_field_map.get(part, part)
                    data = getattr(data, field_name, None)

                if hasattr(data, "_changed_fields") and not getattr(
                    data, "_is_document", False
                ):
                    data._changed_fields = []

        self._changed_fields = []

    def _get_changed_fields(self):
        """Return a list of all fields that have explicitly been changed."""

        changed_fields = []
        changed_fields += getattr(self, "_changed_fields", [])

        for field_name in self._fields_ordered:
            db_field_name = self._db_field_map.get(field_name, field_name)

            if db_field_name in changed_fields:
                # Whole field already marked as changed, no need to go further
                continue

        return changed_fields

    @staticmethod
    def _fetch_each_set_item_from_its_path(set_fields, doc, set_data):
        for path in set_fields:
            parts = path.split(".")
            d = doc
            new_path = []
            for p in parts:
                if isinstance(d, (ObjectId, DBRef)):
                    # Don't dig in the references
                    break
                elif isinstance(d, list) and p.isdigit():
                    # An item of a list
                    # (identified by its index) is updated
                    d = d[int(p)]
                elif hasattr(d, "get"):
                    # dict-like object
                    d = d.get(p)
                new_path.append(p)
            path = ".".join(new_path)
            set_data[path] = d

    def remove_null_values(self, d, unset_data):
        """Recursively remove keys with None values from a dictionary
        and populate unset_data with removed keys."""
        keys_to_remove = []
        for key, value in list(d.items()):
            if value is None:
                unset_data[key] = 1
                keys_to_remove.append(key)
            elif isinstance(value, dict):
                self.remove_null_values(value, unset_data)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, (dict, list)):
                        self.remove_null_values(item, unset_data)

        for key in keys_to_remove:
            d.pop(key, None)

    def _delta(self):
        """Returns the delta (set, unset) of the changes for a document.
        Gets any values that have been explicitly changed.
        """
        # Handles cases where not loaded from_son but has _id
        doc = self.to_mongo()

        set_fields = self._get_changed_fields()
        unset_data = {}
        if hasattr(self, "_changed_fields"):
            set_data = {}
            # Fetch each set item from its path
            BaseDocument._fetch_each_set_item_from_its_path(
                set_fields, doc, set_data)
        else:
            set_data = doc
            if "_id" in set_data:
                del set_data["_id"]

        # Remove keys with None values from set_data
        self.remove_null_values(d=set_data, unset_data=unset_data)

        # Determine if any changed items were actually unset
        for path, value in list(set_data.items()):
            # Account for 0 and True that are truthy
            if value or isinstance(value, (numbers.Number, bool)):
                continue

            parts = path.split(".")

            # If we've set a value that ain't the default value don't unset it
            default = None
            if path in self._fields:
                default = self._fields[path].default
            else:
                # Perform a full lookup for lists
                d = self
                db_field_name = parts.pop()
                for p in parts:
                    if isinstance(d, list) and p.isdigit():
                        d = d[int(p)]
                    elif hasattr(d, "__getattribute__") and \
                            not isinstance(d, dict):
                        real_path = d._reverse_db_field_map.get(p, p)
                        d = getattr(d, real_path)
                    else:
                        d = d.get(p)

                if hasattr(d, "_fields"):
                    field_name = d._reverse_db_field_map.get(
                        db_field_name, db_field_name
                    )
                    default = d._fields.get(
                        field_name).default \
                        if field_name in d._fields else None

            if default is not None:
                default = default() if callable(default) else default

            if value != default:
                continue

            del set_data[path]
            unset_data[path] = 1
        return set_data, unset_data

    @classmethod
    def _get_collection_name(cls):
        """Return the collection name for this class. None for abstract
        class.
        """
        return cls._meta.get("collection", None)

    @classmethod
    def _from_son(cls, son, created=False):
        """Create an instance of a Document
        (subclass) from a PyMongo SON (dict)"""
        if son and not isinstance(son, dict):
            raise ValueError(
                f"""The source SON object needs to be of type
                 'dict' but a '{type(son)}' was found"""
            )

        # Get the class name from the document,
        # falling back to the given class if unavailable
        class_name = son.get("_cls", cls._class_name)

        # Convert SON to a data dict, making sure each key is a string and
        # corresponds to the right db field.
        data = {}
        for key, value in son.items():
            key = str(key)
            key = cls._db_field_map.get(key, key)
            data[key] = value
        # Return correct subclass for document type
        if class_name != cls._class_name:
            cls = get_document(class_name)

        errors_dict = {}
        fields = cls._fields

        for field_name, field in fields.items():
            if field.db_column in data:
                value = data[field.db_column]
                try:
                    data[field_name] = value if value is None \
                        else field.to_python(value)
                    if field_name != field.db_column:
                        del data[field.db_column]
                except (AttributeError, ValueError) as e:
                    errors_dict[field_name] = e

        if errors_dict:
            errors = "\n".join(
                [f"Field '{k}' - {v}" for k, v in errors_dict.items()])
            raise InvalidDocumentError(
                f"""Invalid data to create a
                `{cls._class_name}` instance.\n{errors}""")

        # In STRICT documents, remove any keys that aren't in cls._fields
        if cls.STRICT:
            data = {k: v for k, v in data.items() if k in cls._fields}

        obj = cls(__auto_convert=False, _created=created, **data)
        obj._changed_fields = []
        return obj

    @classmethod
    def _lookup_field(cls, parts):
        """Given the path to a given field, return a list containing
        the Field object associated with that field and all of its parent
        Field objects.

        Args:
            parts (str, list, or tuple) - path to the field. Should be a
            string for simple fields existing on this document or a list
            of strings for a field that exists deeper in embedded documents.

        Returns:
            A list of Field instances for fields that were found or
            strings for sub-fields that weren't.

        Example:
            >>> user._lookup_field('name')
            [<mongodb.fields.StringField at 0x1119bff50>]

            >>> user._lookup_field('doesnt_exist')
            raises LookUpError

        """

        if not isinstance(parts, (list, tuple)):
            parts = [parts]

        fields = []
        field = None
        from mongodb.fields import ListField
        for field_name in parts:
            # Handle ListField indexing:
            if field_name.isdigit() and isinstance(field, ListField):
                fields.append(field_name)
                continue

            # Look up first field from the document
            if field is None:
                if field_name == "pk":
                    # Deal with "primary key" alias
                    field_name = cls._meta["id_field"]
                if field_name in cls._fields:
                    field = cls._fields[field_name]
                else:
                    raise LookUpError(f'Cannot resolve field "{field_name}"')
            else:
                # If the parent field has a "field" attribute which has a
                # lookup_member method, call it to find the field
                # corresponding to this iteration.
                if hasattr(getattr(field, "field", None), "lookup_member"):
                    new_field = field.field.lookup_member(field_name)

                elif hasattr(field, "lookup_member"):
                    new_field = field.lookup_member(field_name)

                else:
                    raise LookUpError(
                        f"Cannot resolve subfield or operator {field_name} on the field {field.name}"
                    )

                # If current field still wasn't found and the parent field
                # is a ComplexBaseField, add the name current field name and
                # move on.
                from mongodb.fields import ComplexBaseField
                if not new_field and isinstance(field, ComplexBaseField):
                    fields.append(field_name)
                    continue
                elif not new_field:
                    raise LookUpError(f'Cannot resolve field "{field_name}"')

                field = new_field  # update field to the new field type
            fields.append(field)

        return fields

    @classmethod
    def _translate_field_name(cls, field, sep="."):
        """Translate a field attribute name to a database field name."""
        parts = field.split(sep)
        parts = [f.db_column for f in cls._lookup_field(parts)]
        return ".".join(parts)

    def __set_field_display(self):
        """For each field that specifies choices, create a
        get_<field>_display method.
        """
        fields_with_choices = [
            (n, f) for n, f in self._fields.items() if f.choices]
        for attr_name, field in fields_with_choices:
            setattr(
                self,
                f"get_{attr_name}_display",
                partial(self.__get_field_display, field=field),
            )

    def __get_field_display(self, field):
        """Return the display value for a choice field"""
        value = getattr(self, field.name)
        if field.choices and isinstance(field.choices[0], (list, tuple)):
            if value is None:
                return None
            sep = getattr(field, "display_sep", " ")
            values = ([value])
            return sep.join(
                [str(dict(field.choices).get(val, val))
                    for val in values or []]
            )
        return value
