import contextlib
import copy
import itertools
import re
import warnings
from collections.abc import Mapping

import pymongo
import pymongo.errors
from bson import SON, json_util
from pymongo.collection import ReturnDocument
from pymongo.common import validate_read_preference
from pymongo.read_concern import ReadConcern

from mongodb.context_managers import set_read_write_concern, set_write_concern
from mongodb.errors import (BulkWriteError, InvalidQueryError, LookUpError,
                            NotUniqueError, OperationError)
from mongodb.pymongo_support import LEGACY_JSON_OPTIONS
from mongodb.queryset import transform
from mongodb.queryset.field_list import QueryFieldList
from mongodb.queryset.visitor import Q, QNode


class BaseQuerySet:
    """A set of results returned from a query. Wraps a MongoDB cursor,
    providing :class:`~mongodb.Document` objects as the results.
    """

    __dereference = False

    def __init__(self, document, collection):
        self._document = document
        self._collection_obj = collection
        self._mongo_query = None
        self._query_obj = Q()
        self._cls_query = {}
        self._where_clause = None
        self._loaded_fields = QueryFieldList()
        self._ordering = None
        self._timeout = True
        self._allow_disk_use = False
        self._read_preference = None
        self._read_concern = None
        self._iter = False
        self._scalar = []
        self._none = False
        self._as_pymongo = False
        self._search_text = None
        self._cursor_obj = None
        self._limit = None
        self._skip = None
        self._batch_size = None
        self._empty = False

    def __call__(self, q_obj=None, negate_query=False, **query):
        """Filter the selected documents by calling the
        :class:`QuerySet` with a query.

        :param q_obj: a :class:`Q` object to be used in
            the query; the :class:`QuerySet` is filtered
            multiple times with different :class:`Q`
            objects, only the last one will be used.
        :param query: Django-style query keyword arguments.
        """
        query = Q(**query)
        if q_obj:
            if not isinstance(q_obj, QNode):
                raise InvalidQueryError(
                    f"""Not a query object: {q_obj}.
                    Did you intend to use key=value?""")
            query &= q_obj

        queryset = self.clone()
        queryset._query_obj &= query
        queryset._mongo_query = {
            '$nor': [
                queryset._query_obj.to_query(queryset._document)]} if negate_query else None
        queryset._cursor_obj = None

        return queryset

    def __getstate__(self):
        """Need for pickling queryset"""

        obj_dict = self.__dict__.copy()

        # don't pickle collection, instead pickle collection params
        obj_dict.pop("_collection_obj")

        # don't pickle cursor
        obj_dict["_cursor_obj"] = None

        return obj_dict

    def __setstate__(self, obj_dict):
        """Need for pickling queryset"""

        obj_dict["_collection_obj"] = obj_dict["_document"]._get_collection()

        # update attributes
        self.__dict__.update(obj_dict)

    def __getitem__(self, key):
        """Return a document instance corresponding to a given index if
        the key is an integer. If the key is a slice, translate its
        bounds into a skip and a limit, and return a cloned queryset
        with that skip/limit applied.
        """
        queryset = self.clone()
        queryset._empty = False

        if isinstance(key, slice):
            queryset._cursor_obj = queryset._cursor[key]
            queryset._skip, queryset._limit = key.start, key.stop
            if key.start and key.stop:
                queryset._limit = key.stop - key.start
            if queryset._limit == 0:
                queryset._empty = True

            # Allow further QuerySet modifications to be performed
            return queryset

        # Handle an index
        elif isinstance(key, int):
            if queryset._scalar:
                return queryset._get_scalar(
                    queryset._document._from_son(
                        queryset._cursor[key],
                    )
                )

            if queryset._as_pymongo:
                return queryset._cursor[key]

            return queryset._document._from_son(
                queryset._cursor[key],
            )

        raise TypeError("Provide a slice or an integer index")

    def __iter__(self):
        raise NotImplementedError

    def _has_data(self):
        """Return True if cursor has any data."""
        queryset = self.order_by()
        return queryset.first() is not None

    def __bool__(self):
        """Avoid to open all records in an if stmt in Py3."""
        return self._has_data()

    # Core functions

    def all(self):
        """Returns a copy of the current QuerySet."""
        return self.__call__()

    def filter(self, *q_objs, **query):
        """An alias of :meth:`~mongodb.queryset.QuerySet.__call__`"""
        return self.__call__(*q_objs, negate_query=False, **query)

    def search_text(self, text, language=None):
        """
        Start a text search, using text indexes.

        :param language:  The language that determines the list of
            stop words the search and the rules for the stemmer and
            tokenizer.  not specified, the search uses the default
            language of the index.
        """
        queryset = self.clone()
        if queryset._search_text:
            raise OperationError(
                "It is not possible to use search_text two times.")

        query_kwargs = SON({"$search": text})
        if language:
            query_kwargs["$language"] = language

        queryset._query_obj &= Q(__raw__={"$text": query_kwargs})
        queryset._mongo_query = None
        queryset._cursor_obj = None
        queryset._search_text = text

        return queryset

    def get(self, *q_objs, **query):
        """Retrieve the the matching object raising
        `MultipleObjectsReturned` exception if multiple results
        and `DoesNotExist` if no results are found.
        """
        queryset = self.clone()
        queryset = queryset.order_by().limit(2)
        queryset = queryset.filter(*q_objs, **query)

        try:
            result = next(queryset)
            result._cursor = queryset._cursor
        except StopIteration as e:
            raise queryset._document.DoesNotExist(
                f"""{queryset._document._class_name} matching
                query doesn't exist."""
            ) from e

        try:
            # Check if there is another match
            next(queryset)
        except StopIteration:
            return result

        """If we were able to retrieve the 2nd doc,
        raise the MultipleObjectsReturned exception."""
        raise queryset._document.MultipleObjectsReturned(
            "2 or more items returned, instead of 1")

    def create(self, **kwargs):
        """Create new object. Returns the saved object instance."""
        return self._document(**kwargs).save(force_insert=True)

    def first(self):
        """Retrieve the first object matching the query."""
        queryset = self.clone()
        try:
            result = queryset[0]
        except IndexError:
            result = None
        return result

    def insert(self, doc_or_docs, load_bulk=True, write_concern=None):
        """bulk insert documents

        :param doc_or_docs: a document or list of documents to be inserted
        :param load_bulk (optional): If True returns the list of document
            instances
        :param write_concern: Extra keyword arguments are passed down to method
                `pymongo.collection.Collection.insert`
                which will be used as options for the resultant
                ``getLastError`` command.  For example,
                ``insert(..., {w: 2, fsync: True})`` will wait until at least
                two servers have recorded the write and will force an fsync on
                each server being written to.

        By default returns document instances, set ``load_bulk`` to False to
        return just ``ObjectIds``
        """

        if write_concern is None:
            write_concern = {}
        docs = doc_or_docs
        return_one = False
        raw = []
        from mongodb.document import Document
        if isinstance(docs, Document) or issubclass(docs.__class__, Document):
            return_one = True
            docs = [docs]

        for doc in docs:
            self._insert_validation(doc)
            self._document().validate(
                clean=True, insertion=True, data=doc.to_mongo())
            raw.append(doc.to_mongo())

        with set_write_concern(self._collection, write_concern) as collection:
            insert_func = collection.insert_many
            if return_one:
                raw = raw[0]
                insert_func = collection.insert_one

        try:
            inserted_result = insert_func(raw)
            ids = (
                [inserted_result.inserted_id]
                if return_one
                else inserted_result.inserted_ids
            )
        except pymongo.errors.DuplicateKeyError as err:
            raise NotUniqueError(f"Could not save document ({err})") from err
        except pymongo.errors.BulkWriteError as err:
            # inserting documents that already have an _id field will
            # give huge performance debt or raise
            raise BulkWriteError(f"Bulk write error: ({err.details})") from err
        except pymongo.errors.OperationFailure as err:
            raise OperationError(f"Could not save document ({err})") from err

        # Apply inserted_ids to documents
        for doc, doc_id in zip(docs, ids):
            doc.pk = doc_id

        if not load_bulk:
            return ids[0] if return_one else ids

        documents = self.in_bulk(ids)
        results = [documents.get(obj_id) for obj_id in ids]
        return results[0] if return_one else results

    def count(self, with_limit_and_skip=False):
        """Count the selected elements in the query.

        :param with_limit_and_skip (optional): take any :meth:`limit` or
            :meth:`skip` that has been applied to this cursor into account when
            getting the count
        """
        if (
            self._limit == 0
            and with_limit_and_skip is False
            or self._none
            or self._empty
        ):
            return 0

        kwargs = (
            {"limit": self._limit, "skip": self._skip}
            if with_limit_and_skip else {}
        )

        if self._limit == 0:
            # mimic the fact that historically .limit(0) sets no limit
            kwargs.pop("limit", None)

        count = self._cursor.collection.count_documents(
            filter=self._query, **kwargs)

        self._cursor_obj = None
        return count

    def delete(self, write_concern=None, _from_doc_delete=False):
        """Delete the documents matched by the query.

        :param write_concern: Extra keyword arguments are passed down which
            will be used as options for the resultant
            ``getLastError`` command.  For example,
            ``save(..., write_concern={w: 2, fsync: True}, ...)`` will
            wait until at least two servers have recorded the write and
            will force an fsync on the primary server.
        :param _from_doc_delete: True when called from document delete
            therefore signals will have been triggered so don't loop.

        :returns number of deleted documents
        """
        if write_concern is None:
            write_concern = {}
        queryset = self.clone()

        if (
            call_document_delete := (queryset._skip or queryset._limit)  # noqa F841
            and not _from_doc_delete
        ):
            cnt = 0
            for doc in queryset:
                doc.delete(**write_concern)
                cnt += 1
            return cnt

        with set_write_concern(queryset._collection,
                               write_concern) as collection:
            result = collection.delete_many(queryset._query)
            if result.acknowledged:
                return result.deleted_count

    def update(self, upsert=False, multi=True, write_concern=None, read_concern=None, full_result=False, **update):
        """Perform an atomic update on the fields matched by the query.

        :param upsert: insert if document doesn't exist (default ``False``)
        :param multi: Update multiple documents.
        :param write_concern: Extra keyword arguments are passed down which
            will be used as options for the resultant
            ``getLastError`` command.
        :param read_concern: Override the read concern for the operation
        :param full_result: Return the associated ``pymongo.UpdateResult``
            rather than just the number updated items
        :param update: Django-style update keyword arguments

        :returns the number of updated documents unless ``full_result`` is True
        """
        if write_concern is None:
            write_concern = {}
        if not update and not upsert:
            raise OperationError("No update parameters, would remove data")

        queryset = self.clone()
        query = queryset._query
        if "__raw__" in update and isinstance(update["__raw__"], list):
            update = [
                transform.update(queryset._document, **{"__raw__": u})
                for u in update["__raw__"]
            ]
        else:
            update = transform.update(queryset._document, **update)
        # If doing an atomic upsert on an inheritable class
        # then ensure we add _cls to the update operation
        if upsert and "_cls" in query:
            if update.get("$set"):
                update["$set"]["_cls"] = queryset._document._class_name
            else:
                update["$set"] = {"_cls": queryset._document._class_name}
        try:
            with set_read_write_concern(
                queryset._collection, write_concern, read_concern
            ) as collection:
                update_func = collection.update_many if multi else collection.update_one
                result = update_func(query, update, upsert=upsert)
            if full_result:
                return result
            elif result.raw_result:
                return result.raw_result["n"]
        except pymongo.errors.DuplicateKeyError as err:
            raise NotUniqueError(f"Update failed ({err})") from err
        except pymongo.errors.OperationFailure as err:
            raise OperationError(f"Update failed ({err})") from err

    def update_one(
            self,
            upsert=False,
            write_concern=None,
            full_result=False,
            **update):
        """Perform an atomic update on the fields of the first document
        matched by the query.

        :param upsert: insert if document doesn't exist (default ``False``)
        :param write_concern: Extra keyword arguments are passed down which
            will be used as options for the resultant
            ``getLastError`` command.
        :param full_result: Return the associated ``pymongo.UpdateResult``
            rather than just the number updated items
        :param update: Django-style update keyword arguments full_result
        :returns the number of updated documents unless ``full_result`` is True
        """
        return self.update(
            upsert=upsert,
            multi=False,
            write_concern=write_concern,
            full_result=full_result,
            **update,
        )

    def modify(
        self, upsert=False, remove=False, new=False, **update
    ):
        """Update and return the updated document.

        Returns either the document before or after modification based on `new`
        parameter. If no documents match the query and `upsert` is false,
        returns ``None``. If upserting and `new` is false, returns ``None``.

        :param upsert: insert if document doesn't exist (default ``False``)
        :param remove: remove rather than updating (default ``False``)
        :param new: return updated rather than original document
            (default ``False``)
        :param update: Django-style update keyword arguments
        """

        if remove and new:
            raise OperationError("Conflicting parameters: remove and new")

        if not update and not upsert and not remove:
            raise OperationError(
                "No update parameters, must either update or remove")

        queryset = self.clone()
        query = queryset._query
        if not remove:
            update = transform.update(queryset._document, **update)
        sort = queryset._ordering

        try:
            if remove:
                result = queryset._collection.find_one_and_delete(
                    query, sort=sort, **self._cursor_args
                )
            else:
                return_doc = ReturnDocument.AFTER if new else ReturnDocument.BEFORE
                result = queryset._collection.find_one_and_update(
                    query,
                    update,
                    upsert=upsert,
                    sort=sort,
                    return_document=return_doc,
                    **self._cursor_args,
                )
        except pymongo.errors.DuplicateKeyError as err:
            raise NotUniqueError(f"Update failed ({err})") from err
        except pymongo.errors.OperationFailure as err:
            raise OperationError(f"Update failed ({err})") from err

        if result is not None:
            result = self._document._from_son(result)

        return result

    def with_id(self, object_id):
        """Retrieve the object matching the id provided.  Uses `object_id` only
        and raises InvalidQueryError if a filter has been applied. Returns
        `None` if no document exists with that id.

        :param object_id: the value for the id of the document to look up
        """
        queryset = self.clone()
        if queryset._query_obj:
            msg = "Cannot use a filter whilst using `with_id`"
            raise InvalidQueryError(msg)
        return queryset.filter(pk=object_id).first()

    def in_bulk(self, object_ids):
        """Retrieve a set of documents by their ids.

        :param object_ids: a list or tuple of ObjectId's
        :rtype: dict of ObjectId's as keys and collection-specific
                Document subclasses as values.
        """
        doc_map = {}

        docs = self._collection.find(
            {"_id": {"$in": object_ids}}, **self._cursor_args)
        if self._scalar:
            for doc in docs:
                doc_map[doc["_id"]] = self._get_scalar(
                    self._document._from_son(doc))
        elif self._as_pymongo:
            for doc in docs:
                doc_map[doc["_id"]] = doc
        else:
            for doc in docs:
                doc_map[doc["_id"]] = self._document._from_son(
                    doc,
                )

        return doc_map

    def clone(self):
        """Create a copy of the current queryset."""
        return self._clone_into(self.__class__(self._document,
                                               self._collection_obj))

    def explain(self):
        """Returns an explain plan record for the query execution.
        It uses default verbosity mode as 'allPlansExecution' to explain query.
        """
        return self._cursor.explain()

    def _clone_into(self, new_qs):
        """Copy all of the relevant properties of this queryset to
        a new queryset (which has to be an instance of
        :class:`~mongodb.queryset.base.BaseQuerySet`).
        """
        if not isinstance(new_qs, BaseQuerySet):
            raise OperationError(
                f"{new_qs.__name__} is not a subclass of BaseQuerySet"
            )

        copy_props = (
            "_mongo_query",
            "_cls_query",
            "_none",
            "_query_obj",
            "_where_clause",
            "_loaded_fields",
            "_ordering",
            "_timeout",
            "_allow_disk_use",
            "_read_preference",
            "_read_concern",
            "_iter",
            "_scalar",
            "_as_pymongo",
            "_limit",
            "_skip",
            "_empty",
            "_search_text",
            "_batch_size",
        )

        for prop in copy_props:
            val = getattr(self, prop)
            setattr(new_qs, prop, copy.copy(val))

        if self._cursor_obj:
            new_qs._cursor_obj = self._cursor_obj.clone()

        return new_qs

    def _insert_validation(self, object):
        if not isinstance(object, self._document):
            raise OperationError(
                f"""Some of the inserted documents aren't instances
                    of {str(self._document)}""")
        if object.pk and not object._created:
            raise OperationError(
                """Some of the documents have ObjectIds,
                use doc.update() instead""")

    def limit(self, n):
        """Limit the number of returned documents to `n`. This may also be
        achieved using array-slicing syntax (e.g. ``User.objects[:5]``).

        :param n: the maximum number of objects to return if n > 0.
        When 0 is passed, returns all the documents in the cursor
        """
        queryset = self.clone()
        queryset._limit = n
        queryset._empty = False  # cancels the effect of empty

        # If a cursor object has already been created, apply the limit to it.
        if queryset._cursor_obj:
            queryset._cursor_obj.limit(queryset._limit)

        return queryset

    def skip(self, n):
        """Skip `n` documents before returning the results. This may also be
        achieved using array-slicing syntax (e.g. ``User.objects[5:]``).

        :param n: the number of objects to skip before returning results
        """
        queryset = self.clone()
        queryset._skip = n

        # If a cursor object has already been created, apply the skip to it.
        if queryset._cursor_obj:
            queryset._cursor_obj.skip(queryset._skip)

        return queryset

    def batch_size(self, size):
        """Limit the number of documents returned in a single batch (each
        batch requires a round trip to the server).

        :param size: desired size of each batch.
        """
        queryset = self.clone()
        queryset._batch_size = size

        # If a cursor object has already been created,
        # apply the batch size to it.
        if queryset._cursor_obj:
            queryset._cursor_obj.batch_size(queryset._batch_size)

        return queryset

    def only(self, *fields):
        """Load only a subset of this document's fields. ::

            post = BlogPost.objects(...).only('title', 'author.name')

        :func:`~mongodb.queryset.QuerySet.all_fields` will reset any
        field filters.

        :param fields: fields to include
        """
        fields = {f: QueryFieldList.ONLY for f in fields}
        return self.fields(True, **fields)

    def exclude_fields(self, *fields):
        """Opposite to .only(), exclude some document's fields. ::

            post = BlogPost.objects(...).exclude('comments')

        :func:`~mongodb.queryset.QuerySet.all_fields` will reset any
        field filters.

        :param fields: fields to exclude
        """
        fields = {f: QueryFieldList.EXCLUDE for f in fields}
        return self.fields(**fields)

    def exclude(self, *q_objs, **query):
        return self.__call__(*q_objs, negate_query=True, **query)

    def fields(self, _only_called=False, **kwargs):
        """Manipulate how you load this document's fields. Used by `.only()`
        and `.exclude_fields()` to manipulate which fields to retrieve.
        If called directly, use a set of kwargs similar to the MongoDB
        projection document.
        For example:

        Include only a subset of fields:

            posts = BlogPost.objects(...).fields(author=1, title=1)

        Exclude a specific field:

            posts = BlogPost.objects(...).fields(comments=0)

        To retrieve a subrange or sublist of array elements,
        support exist for both the `slice` and `elemMatch` projection operator:

            posts = BlogPost.objects(...).fields(slice__comments=5)
            posts = BlogPost.objects(...).fields(elemMatch__comments="test")

        :param kwargs: A set of keyword arguments identifying what to
            include, exclude, or slice.
        """

        # Check for an operator and transform to mongo-style if there is
        operators = ["slice", "elemMatch"]
        cleaned_fields = []
        for key, value in kwargs.items():
            parts = key.split("__")
            if parts[0] in operators:
                op = parts.pop(0)
                value = {f"${op}": value}
            key = ".".join(parts)
            cleaned_fields.append((key, value))

        # Sort fields by their values, explicitly excluded fields first, then
        # explicitly included, and then more complicated operators such as
        # $slice.
        def _sort_key(field_tuple):
            _, value = field_tuple
            return value if isinstance(value, int) else 2

        fields = sorted(cleaned_fields, key=_sort_key)

        # Clone the queryset, group all fields by their value, convert
        # each of them to db_fields, and set the queryset's _loaded_fields
        queryset = self.clone()
        for value, group in itertools.groupby(fields, lambda x: x[1]):
            fields = [field for field, value in group]
            fields = queryset._fields_to_dbfields(fields)
            queryset._loaded_fields += QueryFieldList(
                fields, value=value, _only_called=_only_called
            )

        return queryset

    def all_fields(self):
        """Include all fields. Reset all previously calls of .only() or
        .exclude(). ::

            post = BlogPost.objects.exclude('comments').all_fields()
        """
        queryset = self.clone()
        queryset._loaded_fields = QueryFieldList(
            always_include=queryset._loaded_fields.always_include
        )
        return queryset

    def order_by(self, *keys):
        """Order the :class:`~mongodb.queryset.QuerySet` by the given keys.

        The order may be specified by prepending each of the keys by a "+" or
        a "-". Ascending order is assumed if there's no prefix.

        If no keys are passed, existing ordering is cleared instead.

        :param keys: fields to order the query results by; keys may be
            prefixed with "+" or a "-" to determine the ordering direction.
        """
        queryset = self.clone()

        old_ordering = queryset._ordering
        new_ordering = queryset._get_order_by(keys)

        if queryset._cursor_obj:

            # If a cursor object has already been created, apply the sort to it
            if new_ordering:
                queryset._cursor_obj.sort(new_ordering)

            # If we're trying to clear a previous explicit ordering, we need
            # to clear the cursor entirely (because PyMongo doesn't allow
            # clearing an existing sort on a cursor).
            elif old_ordering:
                queryset._cursor_obj = None

        queryset._ordering = new_ordering

        return queryset

    def clear_cls_query(self):
        """Clear the default "_cls" query.

        By default, all queries generated for documents that allow inheritance
        include an extra "_cls" clause. In most cases this is desirable, but
        sometimes you might achieve better performance if you clear that
        default query.

        Scan the code for `_cls_query` to get more details.
        """
        queryset = self.clone()
        queryset._cls_query = {}
        return queryset

    def allow_disk_use(self, enabled):
        """Enable or disable the use of temporary files on disk while
            processing a blocking sort operation.
         (To store data exceeding the 100 megabyte system memory limit)

        :param enabled: whether or not temporary files on disk are used
        """
        queryset = self.clone()
        queryset._allow_disk_use = enabled
        return queryset

    def timeout(self, enabled):
        """Enable or disable the default mongod timeout when querying.

        :param enabled: whether or not the timeout is used
        """
        queryset = self.clone()
        queryset._timeout = enabled
        return queryset

    def read_preference(self, read_preference):
        """Change the read_preference when querying.

        :param read_preference: override ReplicaSetConnection-level
            preference.
        """
        validate_read_preference("read_preference", read_preference)
        queryset = self.clone()
        queryset._read_preference = read_preference
        # we need to re-create the cursor object
        # whenever we apply read_preference
        queryset._cursor_obj = None
        return queryset

    def read_concern(self, read_concern):
        """Change the read_concern when querying.

        :param read_concern: override ReplicaSetConnection-level
            preference.
        """
        if read_concern is not None and not isinstance(read_concern, Mapping):
            raise TypeError(f"{read_concern!r} is not a valid read concern.")

        queryset = self.clone()
        queryset._read_concern = (
            ReadConcern(**read_concern) if read_concern is not None else None
        )
        # we need to re-create the cursor object whenever we apply read_concern
        queryset._cursor_obj = None
        return queryset

    def scalar(self, *fields):
        """Instead of returning Document instances, return either a specific
        value or a tuple of values in order.

        .. note:: This effects all results and can be unset by calling
                  ``scalar`` without arguments. Calls ``only`` automatically.

        :param fields: One or more fields to return instead of a Document.
        """
        queryset = self.clone()
        queryset._scalar = list(fields)
        queryset = queryset.only(*fields) if fields else queryset.all_fields()
        return queryset

    def distinct(self, field):
        """Return a list of distinct values for a given field.

        :param field: the field to select distinct values from

        .. note:: This is a command and won't take ordering or limit into
           account.
        """
        from mongodb.fields import ListField
        queryset = self.clone()

        with contextlib.suppress(LookUpError):
            field = self._fields_to_dbfields([field]).pop()
        raw_values = queryset._cursor.distinct(field)

        distinct = self._dereference(
            raw_values, 1, name=field, instance=self._document)

        doc_field = self._document._fields.get(field.split(".", 1)[0])

        if isinstance(doc_field, ListField):
            doc_field = getattr(doc_field, "field", doc_field)

        # handle distinct on subdocuments
        if "." in field:
            for field_part in field.split(".")[1:]:
                # now get the subdocument
                doc_field = getattr(doc_field, field_part, doc_field)
                if isinstance(doc_field, ListField):
                    doc_field = getattr(doc_field, "field", doc_field)

        return distinct

    def values_list(self, *fields):
        """An alias for scalar"""
        return self.scalar(*fields)

    def values(self, *fields):
        """
        Retrieve the specified fields from the queryset and
        return them as a list of dictionaries.

        Args:
            *fields: Variable-length argument list of fields to include
            in the result. Each field should be a string representing
            the name of an attribute or field in the objects of the queryset.

        Returns:
            A list of dictionaries, where each dictionary represents the
            specified fields and their corresponding values for each object in the queryset.

        Example:
            # Assuming a 'Book' model with 'title', 'author', and 'price' fields
            queryset = Book.objects.all()
            queryset_values = queryset.values('title', 'price')

            # Output:
            [
                {'title': 'Book 1', 'price': 29.99},
                {'title': 'Book 2', 'price': 39.99},
                ...
            ]
        """
        cursor = self.only(*fields)
        return [{field: getattr(obj, field) for field in fields} for obj in cursor]

    def as_pymongo(self):
        """Instead of returning Document instances, return raw values from
        pymongo.

        This method is particularly useful if you don't need dereferencing
        and care primarily about the speed of data retrieval.
        """
        queryset = self.clone()
        queryset._as_pymongo = True
        return queryset

    # JSON Helpers

    def to_json(self, *args, **kwargs):
        """Converts a queryset to JSON"""
        if "json_options" not in kwargs:
            warnings.warn(
                "No 'json_options' are specified! Falling back to "
                "LEGACY_JSON_OPTIONS with uuid_representation=PYTHON_LEGACY. "
                "For use with other MongoDB drivers specify the UUID "
                "representation to use.",
                DeprecationWarning,
            )
            kwargs["json_options"] = LEGACY_JSON_OPTIONS
        return json_util.dumps(self.as_pymongo(), *args, **kwargs)

    def from_json(self, json_data):
        """Converts json data to unsaved objects"""
        son_data = json_util.loads(json_data)
        return [self._document._from_son(data) for data in son_data]

    def aggregate(self, pipeline, **kwargs):
        """Perform a aggregate function based in your queryset params

        :param pipeline: list of aggregation commands
        :param kwargs: (optional) kwargs dictionary
            to be passed to pymongo's aggregate call
        """
        user_pipeline = [pipeline] if isinstance(
            pipeline, dict) else list(pipeline)

        initial_pipeline = []
        if self._query:
            initial_pipeline.append({"$match": self._query})

        if self._ordering:
            initial_pipeline.append({"$sort": dict(self._ordering)})

        if self._limit is not None:
            initial_pipeline.append(
                {"$limit": self._limit + (self._skip or 0)})

        if self._skip is not None:
            initial_pipeline.append({"$skip": self._skip})

        final_pipeline = initial_pipeline + user_pipeline

        collection = self._collection
        if self._read_preference is not None or self._read_concern is not None:
            collection = self._collection.with_options(
                read_preference=self._read_preference,
                read_concern=self._read_concern
            )

        return collection.aggregate(final_pipeline, cursor={}, **kwargs)

    # Iterator helpers

    def __next__(self):
        """Wrap the result in a :class:`~mongodb.Document` object."""
        if self._none or self._empty:
            raise StopIteration

        raw_doc = next(self._cursor)

        if self._as_pymongo:
            return raw_doc

        doc = self._document._from_son(
            raw_doc,
        )

        return self._get_scalar(doc) if self._scalar else doc

    def rewind(self):
        """Rewind the cursor to its unevaluated state."""
        self._iter = False
        self._cursor.rewind()

    # Properties

    @property
    def _collection(self):
        """Property that returns the collection object. This allows us to
        perform operations only if the collection is accessed.
        """
        return self._collection_obj

    @property
    def _cursor_args(self):
        fields_name = "projection"
        cursor_args = {}
        if not self._timeout:
            cursor_args["no_cursor_timeout"] = True

        if self._allow_disk_use:
            cursor_args["allow_disk_use"] = True

        if self._loaded_fields:
            cursor_args[fields_name] = self._loaded_fields.as_dict()

        if self._search_text:
            fields_name = "projection"

            if fields_name not in cursor_args:
                cursor_args[fields_name] = {}

            cursor_args[fields_name]["_text_score"] = {"$meta": "textScore"}

        return cursor_args

    @property
    def _cursor(self):
        """Return a PyMongo cursor object corresponding to this queryset."""

        # If _cursor_obj already exists, return it immediately.
        if self._cursor_obj is not None:
            return self._cursor_obj

        # Create a new PyMongo cursor.
        # XXX In PyMongo 3+, we define the read preference on a collection
        # level, not a cursor level. Thus, we need to get a cloned collection
        # object using `with_options` first.
        if self._read_preference is not None or self._read_concern is not None:
            self._cursor_obj = self._collection.with_options(
                read_preference=self._read_preference,
                read_concern=self._read_concern
            ).find(self._query, **self._cursor_args)
        else:
            self._cursor_obj = self._collection.find(
                self._query, **self._cursor_args)

        # Apply "where" clauses to cursor
        if self._where_clause:
            where_clause = self._sub_js_fields(self._where_clause)
            self._cursor_obj.where(where_clause)

        # Apply ordering to the cursor.
        # XXX self._ordering can be equal to:
        # * None if we didn't explicitly call order_by on this queryset.
        # * A list of PyMongo-style sorting tuples.
        # * An empty list if we explicitly called order_by() without any
        #   arguments. This indicates that we want to clear the default
        #   ordering.
        if self._ordering:
            # explicit ordering
            self._cursor_obj.sort(self._ordering)
        elif self._ordering is None and self._document._meta["ordering"]:
            # default ordering
            order = self._get_order_by(self._document._meta["ordering"])
            self._cursor_obj.sort(order)

        if self._limit is not None:
            self._cursor_obj.limit(self._limit)

        if self._skip is not None:
            self._cursor_obj.skip(self._skip)

        if self._batch_size is not None:
            self._cursor_obj.batch_size(self._batch_size)

        return self._cursor_obj

    def __deepcopy__(self, memo):
        """Essential for chained queries with ReferenceFields involved"""
        return self.clone()

    @property
    def _query(self):
        if self._mongo_query is None:
            self._mongo_query = self._query_obj.to_query(self._document)
            if self._cls_query:
                if "_cls" in self._mongo_query:
                    self._mongo_query = {
                        "$and": [self._cls_query, self._mongo_query]}
                else:
                    self._mongo_query.update(self._cls_query)
        return self._mongo_query

    @property
    def _dereference(self):
        if not self.__dereference:
            from mongodb.dereference import DeReference
            self.__dereference = DeReference()
        return self.__dereference

    # Helper Functions

    def _fields_to_dbfields(self, fields):
        """Translate fields' paths to their db equivalents."""

        db_field_paths = []
        for field in fields:
            field_parts = field.split(".")
            field = ".".join(
                f if isinstance(f, str) else f.db_column
                for f in self._document._lookup_field(field_parts)
            )
            db_field_paths.append(field)

        return db_field_paths

    def _get_order_by(self, keys):
        """Given a list of mongodb-style sort keys, return a list
        of sorting tuples that can be applied to a PyMongo cursor. For
        example:

        >>> qs._get_order_by(['-last_name', 'first_name'])
        [('last_name', -1), ('first_name', 1)]
        """
        key_list = []
        for key in keys:
            if not key:
                continue

            if key == "$text_score":
                key_list.append(("_text_score", {"$meta": "textScore"}))
                continue

            direction = pymongo.ASCENDING
            if key[0] == "-":
                direction = pymongo.DESCENDING

            if key[0] in ("-", "+"):
                key = key[1:]

            key = key.replace("__", ".")
            with contextlib.suppress(Exception):
                key = self._document._translate_field_name(key)
            key_list.append((key, direction))

        return key_list

    def _get_scalar(self, doc):
        def lookup(obj, name):
            chunks = name.split("__")
            for chunk in chunks:
                obj = getattr(obj, chunk)
            return obj

        data = [lookup(doc, n) for n in self._scalar]
        return data[0] if len(data) == 1 else tuple(data)

    def _sub_js_fields(self, code):
        """When fields are specified with [~fieldname] syntax, where
        *fieldname* is the Python name of a field, *fieldname* will be
        substituted for the MongoDB name of the field (specified using the
        :attr:`name` keyword argument in a field's constructor).
        """

        def field_sub(match):
            # Extract just the field name, and look up the field objects
            field_name = match.group(1).split(".")
            fields = self._document._lookup_field(field_name)
            # Substitute the correct name for the field into the javascript
            return f'["{fields[-1].db_column}"]'

        def field_path_sub(match):
            # Extract just the field name, and look up the field objects
            field_name = match.group(1).split(".")
            fields = self._document._lookup_field(field_name)
            # Substitute the correct name for the field into the javascript
            return ".".join([f.db_column for f in fields])

        code = re.sub(r"\[\s*~([A-z_][A-z_0-9.]+?)\s*\]", field_sub, code)
        code = re.sub(
            r"\{\{\s*~([A-z_][A-z_0-9.]+?)\s*\}\}", field_path_sub, code)
        return code

    def _chainable_method(self, method_name, val):
        """Call a particular method on the PyMongo cursor call
        a particular chainable method with the provided value.
        """
        queryset = self.clone()

        # Get an existing cursor object or create a new one
        cursor = queryset._cursor

        # Find the requested method on the cursor and call it with the
        # provided value
        getattr(cursor, method_name)(val)

        # Cache the value on the queryset._{method_name}
        setattr(queryset, f"_{method_name}", val)

        return queryset
