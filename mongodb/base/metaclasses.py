import itertools
import warnings

from django.db.models import Field

from mongodb.base.common import _document_registry
from mongodb.base.fields import BaseField
from mongodb.errors import (DoesNotExist, InvalidDocumentError,
                            MultipleObjectsReturned)
from mongodb.fields import ObjectIdField
from mongodb.queryset.manager import QuerySetManager


class DocumentMetaclass(type):
    """Metaclass for all documents."""

    def __new__(cls, name, bases, attrs):
        flattened_bases = cls._get_bases(bases)

        # If a base class just call super
        metaclass = attrs.get("my_metaclass")
        if metaclass and issubclass(metaclass, DocumentMetaclass):
            return super().__new__(cls, name, bases, attrs)

        attrs["_is_document"] = attrs.get("_is_document", False)
        attrs["_cached_reference_fields"] = []

        # EmbeddedDocuments could have meta data for inheritance
        if "meta" in attrs:
            attrs["_meta"] = attrs.pop("meta")

        # EmbeddedDocuments should inherit meta data
        if "_meta" not in attrs:
            meta = MetaDict()
            for base in flattened_bases[::-1]:
                # Add any mixin metadata from plain objects
                if hasattr(base, "meta"):
                    meta.merge(base.meta)
                elif hasattr(base, "_meta"):
                    meta.merge(base._meta)
            attrs["_meta"] = meta
            attrs["_meta"][
                "abstract"
            ] = False  # 789: EmbeddedDocument shouldn't inherit abstract

        # Handle document Fields

        # Merge all fields from subclasses
        doc_fields = {}
        for base in flattened_bases[::-1]:
            if hasattr(base, "_fields"):
                doc_fields.update(base._fields)

            # Standard object mixin - merge in any Fields
            if not hasattr(base, "_meta"):
                base_fields = {}
                for attr_name, attr_value in base.__dict__.items():
                    if not issubclass(type(attr_value), Field) and \
                            not isinstance(attr_value, BaseField):
                        continue
                    attr_value.name = attr_name
                    if not attr_value.db_column:
                        attr_value.db_column = attr_name
                    base_fields[attr_name] = attr_value

                doc_fields.update(base_fields)

        # Discover any document fields
        field_names = {}
        for attr_name, attr_value in attrs.items():
            if not issubclass(type(attr_value), Field) and \
                    not isinstance(attr_value, BaseField):
                continue
            attr_value.name = attr_name
            if not attr_value.db_column:
                attr_value.db_column = attr_name
            doc_fields[attr_name] = attr_value

            # Count names to ensure no db_column redefinitions
            field_names[attr_value.db_column] = (
                field_names.get(attr_value.db_column, 0) + 1
            )

        if duplicate_db_fields := [k for k, v in field_names.items() if v > 1]:
            raise InvalidDocumentError(
                f'''Multiple db_fields defined for:
                {", ".join(duplicate_db_fields)} '''
            )

        # Set _fields and db_column maps
        attrs["_fields"] = doc_fields
        attrs["_db_field_map"] = {
            k: getattr(v, "db_column", k) for k, v in doc_fields.items()
        }
        attrs["_reverse_db_field_map"] = {
            v: k for k, v in attrs["_db_field_map"].items()
        }

        attrs["_fields_ordered"] = tuple(
            i[1]
            for i in sorted((v.creation_counter, v.name)
                            for v in doc_fields.values())
        )

        #
        # Set document hierarchy
        #
        superclasses = ()
        class_name = [name]
        for base in flattened_bases:
            if not getattr(base, "_is_base_cls", True) and not getattr(
                base, "_meta", {}
            ).get("abstract", True):
                # Collate hierarchy for _cls and _subclasses
                class_name.append(base.__name__)

        # Get superclasses from last base superclass
        document_bases = [
            b for b in flattened_bases if hasattr(b, "_class_name")]
        if document_bases:
            superclasses = document_bases[0]._superclasses
            superclasses += (document_bases[0]._class_name,)

        _cls = ".".join(reversed(class_name))
        attrs["_class_name"] = _cls
        attrs["_superclasses"] = superclasses
        attrs["_subclasses"] = (_cls,)

        # Create the new_class
        new_class = super().__new__(cls, name, bases, attrs)

        # Set _subclasses
        for base in document_bases:
            if _cls not in base._subclasses:
                base._subclasses += (_cls,)
        from mongodb.document import Document
        if issubclass(new_class, Document):
            new_class._collection = None

        # Add class to the _document_registry
        _document_registry[new_class._class_name] = new_class

        return new_class

    @classmethod
    def _get_bases(cls, bases):
        if isinstance(bases, BasesTuple):
            return bases
        seen = []
        bases = cls.__get_bases(bases)
        unique_bases = (b for b in bases if not (b in seen or seen.append(b)))
        return BasesTuple(unique_bases)

    @classmethod
    def __get_bases(cls, bases):
        for base in bases:
            if base is object:
                continue

            yield base
            yield from cls.__get_bases(base.__bases__)


