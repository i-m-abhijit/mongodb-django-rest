import contextlib
import weakref

from bson import DBRef

from mongodb.document import BaseDocument
from mongodb.errors import DoesNotExist


def mark_as_changed_wrapper(parent_method):
    """Decorator that ensures _mark_as_changed method gets called."""

    def wrapper(self, *args, **kwargs):
        # Can't use super() in the decorator.
        result = parent_method(self, *args, **kwargs)
        self._mark_as_changed()
        return result

    return wrapper


def mark_key_as_changed_wrapper(parent_method):
    """Decorator that ensures _mark_as_changed
    method gets called with the key argument"""

    def wrapper(self, key, *args, **kwargs):
        # Can't use super() in the decorator.
        result = parent_method(self, key, *args, **kwargs)
        self._mark_as_changed(key)
        return result

    return wrapper


class BaseDict(dict):
    """A special dict so we can watch any changes."""

    _dereferenced = False
    _instance = None
    _name = None

    def __init__(self, dict_items, instance, name):

        if isinstance(instance, BaseDocument):
            self._instance = weakref.proxy(instance)
        self._name = name
        super().__init__(dict_items)

    def get(self, key, default=None):
        # get does not use __getitem__ by
        # default so we must override it as well
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def __getitem__(self, key):
        value = super().__getitem__(key)

        if isinstance(value, dict) and not isinstance(value, BaseDict):
            value = BaseDict(value, None, f"{self._name}.{key}")
            super().__setitem__(key, value)
            value._instance = self._instance
        elif isinstance(value, list) and not isinstance(value, BaseList):
            value = BaseList(value, None, f"{self._name}.{key}")
            super().__setitem__(key, value)
            value._instance = self._instance
        return value

    def __getstate__(self):
        self.instance = None
        self._dereferenced = False
        return self

    def __setstate__(self, state):
        self = state
        return self

    __setitem__ = mark_key_as_changed_wrapper(dict.__setitem__)
    __delattr__ = mark_key_as_changed_wrapper(dict.__delattr__)
    __delitem__ = mark_key_as_changed_wrapper(dict.__delitem__)
    pop = mark_as_changed_wrapper(dict.pop)
    clear = mark_as_changed_wrapper(dict.clear)
    update = mark_as_changed_wrapper(dict.update)
    popitem = mark_as_changed_wrapper(dict.popitem)
    setdefault = mark_as_changed_wrapper(dict.setdefault)

    def _mark_as_changed(self, key=None):
        if hasattr(self._instance, "_mark_as_changed"):
            if key:
                self._instance._mark_as_changed(f"{self._name}.{key}")
            else:
                self._instance._mark_as_changed(self._name)


class BaseList(list):
    """A special list so we can watch any changes."""

    _dereferenced = False
    _instance = None
    _name = None

    def __init__(self, list_items, instance, name):

        if isinstance(instance, BaseDocument):
            self._instance = weakref.proxy(instance)
        self._name = name
        super().__init__(list_items)

    def __getitem__(self, key):
        # change index to positive value because
        # MongoDB does not support negative one
        if isinstance(key, int) and key < 0:
            key = len(self) + key
        value = super().__getitem__(key)

        if isinstance(key, slice):
            return value

        if isinstance(value, dict) and not isinstance(value, BaseDict):
            # Replace dict by BaseDict
            value = BaseDict(value, None, f"{self._name}.{key}")
            super().__setitem__(key, value)
            value._instance = self._instance
        elif isinstance(value, list) and not isinstance(value, BaseList):
            # Replace list by BaseList
            value = BaseList(value, None, f"{self._name}.{key}")
            super().__setitem__(key, value)
            value._instance = self._instance
        return value

    def __iter__(self):
        yield from super().__iter__()

    def __getstate__(self):
        self.instance = None
        self._dereferenced = False
        return self

    def __setstate__(self, state):
        self = state
        return self

    def __setitem__(self, key, value):
        changed_key = key
        if isinstance(key, slice):
            # In case of slice, we don't bother to identify
            # the exact elements being updated instead, we
            # simply marks the whole list as changed
            changed_key = None

        result = super().__setitem__(key, value)
        self._mark_as_changed(changed_key)
        return result

    append = mark_as_changed_wrapper(list.append)
    extend = mark_as_changed_wrapper(list.extend)
    insert = mark_as_changed_wrapper(list.insert)
    pop = mark_as_changed_wrapper(list.pop)
    remove = mark_as_changed_wrapper(list.remove)
    reverse = mark_as_changed_wrapper(list.reverse)
    sort = mark_as_changed_wrapper(list.sort)
    __delitem__ = mark_as_changed_wrapper(list.__delitem__)
    __iadd__ = mark_as_changed_wrapper(list.__iadd__)
    __imul__ = mark_as_changed_wrapper(list.__imul__)

    def _mark_as_changed(self, key=None):
        if hasattr(self._instance, "_mark_as_changed"):
            if key is not None:
                self._instance._mark_as_changed(
                    f"{self._name}.{key % len(self)}")
            else:
                self._instance._mark_as_changed(self._name)


