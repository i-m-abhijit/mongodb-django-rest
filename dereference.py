from bson import SON, DBRef

from mongodb.base.common import get_document
from mongodb.base.datastructures import BaseDict, BaseList, LazyReference
from mongodb.base.metaclasses import TopLevelDocumentMetaclass
from mongodb.connection import get_db
from mongodb.document import Document
from mongodb.fields import DictField, ListField
from mongodb.queryset import QuerySet


class DeReference:
    def __call__(self, items, max_depth=1, instance=None, name=None):
        """
        Cheaply dereferences the items to a set depth.
        Also handles the conversion of complex data types.

        :param items: The iterable (dict, list, queryset) to be dereferenced.
        :param max_depth: The maximum depth to recurse to
        :param instance: The owning instance used for tracking changes by
            :class:`ComplexBaseField`
        :param name: The name of the field, used for tracking changes by
            :class:`ComplexBaseField`
        :param get: A boolean determining if being called by __get__
        """
        if items is None or isinstance(items, str):
            return items

        # cheapest way to convert a queryset to a list
        # list(queryset) uses a count() query to determine length
        if isinstance(items, QuerySet):
            items = list(items)

        self.max_depth = max_depth
        doc_type = None

        if instance and isinstance(
            instance, (Document, TopLevelDocumentMetaclass)
        ):
            doc_type = instance._fields.get(name)
            while hasattr(doc_type, "field"):
                doc_type = doc_type.field
        self.reference_map = self._find_references(items)
        self.object_map = self._fetch_objects(doc_type=doc_type)
        return self._attach_objects(items, 0, instance, name)

    def _find_references(self, items, depth=0):
        """
        Recursively finds all db references to be dereferenced

        :param items: The iterable (dict, list, queryset)
        :param depth: The current depth of recursion
        """
        reference_map = {}
        if not items or depth >= self.max_depth:
            return reference_map

        # Determine the iterator to use
        iterator = items.values() if isinstance(items, dict) else items

        # Recursively find dbreferences
        depth += 1
        return self._find_dbreferences(reference_map, iterator, depth)

    def _find_dbreferences(self, reference_map, iterator, depth):
        for item in iterator:
            if isinstance(item, (Document,)):
                self._process_document_item(reference_map, item, depth)
            elif isinstance(item, LazyReference):
                continue
            elif isinstance(item, DBRef):
                self._process_dbref_item(reference_map, item)
            elif isinstance(item, (dict, SON)) and "_ref" in item:
                self._process_dict_item(reference_map, item)
            elif isinstance(item, (dict, list, tuple)) and depth - 1 <= self.max_depth:
                references = self._find_references(item, depth - 1)
                for key, refs in references.items():
                    reference_map.setdefault(key, set()).update(refs)

        return reference_map

    def _process_document_item(self, reference_map, item, depth):
        for field_name, field in item._fields.items():
            v = item._data.get(field_name)
            if isinstance(v, LazyReference):
                continue
            elif isinstance(v, DBRef):
                reference_map.setdefault(field.document_type, set()).add(v.id)
            elif isinstance(v, (dict, SON)) and "_ref" in v:
                reference_map.setdefault(get_document(v["_cls"]), set()).add(v["_ref"].id)
            elif isinstance(v, (dict, list, tuple)) and depth <= self.max_depth:
                field_cls = getattr(getattr(field, "field", None), "document_type", None)
                references = self._find_references(v, depth)
                for key, refs in references.items():
                    if isinstance(field_cls, (Document, TopLevelDocumentMetaclass)):
                        key = field_cls
                    reference_map.setdefault(key, set()).update(refs)

    def _process_dbref_item(self, reference_map, item):
        reference_map.setdefault(item.collection, set()).add(item.id)

    def _process_dict_item(self, reference_map, item):
        reference_map.setdefault(get_document(item["_cls"]), set()).add(item["_ref"].id)

    def _fetch_objects(self, doc_type=None):
        """Fetch all references and convert to their document objects"""
        object_map = {}
        for collection, dbrefs in self.reference_map.items():
            ref_document_cls_exists = \
                getattr(collection, "objects", None) is not None

            if ref_document_cls_exists:
                col_name = collection._get_collection_name()
                refs = [
                    dbref for dbref in dbrefs
                    if (col_name, dbref) not in object_map
                ]
                references = collection.objects.in_bulk(refs)
                for key, doc in references.items():
                    object_map[(col_name, key)] = doc
            else:
                # Generic reference: use the refs data to convert to document
                if isinstance(doc_type, (ListField, DictField)):
                    continue

                refs = [
                    dbref for dbref in dbrefs
                    if (collection, dbref) not in object_map
                ]

                if doc_type:
                    references = doc_type._get_db()[collection].find(
                        {"_id": {"$in": refs}}
                    )
                    for ref in references:
                        doc = doc_type._from_son(ref)
                        object_map[(collection, doc.id)] = doc
                else:
                    references = get_db()[collection].find(
                        {"_id": {"$in": refs}})
                    for ref in references:
                        if "_cls" in ref:
                            doc = get_document(ref["_cls"])._from_son(ref)
                        elif doc_type is None:
                            doc = get_document(
                                "".join(x.capitalize()
                                        for x in collection.split("_"))
                            )._from_son(ref)
                        else:
                            doc = doc_type._from_son(ref)
                        object_map[(collection, doc.id)] = doc
        return object_map

    def _attach_objects(self, items, depth=0, instance=None, name=None):
        """
        Recursively finds all db references to be dereferenced

        :param items: The iterable (dict, list, queryset)
        :param depth: The current depth of recursion
        :param instance: The owning instance used for tracking changes by
            :class:`ComplexBaseField`
        :param name: The name of the field, used for tracking changes by
            :class:`ComplexBaseField`
        """
        if not items:
            if isinstance(items, (BaseDict, BaseList)):
                return items

            if instance:
                return BaseDict(items, instance, name) if isinstance(items, dict) else BaseList(items, instance, name)

        if isinstance(items, (dict, SON)):
            if "_ref" in items:
                return self._get_referenced_object(items["_ref"])
            elif "_cls" in items:
                return self._recurr_attach_objects(items, depth)

        is_list = not hasattr(items, "items")
        data = items if is_list else {}

        depth += 1
        for k, v in (enumerate(items) if is_list else items.items()):
            if is_list:
                data[k] = self._process_list_item_for_attach_objects(v, depth, instance, name, k)
            else:
                data[k] = self._process_dict_item_for_attach_objects(v, depth, instance, name, k)

        if instance and name:
            if is_list:
                return tuple(data) if isinstance(items, tuple) else BaseList(data, instance, name)
            return BaseDict(data, instance, name)
        depth += 1
        return data

    def _get_referenced_object(self, ref):
        return self.object_map.get((ref.collection, ref.id), ref)

    def _process_list_item_for_attach_objects(self, item, depth, instance, name, index):
        if index in self.object_map:
            return self.object_map[index]
        elif isinstance(item, Document):
            for field_name in item._fields:
                item._data[field_name] = self._get_field_value(item._data.get(field_name, None), depth, instance, name, index, field_name)
        elif isinstance(item, (dict, list, tuple)) and depth <= self.max_depth:
            return self._attach_objects(item, depth - 1, instance=instance, name=f"{name}.{index}" if name else name)
        elif isinstance(item, DBRef) and hasattr(item, "id"):
            return self.object_map.get((item.collection, item.id), item)
        return item

    def _process_dict_item_for_attach_objects(self, item, depth, instance, name, key):
        if key in self.object_map:
            return self.object_map[key]
        elif isinstance(item, (Document,)):
            for field_name in item._fields:
                item._data[field_name] = self._get_field_value(item._data.get(field_name, None), depth, instance, name, key, field_name)
        elif isinstance(item, (dict, list, tuple)) and depth <= self.max_depth:
            return self._attach_objects(item, depth - 1, instance=instance, name=f"{name}.{key}" if name else name)
        elif isinstance(item, DBRef) and hasattr(item, "id"):
            return self.object_map.get((item.collection, item.id), item)
        return item

    def _recurr_attach_objects(self, items, depth):
        doc = get_document(items["_cls"])._from_son(items)
        _cls = doc._data.pop("_cls", None)
        del items["_cls"]
        doc._data = self._attach_objects(doc._data, depth, doc, None)
        if _cls is not None:
            doc._data["_cls"] = _cls
        return doc

    def _get_field_value(self, v, depth, instance, name, k, field_name):
        if isinstance(v, DBRef):
            return self.object_map.get(
                (v.collection, v.id), v
            )
        if isinstance(v, (dict, SON)) and "_ref" in v:
            return self.object_map.get(
                (v["_ref"].collection, v["_ref"].id), v
            )
        if isinstance(v, (dict, list, tuple)) and \
                depth <= self.max_depth:
            return self._attach_objects(
                v, depth, instance=instance,
                name=f"{name}.{k}.{field_name}"
            )
