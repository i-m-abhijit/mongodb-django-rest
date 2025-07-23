import re

import pymongo

from mongodb.base.document import BaseDocument
from mongodb.base.metaclasses import TopLevelDocumentMetaclass
from mongodb.connection import DEFAULT_CONNECTION_NAME, get_db
from mongodb.context_managers import set_write_concern
from mongodb.errors import (InvalidDocumentError, InvalidQueryError,
                            NotUniqueError, OperationError, SaveConditionError)
from mongodb.queryset import QuerySet, transform


class InvalidCollectionError(Exception):
    pass


class Document(BaseDocument, metaclass=TopLevelDocumentMetaclass):
    """The base class used for defining the structure and properties of
    collections of documents stored in MongoDB. Inherit from this class, and
    add fields as class attributes to define a document's structure.

    By default, the MongoDB collection used to store documents created using a
    :class:`~mongodb.Document` subclass will be the name of the subclass
    converted to snake_case. A different collection may be specified by
    providing :attr:`collection` to the :attr:`meta` dictionary in the class
    definition.

    By default, any extra attribute existing in stored data but not declared
    in your model will raise a :class:`~mongodb.FieldDoesNotExist` error.
    This can be disabled by setting :attr:`strict` to ``False``
    in the :attr:`meta` dictionary.
    """
    my_metaclass = TopLevelDocumentMetaclass
    __slots__ = ("__objects",)

    @property
    def pk(self):
        """Get the primary key."""
        if "id_field" not in self._meta:
            return None
        return getattr(self, self._meta["id_field"])

    @pk.setter
    def pk(self, value):
        """Set the primary key."""
        return setattr(self, self._meta["id_field"], value)

    def __hash__(self):
        """Return the hash based on the PK of this document. If it's new
        and doesn't have a PK yet, return the default object hash instead.
        """
        if self.pk is None:
            return super(BaseDocument, self).__hash__()

        return hash(self.pk)

    @classmethod
    def _get_db(cls):
        """Some Model using other db_alias"""
        return get_db(cls._meta.get("db_alias", DEFAULT_CONNECTION_NAME))

    @classmethod
    def _disconnect(cls):
        """Detach the Document class from the (cached) database collection"""
        cls._collection = None

    @classmethod
    def _get_collection(cls):
        """Return the PyMongo collection corresponding to this document.
        Initializes a :class:`~pymongo.collection.Collection` corresponding
           to this document.
        """
        if not hasattr(cls, "_collection") or cls._collection is None:
            db = cls._get_db()
            collection_name = cls._get_collection_name()
            cls._collection = db[collection_name]
        return cls._collection

    def to_mongo(self, *args, **kwargs):
        data = super().to_mongo(*args, **kwargs)

        # If '_id' is None, try and set it from self._data. If that
        # doesn't exist either, remove '_id' from the SON completely.
        if data["_id"] is None:
            if self._data.get("id") is None:
                del data["_id"]
            else:
                data["_id"] = self._data["id"]

        return data

    def modify(self, query=None, **update):
        """Perform an atomic update of the document in the database and reload
        the document object using updated version.

        Returns True if the document has been updated or False if the document
        in the database doesn't match the query.

        .. note:: All unsaved changes that have been made to the document are
            rejected if the method returns True.

        :param query: the update will be performed only if the document in the
            database matches the query
        :param update: Django-style update keyword arguments
        """
        if query is None:
            query = {}

        if self.pk is None:
            raise InvalidDocumentError(
                "The document does not have a primary key.")

        id_field = self._meta["id_field"]
        query = query.copy() if isinstance(query, dict) \
            else query.to_query(self)

        if id_field not in query:
            query[id_field] = self.pk
        elif query[id_field] != self.pk:
            raise InvalidQueryError(
                """Invalid document modify query:
                it must modify only this document."""
            )

        # Need to add shard key to query, or you get an error
        query.update(self._object_key)

        updated = self._qs(**query).modify(new=True, **update)
        if updated is None:
            return False

        for field in self._fields_ordered:
            setattr(self, field, self._reload(field, updated[field]))

        self._changed_fields = updated._changed_fields
        self._created = False

        return True

    def save(
        self,
        force_insert=False,
        validate=True,
        clean=True,
        write_concern=None,
        save_condition=None,
        **kwargs,
    ):
        """Save the :class:`~mongodb.Document` to the database. If the
        document already exists, it will be updated, otherwise it will be
        created. Returns the saved object instance.

        :param force_insert: only try to create a new document, don't allow
            updates of existing documents.
        :param validate: validates the document; set to `False` to skip.
        :param clean: call the document clean method, requires `validate` to be
            True.
        :param write_concern: Extra keyword arguments are passed down to
            :meth:`~pymongo.collection.Collection.save` OR
            :meth:`~pymongo.collection.Collection.insert`
            which will be used as options for the resultant
            ``getLastError`` command.  For example,
            ``save(..., write_concern={w: 2, fsync: True}, ...)`` will
            wait until at least two servers have recorded the write and
            will force an fsync on the primary server.
        :param save_condition: only perform save if matching record in db
            satisfies condition(s) (e.g. version number).
            Raises :class:`OperationError` if the conditions are not satisfied
        """

        if self._meta.get("abstract"):
            raise InvalidDocumentError("Cannot save an abstract document.")

        if write_concern is None:
            write_concern = {}

        doc_id = self.to_mongo(fields=[self._meta["id_field"]])
        created = "_id" not in doc_id or self._created or force_insert
        doc = self.to_mongo()
        # TODO: Validation check should be performed only on changed fields
        # Suppose in our Document class we update field type of a document
        # field from CharField to IntegerField. In that case save() will throw
        # ValidationError while updating existing Document objects as existing
        # Document objects have CharField as field type. We can fix this issue
        # by validating only changed fields.
        if validate:
            if created:
                self.validate(
                    clean=clean, insertion=True, data=doc)
            else:
                self.validate(clean=clean)

        try:
            # Save a new document or update an existing one
            if created:
                object_id = self._save_create(doc, force_insert, write_concern)
            else:
                object_id, created = self._save_update(
                    doc, save_condition, write_concern
                )

        except pymongo.errors.DuplicateKeyError as err:
            message = "Tried to save duplicate unique keys (%s)"
            raise NotUniqueError(message % err) from err
        except pymongo.errors.OperationFailure as err:
            message = "Could not save document (%s)"
            if re.match("^E1100[01] duplicate key", str(err)):
                # E11000 - duplicate key error index
                # E11001 - duplicate key on update
                message = "Tried to save duplicate unique keys (%s)"
                raise NotUniqueError(message % err) from err
            raise OperationError(message % err) from err

        # Make sure we store the PK on this document now that it's saved
        id_field = self._meta["id_field"]
        if created:
            self[id_field] = self._fields[id_field].to_python(object_id)

        self._clear_changed_fields()
        self._created = False

        return self

    def _remove_null_values(self, d):
        """Recursively removing keys with None values from a dictionary."""
        if isinstance(d, dict):
            return {k: self._remove_null_values(v) if isinstance(v, (dict, list)) else v for k, v in d.items() if v is not None}
        elif isinstance(d, list):
            return [self._remove_null_values(item) if isinstance(item, (dict, list)) else item for item in d if item is not None]
        else:
            return d

    def _save_create(self, doc, force_insert, write_concern):
        """Save a new document.

        Helper method, should only be used inside save().
        """
        # Removing keys with None values
        doc = self._remove_null_values(d=doc)
        collection = self._get_collection()
        with set_write_concern(collection, write_concern) as wc_collection:
            if force_insert:
                return wc_collection.insert_one(doc).inserted_id
            # insert_one will provoke UniqueError alongside save does not
            # therefore, it need to catch and call replace_one.
            if "_id" in doc:
                select_dict = {"_id": doc["_id"]}
                if wc_collection.find_one_and_replace(
                    select_dict, doc
                ):
                    return doc["_id"]

            object_id = wc_collection.insert_one(doc).inserted_id

        return object_id

    def explain(self):
        """Return an explain plan record for the
        :class:`~mongodb.document.Document` cursor.
        """
        return self._cursor.explain()

    def _get_update_doc(self):
        """Return a dict containing all the $set and $unset operations
        that should be sent to MongoDB based on the changes made to this
        Document.
        """
        updates, removals = self._delta()

        update_doc = {}
        if updates:
            update_doc["$set"] = updates
        if removals:
            update_doc["$unset"] = removals

        return update_doc

    def _save_update(self, doc, save_condition, write_concern):
        """Update an existing document.

        Helper method, should only be used inside save().
        """
        collection = self._get_collection()
        object_id = doc["_id"]
        created = False

        select_dict = {}
        if save_condition is not None:
            select_dict = transform.query(self.__class__, **save_condition)

        select_dict["_id"] = object_id

        if update_doc := self._get_update_doc():
            upsert = save_condition is None
            with set_write_concern(collection, write_concern) as wc_collection:
                last_error = wc_collection.update_one(
                    select_dict, update_doc, upsert=upsert
                ).raw_result
            if not upsert and last_error["n"] == 0:
                raise SaveConditionError(
                    "Race condition preventing document update detected"
                )
            if last_error is not None:
                updated_existing = last_error.get("updatedExisting")
                if updated_existing is False:
                    created = True

        return object_id, created

    @property
    def _qs(self):
        """Return the default queryset corresponding to this document."""
        if not hasattr(self, "__objects"):
            queryset_class = self._meta.get("queryset_class", QuerySet)
            self.__objects = queryset_class(
                self.__class__, self._get_collection())
        return self.__objects

    @property
    def _object_key(self):
        """Return a query dict that can be used to fetch this document.

        Note that the dict returned by this method uses mongodb field
        names instead of PyMongo field names (e.g. "pk" instead of "_id").
        """
        return {"pk": self.pk}

    def update(self, **kwargs):
        """Performs an update on the :class:`~mongodb.Document`
        A convenience wrapper to :meth:`~mongodb.QuerySet.update`.

        Raises :class:`OperationError` if called on an object that has not yet
        been saved.
        """
        if self.pk is None:
            if not kwargs.get("upsert", False):
                raise OperationError(
                    "attempt to update a document not yet saved")

            query = self.to_mongo()
            if "_cls" in query:
                del query["_cls"]
            return self._qs.filter(**query).update_one(**kwargs)
        # Need to add shard key to query, or you get an error
        return self._qs.filter(**self._object_key).update_one(**kwargs)

    def delete(self):
        """Delete the :class:`~mongodb.Document` from the database. This
        will only take effect if the document has been previously saved.
        """
        try:
            self._qs.filter(**self._object_key).delete()
        except pymongo.errors.OperationFailure as err:
            message = f"Could not delete document ({err.args})"
            raise OperationError(message) from err
