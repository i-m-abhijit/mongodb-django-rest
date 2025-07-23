from collections import defaultdict

from mongodb.base.document import BaseDocument
from mongodb.errors import InvalidQueryError

UPDATE_OPERATORS = {
    "set",
    "unset",
    "inc",
    "dec",
    "mul",
    "pop",
    "push",
    "push_all",
    "pull",
    "pull_all",
    "add_to_set",
    "set_on_insert",
    "min",
    "max",
    "rename",
}
COMPARISON_OPERATORS = (
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "nin",
    "mod",
    "all",
    "size",
    "exists",
    "not",
    "elemMatch",
    "type",
)
STRING_OPERATORS = (
    "contains",
    "icontains",
    "startswith",
    "istartswith",
    "endswith",
    "iendswith",
    "exact",
    "iexact",
    "regex",
    "iregex",
    "wholeword",
    "iwholeword",
)
CUSTOM_OPERATORS = ("match",)
MATCH_OPERATORS = (
    COMPARISON_OPERATORS + STRING_OPERATORS + CUSTOM_OPERATORS
)


def query(_doc_cls=None, **kwargs):
    """Transform a query from Django-style format to Mongo format."""
    mongo_query = {}
    merge_query = defaultdict(list)
    for key, value in sorted(kwargs.items()):
        if key == "__raw__":
            mongo_query.update(value)
            continue

        parts = key.rsplit("__")
        indices = [(i, p) for i, p in enumerate(parts) if p.isdigit()]
        parts = [part for part in parts if not part.isdigit()]
        # Check for an operator and transform to mongo-style if there is
        op = None
        if len(parts) > 1 and parts[-1] in MATCH_OPERATORS:
            op = parts.pop()

        # Allow to escape operator-like field name by __
        if len(parts) > 1 and parts[-1] == "":
            parts.pop()

        negate = False
        if len(parts) > 1 and parts[-1] == "not":
            parts.pop()
            negate = True

        nested_fields = _get_nested_fields(parts)

        if _doc_cls:
            # Switch field names to proper names [set in Field(name='abc')]
            try:
                fields = _doc_cls._lookup_field(parts)
            except Exception as e:
                raise InvalidQueryError(e) from e
            parts = []
            cleaned_fields = _get_cleaned_fields(fields, parts)

            # Convert value to proper value
            field = cleaned_fields[-1]

            singular_ops = [None, "ne", "gt", "gte", "lt", "lte", "not"]
            singular_ops += STRING_OPERATORS
            if op in singular_ops:
                value = field.prepare_query_value(op, value)
            elif op in ("in", "nin", "all") and not isinstance(value, dict):
                # Raise an error if the in/nin/all param is not iterable.
                value = _prepare_query_for_iterable(field, op, value)

        if op:
            if op in ("match", "elemMatch"):
                from mongodb.fields import ListField
                if isinstance(value, dict) and isinstance(field, ListField):
                    value = query(field.field.document_type, **value)
                else:
                    value = field.prepare_query_value(op, value)
                value = {"$elemMatch": value}
            elif op not in STRING_OPERATORS:
                value = {f"${op}": value}

        if negate:
            value = {"$not": value}

        for i, part in indices:
            parts.insert(i, part)
        parts += nested_fields
        key = ".".join(parts)

        if key not in mongo_query:
            mongo_query[key] = value
        elif isinstance(mongo_query[key], dict) and isinstance(value, dict):
            mongo_query[key].update(value)
        else:
            # Store for manually merging later
            merge_query[key].append(value)

    # The queryset has been filter in such a way we must manually merge
    for k, v in merge_query.items():
        merge_query[k].append(mongo_query[k])
        del mongo_query[k]
        if isinstance(v, list):
            value = [{k: val} for val in v]
            if "$and" in mongo_query.keys():
                mongo_query["$and"].extend(value)
            else:
                mongo_query["$and"] = value

    return mongo_query


