# MongoDB Django REST Library - Complete Documentation

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Connection Management](#connection-management)
5. [Document Models](#document-models)
6. [Field Types](#field-types)
7. [QuerySet Operations](#queryset-operations)
8. [Django REST Framework Integration](#django-rest-framework-integration)
9. [Advanced Features](#advanced-features)
10. [Error Handling](#error-handling)
11. [Best Practices](#best-practices)
12. [API Reference](#api-reference)

## Overview

The MongoDB Django REST library provides a comprehensive MongoDB integration for Django applications with full Django REST framework support. It offers an ORM-like interface similar to Django's built-in ORM but designed specifically for MongoDB.

### Key Features

- **MongoDB Connection Management**: Multiple database connections with aliases
- **Document-Based Models**: Define MongoDB documents similar to Django models
- **Rich Field Types**: Comprehensive field types for MongoDB data
- **QuerySet API**: Django-like querying interface
- **REST Framework Integration**: Seamless serialization for APIs
- **Validation System**: Built-in data validation
- **Indexing Support**: Database indexing configuration
- **Signal System**: Pre/post save hooks
- **Context Managers**: Transaction-like operations

## Installation

```bash
pip install mongodb-rest
```

### Dependencies

- Python 3.8+
- Django 3.2+
- Django REST Framework 3.12+
- PyMongo 4.0+
- python-dateutil 2.8+

## Quick Start

### 1. Configure Django Settings

```python
# settings.py
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'rest_framework',
    'mongodb',  # Add this
    # your apps
]

# MongoDB Configuration
MONGODB_SETTINGS = {
    'db': 'your_database_name',
    'host': 'localhost',
    'port': 27017,
    'username': 'your_username',  # optional
    'password': 'your_password',  # optional
}
```

### 2. Connect to MongoDB

```python
from mongodb import connect

# Basic connection
connect('my_database')

# Advanced connection
connect(
    db='my_database',
    host='localhost',
    port=27017,
    username='user',
    password='password',
    authentication_source='admin'
)
```

### 3. Define a Document

```python
from mongodb import Document
from mongodb.fields import StringField, IntField, EmailField, DateTimeField

class User(Document):
    name = StringField(required=True, max_length=100)
    email = EmailField(required=True)
    age = IntField(min_value=0, max_value=150)
    created_at = DateTimeField(auto_now_add=True)
    
    meta = {
        'collection': 'users',
        'indexes': ['email']
    }
```

### 4. Use the Document

```python
# Create a user
user = User(name="John Doe", email="john@example.com", age=30)
user.save()

# Query users
users = User.objects.all()
john = User.objects.filter(name="John Doe").first()
adults = User.objects.filter(age__gte=18)
```

## Connection Management

### Basic Connection

```python
from mongodb import connect, disconnect

# Connect to default database
connect('my_database')

# Disconnect
disconnect()
```

### Multiple Connections

```python
from mongodb import connect, disconnect

# Primary database
connect('main_db', alias='default')

# Analytics database
connect('analytics_db', alias='analytics')

# Use specific connection
class User(Document):
    name = StringField()
    
    meta = {
        'db_alias': 'analytics'
    }
```

### Connection Options

```python
connect(
    db='my_database',
    host='localhost',
    port=27017,
    username='user',
    password='password',
    authentication_source='admin',
    authentication_mechanism='SCRAM-SHA-1',
    read_preference='primary',
    # PyMongo options
    maxPoolSize=100,
    minPoolSize=10,
    maxIdleTimeMS=30000,
    serverSelectionTimeoutMS=5000,
)
```

### Connection URI

```python
# MongoDB URI format
connect('mongodb://user:password@localhost:27017/database')
```

## Document Models

### Basic Document Definition

```python
from mongodb import Document
from mongodb.fields import *

class BlogPost(Document):
    title = StringField(required=True, max_length=200)
    content = StringField()
    author = ReferenceField('User')
    published = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    
    meta = {
        'collection': 'blog_posts',
        'indexes': [
            'title',
            'author',
            ('created_at', -1),  # Descending index
            [('author', 1), ('created_at', -1)]  # Compound index
        ],
        'ordering': ['-created_at']
    }
```

### Meta Options

```python
class MyDocument(Document):
    # fields...
    
    meta = {
        'collection': 'custom_collection_name',  # Collection name
        'db_alias': 'secondary',                 # Database alias
        'indexes': ['field1', 'field2'],         # Indexes to create
        'ordering': ['-created_at'],             # Default ordering
        'max_documents': 1000,                   # Capped collection
        'max_size': 5000000,                     # Capped collection size
        'allow_inheritance': True,               # Enable inheritance
        'abstract': False,                       # Abstract document
    }
```

### Document Inheritance

```python
class BaseDocument(Document):
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    
    meta = {
        'abstract': True,  # This won't create a collection
        'allow_inheritance': True
    }

class User(BaseDocument):
    name = StringField(required=True)
    email = EmailField(required=True)

class Product(BaseDocument):
    name = StringField(required=True)
    price = DecimalField(min_value=0)
```

## Field Types

### String Fields

```python
class MyDocument(Document):
    # Basic string field
    name = StringField(required=True, max_length=100)
    
    # String with choices
    status = StringField(choices=['active', 'inactive', 'pending'])
    
    # String with regex validation
    code = StringField(regex=r'^[A-Z]{3}\d{3}$')
    
    # Email field (validates email format)
    email = EmailField(required=True)
    
    # URL field
    website = URLField()
```

### Numeric Fields

```python
class Product(Document):
    # Integer field
    quantity = IntField(min_value=0, max_value=1000)
    
    # Float field
    rating = FloatField(min_value=0.0, max_value=5.0)
    
    # Decimal field (for precise calculations)
    price = DecimalField(min_value=0, max_digits=10, decimal_places=2)
    
    # Long field (for large integers)
    views = LongField(default=0)
```

### Date and Time Fields

```python
class Event(Document):
    # DateTime field
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    
    # Date field (date only)
    event_date = DateField()
    
    # Custom datetime
    scheduled_at = DateTimeField(default=datetime.now)
```

### Boolean and Binary Fields

```python
class User(Document):
    # Boolean field
    is_active = BooleanField(default=True)
    is_verified = BooleanField(default=False)
    
    # Binary field (for file data)
    avatar = BinaryField()
```

### Complex Fields

```python
class BlogPost(Document):
    title = StringField(required=True)
    
    # List field
    tags = ListField(StringField(max_length=50))
    categories = ListField(ReferenceField('Category'))
    
    # Dictionary field
    metadata = DictField()
    settings = DictField(default=lambda: {'public': True})
    
    # Embedded document
    author_info = EmbeddedDocumentField('AuthorInfo')
    
    # Reference to another document
    author = ReferenceField('User', reverse_delete_rule=CASCADE)
    
    # Generic reference (can reference any document type)
    related_object = GenericReferenceField()
```

### Embedded Documents

```python
class Address(EmbeddedDocument):
    street = StringField(required=True)
    city = StringField(required=True)
    country = StringField(required=True)
    postal_code = StringField()

class User(Document):
    name = StringField(required=True)
    email = EmailField(required=True)
    
    # Single embedded document
    address = EmbeddedDocumentField(Address)
    
    # List of embedded documents
    addresses = ListField(EmbeddedDocumentField(Address))
```

### File Fields

```python
class Document(Document):
    title = StringField(required=True)
    
    # File field (stores file in GridFS)
    attachment = FileField()
    
    # Image field (with additional image-specific methods)
    thumbnail = ImageField(size=(100, 100, True))  # width, height, force
```

### Field Options

All fields support these common options:

```python
field = StringField(
    required=True,           # Field is required
    default='default_value', # Default value
    unique=True,            # Field must be unique
    choices=['a', 'b', 'c'], # Allowed values
    validation=my_validator, # Custom validation function
    help_text='Help text',   # Documentation
    verbose_name='Display Name', # Human-readable name
)
```

## QuerySet Operations

### Basic Queries

```python
# Get all documents
users = User.objects.all()

# Filter documents
active_users = User.objects.filter(is_active=True)
adults = User.objects.filter(age__gte=18)

# Get single document
user = User.objects.get(email='john@example.com')
user = User.objects.filter(name='John').first()

# Check existence
exists = User.objects.filter(email='john@example.com').exists()

# Count documents
count = User.objects.filter(is_active=True).count()
```

### Query Operators

```python
# Comparison operators
User.objects.filter(age__gt=18)        # Greater than
User.objects.filter(age__gte=18)       # Greater than or equal
User.objects.filter(age__lt=65)        # Less than
User.objects.filter(age__lte=65)       # Less than or equal
User.objects.filter(age__ne=25)        # Not equal

# String operators
User.objects.filter(name__contains='John')      # Contains substring
User.objects.filter(name__icontains='john')     # Case-insensitive contains
User.objects.filter(name__startswith='J')       # Starts with
User.objects.filter(name__endswith='son')       # Ends with
User.objects.filter(name__regex=r'^J.*n$')      # Regex match

# List operators
User.objects.filter(tags__in=['python', 'django'])  # In list
User.objects.filter(tags__nin=['spam'])             # Not in list
User.objects.filter(tags__all=['python', 'web'])    # Contains all
User.objects.filter(tags__size=3)                   # List size

# Existence operators
User.objects.filter(phone__exists=True)   # Field exists
User.objects.filter(phone__exists=False)  # Field doesn't exist

# Type operators
User.objects.filter(age__type=int)        # Field type check
```

### Complex Queries

```python
from mongodb.queryset import Q

# OR queries
users = User.objects.filter(Q(age__lt=18) | Q(age__gt=65))

# AND queries (default behavior)
users = User.objects.filter(Q(is_active=True) & Q(age__gte=18))

# NOT queries
users = User.objects.filter(~Q(is_active=False))

# Complex combinations
users = User.objects.filter(
    (Q(age__gte=18) & Q(age__lte=65)) | Q(is_premium=True)
)
```

### Ordering and Limiting

```python
# Order by field
users = User.objects.order_by('name')           # Ascending
users = User.objects.order_by('-created_at')    # Descending
users = User.objects.order_by('age', '-name')   # Multiple fields

# Limit results
users = User.objects.limit(10)                  # First 10
users = User.objects.skip(20).limit(10)         # Skip 20, take 10

# Slicing (Pythonic way)
users = User.objects.all()[:10]                 # First 10
users = User.objects.all()[20:30]               # Skip 20, take 10
```

### Field Selection

```python
# Only specific fields
users = User.objects.only('name', 'email')

# Exclude specific fields
users = User.objects.exclude('password', 'secret_key')

# Reset field selection
users = User.objects.only('name').all_fields()
```

### Aggregation

```python
from mongodb.queryset import Sum, Avg, Min, Max, Count

# Simple aggregation
total_age = User.objects.aggregate(Sum('age'))
avg_age = User.objects.aggregate(Avg('age'))
min_age = User.objects.aggregate(Min('age'))
max_age = User.objects.aggregate(Max('age'))
user_count = User.objects.aggregate(Count('id'))

# Multiple aggregations
stats = User.objects.aggregate(
    total_users=Count('id'),
    avg_age=Avg('age'),
    min_age=Min('age'),
    max_age=Max('age')
)

# Aggregation with grouping
age_groups = User.objects.aggregate([
    {'$group': {
        '_id': '$age_group',
        'count': {'$sum': 1},
        'avg_age': {'$avg': '$age'}
    }}
])
```

### Raw Queries

```python
# Raw MongoDB query
users = User.objects.raw({'age': {'$gte': 18}})

# Raw aggregation pipeline
pipeline = [
    {'$match': {'is_active': True}},
    {'$group': {'_id': '$department', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}}
]
results = User.objects.aggregate(pipeline)
```

## Django REST Framework Integration

### Basic Serializers

```python
from mongodb.rest_framework.serializers import DocumentSerializer
from rest_framework import serializers

class UserSerializer(DocumentSerializer):
    class Meta:
        model = User
        fields = '__all__'

# Custom serializer
class UserSerializer(DocumentSerializer):
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'full_name']
        read_only_fields = ['id', 'created_at']
    
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"
```

### ViewSets

```python
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    
    def get_queryset(self):
        return User.objects.filter(is_active=True)
    
    @action(detail=True, methods=['post'])
    def set_password(self, request, pk=None):
        user = self.get_object()
        password = request.data.get('password')
        user.set_password(password)
        user.save()
        return Response({'status': 'password set'})
    
    @action(detail=False)
    def active_users(self, request):
        active_users = User.objects.filter(is_active=True)
        serializer = self.get_serializer(active_users, many=True)
        return Response(serializer.data)
```

### Nested Serializers

```python
class AddressSerializer(DocumentSerializer):
    class Meta:
        model = Address
        fields = '__all__'

class UserSerializer(DocumentSerializer):
    address = AddressSerializer()
    addresses = AddressSerializer(many=True)
    
    class Meta:
        model = User
        fields = ['name', 'email', 'address', 'addresses']
    
    def create(self, validated_data):
        address_data = validated_data.pop('address')
        addresses_data = validated_data.pop('addresses', [])
        
        user = User(**validated_data)
        user.address = Address(**address_data)
        user.addresses = [Address(**addr) for addr in addresses_data]
        user.save()
        return user
```

### Custom Fields

```python
from mongodb.rest_framework.fields import ObjectIdField

class UserSerializer(DocumentSerializer):
    id = ObjectIdField(read_only=True)
    author_id = ObjectIdField(source='author.id', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'author_id']
```

### Validation

```python
class UserSerializer(DocumentSerializer):
    class Meta:
        model = User
        fields = '__all__'
    
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already exists")
        return value
    
    def validate(self, data):
        if data['age'] < 18 and data['is_premium']:
            raise serializers.ValidationError(
                "Premium accounts require age 18+"
            )
        return data
```

## Advanced Features

### Signals

```python
from mongodb.signals import pre_save, post_save, pre_delete, post_delete

@pre_save.connect
def update_timestamp(sender, document, **kwargs):
    if hasattr(document, 'updated_at'):
        document.updated_at = datetime.now()

@post_save.connect
def send_welcome_email(sender, document, created, **kwargs):
    if created and isinstance(document, User):
        send_email(document.email, 'Welcome!')

@pre_delete.connect
def cleanup_references(sender, document, **kwargs):
    if isinstance(document, User):
        # Clean up related documents
        BlogPost.objects.filter(author=document).delete()
```

### Custom Validation

```python
def validate_phone(value):
    if not re.match(r'^\+?1?\d{9,15}$', value):
        raise ValidationError('Invalid phone number format')

class User(Document):
    name = StringField(required=True)
    phone = StringField(validation=validate_phone)
    
    def clean(self):
        # Document-level validation
        if self.age < 13 and not self.parent_email:
            raise ValidationError('Users under 13 must have parent email')
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
```

### Context Managers

```python
from mongodb.context_managers import switch_db, switch_collection

# Switch database temporarily
with switch_db(User, 'backup_db'):
    backup_users = User.objects.all()

# Switch collection temporarily
with switch_collection(User, 'archived_users'):
    archived = User.objects.all()

# Atomic operations (transaction-like)
from mongodb.context_managers import atomic

with atomic():
    user = User(name='John', email='john@example.com')
    user.save()
    
    profile = UserProfile(user=user, bio='Developer')
    profile.save()
    
    # If any operation fails, all are rolled back
```

### Indexing

```python
class User(Document):
    name = StringField()
    email = EmailField()
    location = PointField()  # GeoJSON point
    
    meta = {
        'indexes': [
            'email',                           # Simple index
            ('name', 1),                       # Ascending index
            ('created_at', -1),                # Descending index
            [('name', 1), ('email', 1)],       # Compound index
            ('location', '2dsphere'),          # Geospatial index
            {
                'fields': ['email'],
                'unique': True,
                'sparse': True,
                'background': True
            }
        ]
    }

# Create indexes manually
User.create_index('email', unique=True)
User.create_index([('name', 1), ('age', -1)])
```

### GridFS File Handling

```python
class Document(Document):
    title = StringField(required=True)
    file = FileField()

# Save file
doc = Document(title='My Document')
with open('document.pdf', 'rb') as f:
    doc.file.put(f, content_type='application/pdf', filename='document.pdf')
doc.save()

# Read file
with doc.file as f:
    content = f.read()

# File metadata
print(doc.file.filename)
print(doc.file.content_type)
print(doc.file.length)
```

### Geospatial Queries

```python
class Location(Document):
    name = StringField()
    coordinates = PointField()  # [longitude, latitude]

# Create location
location = Location(
    name='New York',
    coordinates=[40.7128, -74.0060]
)
location.save()

# Geospatial queries
nearby = Location.objects.filter(
    coordinates__near=[40.7589, -73.9851],  # Near coordinates
    coordinates__max_distance=1000          # Within 1000 meters
)

within_area = Location.objects.filter(
    coordinates__within_box=[
        [40.7128, -74.0060],  # Southwest corner
        [40.7829, -73.9441]   # Northeast corner
    ]
)
```

## Error Handling

### Common Exceptions

```python
from mongodb.errors import (
    ValidationError,
    DoesNotExist,
    MultipleObjectsReturned,
    ConnectionFailure,
    OperationError
)

try:
    user = User.objects.get(email='nonexistent@example.com')
except User.DoesNotExist:
    print("User not found")

try:
    user = User.objects.get(name='John')  # Multiple Johns exist
except User.MultipleObjectsReturned:
    print("Multiple users found")

try:
    user = User(name='', email='invalid-email')
    user.save()
except ValidationError as e:
    print(f"Validation failed: {e}")

try:
    connect('nonexistent_db')
except ConnectionFailure as e:
    print(f"Connection failed: {e}")
```

### Custom Error Handling

```python
class UserManager:
    @staticmethod
    def get_user_safely(email):
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            return User.objects.filter(email=email).first()

# Usage
user = UserManager.get_user_safely('john@example.com')
if user:
    print(f"Found user: {user.name}")
else:
    print("User not found")
```

## Best Practices

### 1. Connection Management

```python
# Use connection pooling
connect(
    'my_database',
    maxPoolSize=100,
    minPoolSize=10,
    maxIdleTimeMS=30000
)

# Use multiple connections for different purposes
connect('main_db', alias='default')
connect('analytics_db', alias='analytics')
connect('cache_db', alias='cache')
```

### 2. Document Design

```python
# Good: Embedded documents for related data
class User(Document):
    name = StringField(required=True)
    profile = EmbeddedDocumentField(UserProfile)

# Good: References for independent entities
class BlogPost(Document):
    title = StringField(required=True)
    author = ReferenceField(User)

# Avoid: Deep nesting
# Bad: profile.address.country.region.city
```

### 3. Indexing Strategy

```python
class User(Document):
    email = EmailField(required=True)
    name = StringField()
    created_at = DateTimeField(auto_now_add=True)
    
    meta = {
        'indexes': [
            'email',                    # For login queries
            '-created_at',              # For recent users
            [('name', 1), ('email', 1)] # For search queries
        ]
    }
```

### 4. Query Optimization

```python
# Good: Use only() for large documents
users = User.objects.only('name', 'email')

# Good: Use select_related for references
posts = BlogPost.objects.select_related('author')

# Good: Use pagination for large datasets
page = User.objects.skip(offset).limit(page_size)

# Avoid: Loading all documents
# Bad: all_users = User.objects.all()
```

### 5. Validation

```python
class User(Document):
    email = EmailField(required=True)
    age = IntField(min_value=0, max_value=150)
    
    def clean(self):
        # Custom validation
        if User.objects.filter(email=self.email).exclude(id=self.id).exists():
            raise ValidationError('Email already exists')
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
```

## API Reference

### Connection Functions

```python
connect(db, alias='default', host='localhost', port=27017, **kwargs)
disconnect(alias='default')
disconnect_all()
get_connection(alias='default')
get_db(alias='default')
```

### Document Methods

```python
# Instance methods
document.save(force_insert=False, validate=True)
document.delete()
document.reload()
document.clean()
document.to_dict()
document.to_json()

# Class methods
Document.objects.all()
Document.objects.filter(**kwargs)
Document.objects.get(**kwargs)
Document.objects.create(**kwargs)
Document.objects.update(**kwargs)
Document.objects.delete()
Document.create_index(keys, **kwargs)
Document.drop_collection()
```

### QuerySet Methods

```python
queryset.all()
queryset.filter(**kwargs)
queryset.exclude(**kwargs)
queryset.get(**kwargs)
queryset.first()
queryset.last()
queryset.count()
queryset.exists()
queryset.order_by(*fields)
queryset.limit(n)
queryset.skip(n)
queryset.only(*fields)
queryset.exclude(*fields)
queryset.select_related(*fields)
queryset.aggregate(*pipeline)
queryset.raw(raw_query)
```

### Field Types Reference

```python
# String fields
StringField(max_length=None, min_length=None, regex=None, choices=None)
EmailField()
URLField()

# Numeric fields
IntField(min_value=None, max_value=None)
FloatField(min_value=None, max_value=None)
DecimalField(min_value=None, max_value=None, max_digits=None, decimal_places=None)
LongField(min_value=None, max_value=None)

# Date/time fields
DateTimeField(auto_now=False, auto_now_add=False)
DateField()

# Other fields
BooleanField(default=None)
BinaryField()
ObjectIdField()
UUIDField()

# Complex fields
ListField(field)
DictField()
EmbeddedDocumentField(document_type)
ReferenceField(document_type, reverse_delete_rule=DO_NOTHING)
GenericReferenceField()
FileField()
ImageField(size=None)
PointField()  # GeoJSON point
```

This documentation covers all the major features and capabilities of your MongoDB Django REST library. Each section includes practical examples and best practices to help users effectively utilize the library in their projects.