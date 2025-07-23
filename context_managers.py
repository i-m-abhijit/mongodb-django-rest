from contextlib import contextmanager

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


@contextmanager
def set_write_concern(collection, write_concerns):
    combined_concerns = dict(collection.write_concern.document.items())
    combined_concerns.update(write_concerns)
    yield collection.with_options(
        write_concern=WriteConcern(**combined_concerns))


@contextmanager
def set_read_write_concern(collection, write_concerns, read_concerns):
    combined_write_concerns = dict(collection.write_concern.document.items())

    if write_concerns is not None:
        combined_write_concerns.update(write_concerns)

    combined_read_concerns = dict(collection.read_concern.document.items())

    if read_concerns is not None:
        combined_read_concerns.update(read_concerns)

    yield collection.with_options(
        write_concern=WriteConcern(**combined_write_concerns),
        read_concern=ReadConcern(**combined_read_concerns),
    )
