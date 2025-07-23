# Import everything from each submodule so that it can be accessed via
# mongodb, e.g. instead of `from mongodb.connection import connect`,
# users can simply use `from mongodb import connect`, or even
# `from mongodb import *` and then `connect('testdb')`.
from mongodb.connection import connect, disconnect
from mongodb.document import Document
from mongodb.rest_framework.serializers import DocumentSerializer

__all__ = (
    "connect",
    "disconnect",
    "Document",
    "DocumentSerializer"
)
