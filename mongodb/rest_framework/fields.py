from bson import ObjectId
from bson.errors import InvalidId
from django.utils.encoding import smart_str
from rest_framework import serializers


class ObjectIdField(serializers.Field):
    """ Field for ObjectId values """

    def to_internal_value(self, value):
        try:
            return ObjectId(smart_str(value))
        except InvalidId as e:
            raise serializers.ValidationError(
                f"'{value}' is not a valid ObjectId"
            ) from e

    def to_representation(self, value):
        return smart_str(value)
