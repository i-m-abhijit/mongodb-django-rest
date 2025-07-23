import contextlib
import datetime
import re

import dateutil
from bson import ObjectId

from mongodb.base.document import BaseDocument
from mongodb.base.fields import BaseField, ComplexBaseField
from mongodb.queryset.base import BaseQuerySet
from mongodb.queryset.transform import STRING_OPERATORS

RECURSIVE_REFERENCE_CONSTANT = "self"


class ObjectIdField(BaseField):
    """A field wrapper around MongoDB's ObjectIds."""

    def to_python(self, value):
        with contextlib.suppress(Exception):
            if not isinstance(value, ObjectId):
                value = ObjectId(value)
        return value

    def to_mongo(self, value):
        if not isinstance(value, ObjectId):
            try:
                return ObjectId(str(value))
            except Exception as e:
                self.error(str(e))
        return value

    def prepare_query_value(self, op, value):
        return self.to_mongo(value)

    def validate(self, value):
        try:
            ObjectId(str(value))
        except Exception:
            self.error("Invalid ObjectID")


class IntegerField(BaseField):
    """32-bit integer field."""

    def __init__(self, min_value=None, max_value=None, **kwargs):
        """
        :param min_value: (optional) A min value that
                        will be applied during validation
        :param max_value: (optional) A max value that
                        will be applied during validation
        :param kwargs: Keyword arguments passed into
                        the parent :class:`BaseField`
        """
        self.min_value, self.max_value = min_value, max_value
        super().__init__(**kwargs)

    def to_python(self, value):
        with contextlib.suppress(TypeError, ValueError):
            value = int(value)
        return value

    def validate(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            self.error(f"{value} could not be converted to int")

        if self.min_value is not None and value < self.min_value:
            self.error("Integer value is too small")

        if self.max_value is not None and value > self.max_value:
            self.error("Integer value is too large")

    def prepare_query_value(self, op, value):
        return value if value is None else super().prepare_query_value(op, int(value))


class CharField(BaseField):
    """A unicode string field."""

    def __init__(self, regex=None, max_length=None, min_length=None, **kwargs):
        """
        :param regex: (optional) A string pattern that
                    will be applied during validation
        :param max_length: (optional) A max length that
                    will be applied during validation
        :param min_length: (optional) A min length that
                    will be applied during validation
        :param kwargs: Keyword arguments passed into
                    the parent :class:`BaseField`
        """
        self.regex = re.compile(regex) if regex else None
        self.max_length = max_length
        self.min_length = min_length
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            return value
        with contextlib.suppress(Exception):
            value = value.decode("utf-8")
        return value

    def validate(self, value):
        if not isinstance(value, str):
            self.error("StringField only accepts string values")

        if self.max_length is not None and len(value) > self.max_length:
            self.error("String value is too long")

        if self.min_length is not None and len(value) < self.min_length:
            self.error("String value is too short")

        if self.regex is not None and self.regex.match(value) is None:
            self.error("String value did not match validation regex")

    def lookup_member(self, member_name):
        return None

    def prepare_query_value(self, op, value):
        if not isinstance(op, str):
            return value

        if op in STRING_OPERATORS:
            case_insensitive = op.startswith("i")
            op = op.lstrip("i")

            flags = re.IGNORECASE if case_insensitive else 0

            regex = r"%s"
            operator_regex_map = {"startswith": r"^%s", "endswith": r"%s$",
                                  "exact": r"^%s$", "wholeword": r"\b%s\b",
                                  "regex": value}
            regex = operator_regex_map.get(op) or regex

            if op == "regex":
                value = re.compile(regex, flags)
            else:
                # escape unsafe characters which could lead to a re.error
                value = re.escape(value)
                value = re.compile(regex % value, flags)
        return super().prepare_query_value(op, value)


class DateTimeField(BaseField):
    """Datetime field.
    Uses the python-dateutil library to parse the dates.
    """

    def validate(self, value):
        new_value = self.to_mongo(value)
        if not isinstance(new_value, (datetime.datetime, datetime.date)):
            self.error(f'cannot parse date "{value}"')

    def to_mongo(self, value):
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime(value.year, value.month, value.day)
        if callable(value):
            return value()

        return self._parse_datetime(value) if isinstance(value, str) else None

    @staticmethod
    def _parse_datetime(value):
        # Attempt to parse a datetime from a string
        value = value.strip()
        if not value:
            return None
        try:
            return dateutil.parser.parse(value)
        except (TypeError, ValueError, OverflowError):
            return None

    def prepare_query_value(self, op, value):
        return super().prepare_query_value(op, self.to_mongo(value))


class BooleanField(BaseField):
    """Boolean field type."""

    def to_python(self, value):
        with contextlib.suppress(ValueError, TypeError):
            value = bool(value)
        return value

    def validate(self, value):
        if not isinstance(value, bool):
            self.error("BooleanField only accepts boolean values")


class FloatField(BaseField):
    """Floating point number field."""

    def __init__(self, min_value=None, max_value=None, **kwargs):
        """
        :param min_value: (optional) A min value that
                will be applied during validation
        :param max_value: (optional) A max value that
        will be applied during validation
        :param kwargs: Keyword arguments passed into
        the parent :class:`~mongodb.BaseField`
        """
        self.min_value, self.max_value = min_value, max_value
        super().__init__(**kwargs)

    def to_python(self, value):
        with contextlib.suppress(ValueError):
            value = float(value)
        return value

    def validate(self, value):
        if isinstance(value, int):
            try:
                value = float(value)
            except OverflowError:
                self.error("The value is too large to be converted to float")

        if not isinstance(value, float):
            self.error("FloatField only accepts float and integer values")

        if self.min_value is not None and value < self.min_value:
            self.error("Float value is too small")

        if self.max_value is not None and value > self.max_value:
            self.error("Float value is too large")

    def prepare_query_value(self, op, value):
        if value is None:
            return value

        return super().prepare_query_value(op, float(value))


class ListField(ComplexBaseField):
    """A list field that wraps a standard field, allowing multiple instances
    of the field to be used as a list in the database.

    If using with ReferenceFields see: :ref:`many-to-many-with-listfields`

    """

    def __init__(self, field=None, max_length=None, **kwargs):
        self.max_length = max_length
        kwargs.setdefault("default", lambda: [])
        super().__init__(field=field, **kwargs)

    def __get__(self, instance, owner):
        return self if instance is None else super().__get__(instance, owner)

    def validate(self, value):
        """Make sure that a list of valid fields is being used."""
        if not isinstance(value, (list, tuple, BaseQuerySet)):
            self.error("Only lists and tuples may be used in a list field")

        # Validate that max_length is not exceeded.
        # NOTE It's still possible to bypass this enforcement by using $push.
        # However, if the document is reloaded after $push and then re-saved,
        # the validation error will be raised.
        if self.max_length is not None and len(value) > self.max_length:
            self.error("List is too long")

        super().validate(value)

    def prepare_query_value(self, op, value):
        # Validate that the `set` operator doesn't
        # contain more items than `max_length`.
        if op == "set" and self.max_length is not None and \
                len(value) > self.max_length:
            self.error("List is too long")

        if self.field:

            # If the value is iterable and it's not a string nor a
            # BaseDocument, call prepare_query_value for each of its items.
            if (
                op in ("set", "unset", None)
                and hasattr(value, "__iter__")
                and not isinstance(value, str)
                and not isinstance(value, BaseDocument)
            ):
                return [self.field.prepare_query_value(op, v) for v in value]

            return self.field.prepare_query_value(op, value)

        return super().prepare_query_value(op, value)


def key_not_string(d):
    """Helper function to recursively determine if any key in a
    dictionary is not a string.
    """
    for k, v in d.items():
        if not isinstance(k, str) or \
                (isinstance(v, dict) and key_not_string(v)):
            return True


class DictField(ComplexBaseField):
    """A dictionary field that wraps a standard Python dictionary. This is
    similar to an embedded document, but the structure is not defined.
    """

    def __init__(self, field=None, *args, **kwargs):
        kwargs.setdefault("default", lambda: {})
        super().__init__(*args, field=field, **kwargs)

    def validate(self, value):
        """Make sure that a list of valid fields is being used."""
        if not isinstance(value, dict):
            self.error("Only dictionaries may be used in a DictField")

        if key_not_string(value):
            self.error(
                """Invalid dictionary key -
                documents must have only string keys""")

        super().validate(value)

    def lookup_member(self, member_name):
        return DictField(db_field=member_name)

    def prepare_query_value(self, op, value):
        match_operators = [*STRING_OPERATORS]

        if op in match_operators and isinstance(value, str):
            return CharField().prepare_query_value(op, value)

        if hasattr(
            self.field, "field"
        ):  # Used for instance when using DictField(ListField(IntField()))
            if op in ("set", "unset") and isinstance(value, dict):
                return {
                    k: self.field.prepare_query_value(op, v)
                    for k, v in value.items()
                }
            return self.field.prepare_query_value(op, value)

        return super().prepare_query_value(op, value)