class TopLevelDocumentMetaclass(DocumentMetaclass):
    """Metaclass for top-level documents (i.e. documents that have their own
    collection in the database.
    """

    def __new__(cls, name, bases, attrs):
        flattened_bases = cls._get_bases(bases)
        # Set default _meta data if base class, otherwise get user defined meta
        if attrs.get("my_metaclass") == TopLevelDocumentMetaclass:
            # defaults
            attrs["_meta"] = {
                "abstract": True,
                "ordering": [],  # default ordering applied at runtime
                "id_field": None,
                "delete_rules": None,
                "parents": True
            }
            attrs["_is_base_cls"] = True
            attrs["_meta"].update(attrs.get("meta", {}))
        else:
            attrs["_meta"] = attrs.get("meta", {})
            # Explicitly set abstract to false unless set
            attrs["_meta"]["abstract"] = attrs["_meta"].get("abstract", False)
            attrs["_is_base_cls"] = False

        # Set flag marking as document class - as opposed to an object mixin
        attrs["_is_document"] = True

        # Ensure queryset_class is inherited
        if "objects" in attrs:
            manager = attrs["objects"]
            if hasattr(manager, "queryset_class"):
                attrs["_meta"]["queryset_class"] = manager.queryset_class

        # Clean up top level meta
        if "meta" in attrs:
            del attrs["meta"]

        # Find the parent document class
        parent_doc_cls = [
            b for b in flattened_bases
            if b.__class__ == TopLevelDocumentMetaclass
        ]
        parent_doc_cls = parent_doc_cls[0] if parent_doc_cls else None

        # Prevent classes setting collection different to their parents
        # If parent wasn't an abstract class
        if (
            parent_doc_cls
            and "collection" in attrs.get("_meta", {})
            and not parent_doc_cls._meta.get("abstract", True)
        ):
            msg = f"Trying to set a collection on a subclass ({name})"
            warnings.warn(msg, SyntaxWarning)
            del attrs["_meta"]["collection"]

        # Ensure abstract documents have abstract bases
        if attrs.get("_is_base_cls") or attrs["_meta"].get("abstract"):
            if parent_doc_cls and \
                    not parent_doc_cls._meta.get("abstract", False):
                msg = "Abstract document cannot have non-abstract base"
                raise ValueError(msg)
            return super().__new__(cls, name, bases, attrs)

        # Merge base class metas.
        # Uses a special MetaDict that handles various merging rules
        meta = MetaDict()
        for base in flattened_bases[::-1]:
            # Add any mixin metadata from plain objects
            if hasattr(base, "meta"):
                meta.merge(base.meta)
            elif hasattr(base, "_meta"):
                meta.merge(base._meta)

            # Set collection in the meta if its callable
            if getattr(base, "_is_document", False) and \
                    not base._meta.get("abstract"):
                collection = meta.get("collection", None)
                if callable(collection):
                    meta["collection"] = collection(base)

        meta.merge(attrs.get("_meta", {}))  # Top level meta

        # Set default collection name
        if "collection" not in meta:
            meta["collection"] = (
                "".join(f"_{c}" if c.isupper() else c for c in name)
                .strip("_")
                .lower()
            )
        attrs["_meta"] = meta

        # Call super and get the new class
        new_class = super().__new__(cls, name, bases, attrs)

        meta = new_class._meta

        # If collection is a callable - call it and set the value
        collection = meta.get("collection")
        if callable(collection):
            new_class._meta["collection"] = collection(new_class)

        # Provide a default queryset unless exists or one has been set
        if "objects" not in dir(new_class):
            new_class.objects = QuerySetManager()
        # Validate the fields and set primary key if needed
        for field_name, field in new_class._fields.items():
            if field.primary_key:
                # Ensure only one primary key is set
                current_pk = new_class._meta.get("id_field")
                if current_pk and current_pk != field_name:
                    raise ValueError("Cannot override primary key field")

                # Set primary key
                if not current_pk:
                    new_class._meta["id_field"] = field_name
                    new_class.id = field

        # If the document doesn't explicitly define a primary key field, create
        # one. Make it an ObjectIdField and give it a non-clashing name ("id"
        # by default, but can be different if that one's taken).
        if not new_class._meta.get("id_field"):
            id_name, id_db_name = cls.get_auto_id_names(new_class)
            new_class._meta["id_field"] = id_name
            new_class._fields[id_name] = ObjectIdField(db_column=id_db_name)
            new_class._fields[id_name].name = id_name
            new_class.id = new_class._fields[id_name]
            new_class._db_field_map[id_name] = id_db_name
            new_class._reverse_db_field_map[id_db_name] = id_name

            # Prepend the ID field to _fields_ordered (so that it's *always*
            # the first field).
            new_class._fields_ordered = (id_name,) + new_class._fields_ordered

        # Merge in exceptions with parent hierarchy.
        exceptions_to_merge = (DoesNotExist, MultipleObjectsReturned)
        module = attrs.get("__module__")
        for exc in exceptions_to_merge:
            name = exc.__name__
            parents = tuple(
                getattr(base, name) for base in flattened_bases
                if hasattr(base, name)
            ) or (exc,)

            # Create a new exception and set it as an attribute on the new
            # class.
            exception = type(name, parents, {"__module__": module})
            setattr(new_class, name, exception)

        return new_class

    @classmethod
    def get_auto_id_names(cls, new_class):
        """Find a name for the automatic ID field for the given new class.

        Return a two-element tuple where the first item is the field name (i.e.
        the attribute name on the object) and the second element is the DB
        field name (i.e. the name of the key stored in MongoDB).

        Defaults to ('id', '_id'), or generates a non-clashing name in the form
        of ('auto_id_X', '_auto_id_X') if the default name is already taken.
        """
        id_name, id_db_name = ("id", "_id")
        existing_fields = set(new_class._fields)
        existing_db_fields = {v.db_column for v in new_class._fields.values()}
        if id_name not in existing_fields and \
                id_db_name not in existing_db_fields:
            return id_name, id_db_name

        id_basename, id_db_basename, i = ("auto_id", "_auto_id", 0)
        for i in itertools.count():
            id_name = f"{id_basename}_{i}"
            id_db_name = f"{id_db_basename}_{i}"
            if id_name not in existing_fields and \
                    id_db_name not in existing_db_fields:
                return id_name, id_db_name


class MetaDict(dict):
    """Custom dictionary for meta classes.
    Handles the merging of set indexes
    """

    _merge_options = ("indexes",)

    def merge(self, new_options):
        for k, v in new_options.items():
            self[k] = self.get(k, []) + v if k in self._merge_options else v


class BasesTuple(tuple):
    """Special class to handle introspection of bases tuple in __new__"""
    pass