class StrictDict:
    __slots__ = ()
    _special_fields = {"get", "pop", "iteritems", "items", "keys", "create"}
    _classes = {}

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, key):
        key = f"_reserved_{key}" if key in self._special_fields else key
        try:
            return getattr(self, key)
        except AttributeError as e:
            raise KeyError(key) from e

    def __setitem__(self, key, value):
        key = f"_reserved_{key}" if key in self._special_fields else key
        return setattr(self, key, value)

    def __contains__(self, key):
        return hasattr(self, key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, default=None):
        v = self.get(key, default)
        with contextlib.suppress(AttributeError):
            delattr(self, key)
        return v

    def iteritems(self):
        for key in self:
            yield key, self[key]

    def items(self):
        return [(k, self[k]) for k in iter(self)]

    def iterkeys(self):
        return iter(self)

    def keys(self):
        return list(iter(self))

    def __iter__(self):
        return (key for key in self.__slots__ if hasattr(self, key))

    def __len__(self):
        return len(list(self.items()))

    def __eq__(self, other):
        return list(self.items()) == list(other.items())

    def __ne__(self, other):
        return self != other

    @classmethod
    def create(cls, allowed_keys):
        allowed_keys_tuple = tuple(
            f"_reserved_{k}" if k in cls._special_fields else k
            for k in allowed_keys
        )
        allowed_keys = frozenset(allowed_keys_tuple)
        if allowed_keys not in cls._classes:

            class SpecificStrictDict(cls):
                __slots__ = allowed_keys_tuple

                def __repr__(self):
                    return "{%s}" % ", ".join(
                        f'"{k!s}": {v!r}' for k, v in self.items()
                    )

            cls._classes[allowed_keys] = SpecificStrictDict
        return cls._classes[allowed_keys]


class LazyReference(DBRef):
    __slots__ = ("_cached_doc", "passthrough", "document_type")

    def fetch(self, force=False):
        if not self._cached_doc or force:
            self._cached_doc = self.document_type.objects.get(pk=self.pk)
        if not self._cached_doc:
            raise DoesNotExist(
                f"Trying to dereference unknown document {self}")
        return self._cached_doc

    @property
    def pk(self):
        return self.id

    def __init__(self, document_type, pk, cached_doc=None, passthrough=False):
        self.document_type = document_type
        self._cached_doc = cached_doc
        self.passthrough = passthrough
        super().__init__(self.document_type._get_collection_name(), pk)

    def __getitem__(self, name):
        if not self.passthrough:
            raise KeyError()
        document = self.fetch()
        return document[name]

    def __getattr__(self, name):
        if not object.__getattribute__(self, "passthrough"):
            raise AttributeError()
        document = self.fetch()
        try:
            return document[name]
        except KeyError as e:
            raise AttributeError() from e

    def __repr__(self):
        return f"<LazyReference({self.document_type}, {self.pk!r})>"
