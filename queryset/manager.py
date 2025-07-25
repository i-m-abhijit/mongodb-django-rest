from functools import partial

from mongodb.queryset.queryset import QuerySet


class QuerySetManager:
    """
    The default QuerySet Manager.

    Custom QuerySet Manager functions can extend this class and users can
    add extra queryset functionality.  Any custom manager methods must accept a
    :class:`Document` class as its first argument, and a
    :class:`QuerySet` as its second argument.

    The method function should return a :class:`QuerySet`
    , probably the same one that was passed in, but modified in some way.
    """

    get_queryset = None
    default = QuerySet

    def __init__(self, queryset_func=None):
        if queryset_func:
            self.get_queryset = queryset_func

    def __get__(self, instance, owner):
        """
        Descriptor for instantiating a new QuerySet object
        when Document.objects is accessed.
        """
        if instance is not None:
            # Document object being used rather than a document class
            return self

        # owner is the document that contains the QuerySetManager
        queryset_class = owner._meta.get("queryset_class", self.default)
        queryset = queryset_class(owner, owner._get_collection())

        if self.get_queryset:
            arg_count = self.get_queryset.__code__.co_argcount
            if arg_count == 1:
                queryset = self.get_queryset(queryset)
            elif arg_count == 2:
                queryset = self.get_queryset(owner, queryset)
            else:
                queryset = partial(self.get_queryset, owner, queryset)
        return queryset
