# MongoDB REST

A Python library that provides MongoDB integration with Django REST framework support.

## Features

- Simple MongoDB connection management
- Document-based data modeling
- Django REST framework serializers for MongoDB documents
- Query and field management utilities

## Installation

```bash
pip install mongodb-rest
```

## Quick Start

```python
from mongodb import connect, Document, DocumentSerializer

# Connect to MongoDB
connect('your-database-name')

# Define a document
class User(Document):
    name = StringField(required=True)
    email = EmailField(required=True)

# Use with Django REST framework
class UserSerializer(DocumentSerializer):
    class Meta:
        model = User
        fields = '__all__'
```

## Requirements

- Python 3.8+
- PyMongo 4.0+
- Django 3.2+
- Django REST framework 3.12+

## License

MIT License