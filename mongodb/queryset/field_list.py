class QueryFieldList:
    """Object that handles combinations of .only() and .exclude() calls"""

    ONLY = 1
    EXCLUDE = 0

    def __init__(
        self, fields=None, value=ONLY, always_include=None, _only_called=False
    ):
        """The QueryFieldList builder

        :param fields: A list of fields used in `.only()` or `.exclude_fields()`
        :param value: How to handle the fields; either `ONLY` or `EXCLUDE`
        :param always_include: Any fields to always_include eg `_cls`
        :param _only_called: Has `.only()` been called?  If so its a set of fields
           otherwise it performs a union.
        """
        self.value = value
        self.fields = set(fields or [])
        self.always_include = set(always_include or [])
        self._id = None
        self._only_called = _only_called
        self.slice = {}

    def __add__(self, f):  # noqa C901
        if isinstance(f.value, dict):
            for field in f.fields:
                self.slice[field] = f.value
            if not self.fields:
                self.fields = f.fields
        elif not self.fields:
            self.fields = f.fields
            self.value = f.value
            self.slice = {}
        elif self.value == self.ONLY:
            if f.value == self.ONLY:
                self._clean_slice()
                self.fields = self.fields.union(f.fields) if self._only_called else f.fields
            elif f.value == self.EXCLUDE:
                self.fields -= f.fields
                self._clean_slice()
        elif self.value == self.EXCLUDE:
            if f.value == self.EXCLUDE:
                self.fields = self.fields.union(f.fields)
            elif f.value == self.ONLY:
                self.value = self.ONLY
                self.fields = f.fields - self.fields
            self._clean_slice()

        if "_id" in f.fields:
            self._id = f.value

        if self.always_include:
            if self.value == self.ONLY and self.fields and \
                    sorted(self.slice.keys()) != sorted(self.fields):
                self.fields = self.fields.union(self.always_include)
            else:
                self.fields -= self.always_include

        if getattr(f, "_only_called", False):
            self._only_called = True
        return self

    def __bool__(self):
        return bool(self.fields)

    def as_dict(self):
        field_list = {field: self.value for field in self.fields}
        if self.slice:
            field_list.update(self.slice)
        if self._id is not None:
            field_list["_id"] = self._id
        return field_list

    def reset(self):
        self.fields = set()
        self.slice = {}
        self.value = self.ONLY

    def _clean_slice(self):
        if self.slice:
            for field in set(self.slice.keys()) - self.fields:
                del self.slice[field]