def update(_doc_cls=None, **update):
    """Transform an update spec from Django-style format to Mongo format."""
    mongo_update = {}

    for key, value in update.items():
        if key == "__raw__":
            mongo_update.update(value)
            continue

        parts = key.split("__")

        # if there is no operator, default to 'set'
        if len(parts) < 3 and parts[0] not in UPDATE_OPERATORS:
            parts.insert(0, "set")

        # Check for an operator and transform to mongo-style if there is
        op = None
        if parts[0] in UPDATE_OPERATORS:
            op = parts.pop(0)
            # Convert Pythonic names to Mongo equivalents
            operator_map = {
                "push_all": "pushAll",
                "pull_all": "pullAll",
                "dec": "inc",
                "add_to_set": "addToSet",
                "set_on_insert": "setOnInsert",
            }
            if op == "dec":
                # Support decrement by flipping a positive
                # value's sign and using 'inc'
                value = -value
            # If the operator doesn't found from operator map,
            # the op value will stay unchanged
            op = operator_map.get(op, op)

        match = None
        if parts[-1] in COMPARISON_OPERATORS:
            match = parts.pop()

        # Allow to escape operator-like field name by __
        if len(parts) > 1 and parts[-1] == "":
            parts.pop()

        if _doc_cls:
            # Switch field names to proper names [set in Field(name='foo')]
            try:
                fields = _doc_cls._lookup_field(parts)
            except Exception as e:
                raise InvalidQueryError(e) from e
            parts = []

            cleaned_fields = []
            appended_sub_field = False
            for field in fields:
                append_field = True
                if isinstance(field, str):
                    # Convert the S operator to $
                    if field == "S":
                        field = "$"
                    parts.append(field)
                    append_field = False
                else:
                    parts.append(field.db_column or field.db_field)
                if append_field:
                    appended_sub_field = False
                    cleaned_fields.append(field)
                    if hasattr(field, "field"):
                        cleaned_fields.append(field.field)
                        appended_sub_field = True

            # Convert value to proper value
            field = cleaned_fields[-2] if appended_sub_field \
                else cleaned_fields[-1]

            if op == "pull":
                if field.required or value is not None:
                    value = _prepare_query_for_iterable(field, op, value) \
                        if match in ("in", "nin") and \
                        not isinstance(value, dict) \
                        else field.prepare_query_value(op, value)
            elif op == "push" and isinstance(value, (list, tuple, set)):
                value = [field.prepare_query_value(op, v) for v in value]
            elif op in (None, "set", "push"):
                if field.required or value is not None:
                    value = field.prepare_query_value(op, value)
            elif op in ("pushAll", "pullAll"):
                value = [field.prepare_query_value(op, v) for v in value]
            elif op in ("addToSet", "setOnInsert"):
                if isinstance(value, (list, tuple, set)):
                    value = [field.prepare_query_value(op, v) for v in value]
                elif field.required or value is not None:
                    value = field.prepare_query_value(op, value)
            elif op == "unset":
                value = 1
            elif op == "inc":
                value = field.prepare_query_value(op, value)

        if match:
            value = {f"${match}": value}

        key = ".".join(parts)

        if "pull" in op and "." in key:
            # Dot operators don't work on pull operations
            # unless they point to a list field
            # Otherwise it uses nested dict syntax
            if op == "pullAll":
                raise InvalidQueryError(
                    "pullAll operations only support a single field depth"
                )

            # Look for the last list field and use dot notation until there
            field_classes = [c.__class__ for c in cleaned_fields]
            field_classes.reverse()
            from mongodb.fields import ListField
            if ListField in field_classes:
                # Join all fields via dot notation to the last ListField
                # Then process as normal
                _check_field = ListField

                last_list_field = len(cleaned_fields) -\
                    field_classes.index(_check_field)
                key = ".".join(parts[:last_list_field])
                parts = parts[last_list_field:]
                parts.insert(0, key)

            parts.reverse()
            for key in parts:
                value = {key: value}
        elif op == "addToSet" and isinstance(value, list):
            value = {key: {"$each": value}}
        elif op in ("push", "pushAll"):
            if parts[-1].isdigit():
                key = ".".join(parts[:-1])
                position = int(parts[-1])
                # $position expects an iterable. If pushing a single value,
                # wrap it in a list.
                if not isinstance(value, (set, tuple, list)):
                    value = [value]
                value = {key: {"$each": value, "$position": position}}
            elif op == "pushAll":
                op = "push"  # convert to non-deprecated keyword
                if not isinstance(value, (set, tuple, list)):
                    value = [value]
                value = {key: {"$each": value}}
            else:
                value = {key: value}
        else:
            value = {key: value}
        key = f"${op}"
        if key not in mongo_update:
            mongo_update[key] = value
        elif isinstance(mongo_update[key], dict):
            mongo_update[key].update(value)

    return mongo_update


def _get_nested_fields(parts):
    nested_fields = []
    if len(parts) > 1:
        nested_fields = parts[1:].copy()
        del parts[1:]
    return nested_fields


def _get_cleaned_fields(fields, parts):
    cleaned_fields = []
    for field in fields:
        append_field = True
        if isinstance(field, str):
            parts.append(field)
            append_field = False
        else:
            parts.append(field.db_column)

        if append_field:
            cleaned_fields.append(field)
    return cleaned_fields


def _prepare_query_for_iterable(field, op, value):
    # We need a special check for BaseDocument,
    # because - although it's iterable - using
    # it as such in the context of this method
    # is most definitely a mistake.

    if isinstance(value, BaseDocument):
        raise TypeError(
            """When using the `in`, `nin`, or `all`-operators
            you can't use a `Document`, you must wrap your
            object in a list (object -> [object])."""
        )

    if not hasattr(value, "__iter__"):
        raise TypeError(
            """The `in`, `nin`, or `all`-operators must be
            applied to an iterable (e.g. a list)."""
        )

    return [field.prepare_query_value(op, v) for v in value]
