import pymongo
from bson import binary, json_util

PYMONGO_VERSION = tuple(pymongo.version_tuple[:2])
LEGACY_JSON_OPTIONS = json_util.LEGACY_JSON_OPTIONS.with_options(
    uuid_representation=binary.UuidRepresentation.PYTHON_LEGACY,
)
