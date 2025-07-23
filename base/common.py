from mongodb.errors import NotRegistered

_document_registry = {}


def get_document(name):
    """Get a registered Document class by name."""
    doc = _document_registry.get(name)
    if not doc:
        # Possible old style name
        single_end = name.split(".")[-1]
        compound_end = f".{single_end}"
        possible_match = [
            k for k in _document_registry if k.endswith(compound_end)
            or k == single_end
        ]
        if len(possible_match) == 1:
            doc = _document_registry.get(possible_match.pop(), None)
    if not doc:
        raise NotRegistered(
            f"""
                `{name}` has not been registered in the document registry.
                Importing the document class automatically registers it, has it
                been imported?
            """.strip()
        )
    return doc


def _get_documents_by_db(connection_alias, default_connection_alias):
    """Get all registered Documents class attached to a given database"""

    def get_doc_alias(doc_cls):
        return doc_cls._meta.get("db_alias", default_connection_alias)

    return [
        doc_cls
        for doc_cls in _document_registry.values()
        if get_doc_alias(doc_cls) == connection_alias
    ]
