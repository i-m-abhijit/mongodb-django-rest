# MongoDB Django REST Library

A comprehensive MongoDB integration library for Django applications with full Django REST framework support. Provides an ORM-like interface similar to Django's built-in ORM but designed specifically for MongoDB.

[![Test PyPI version](https://img.shields.io/badge/Test%20PyPI-v0.1.1-blue)](https://test.pypi.org/project/mongodb-rest/)
[![Python versions](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🚀 Key Features

- **MongoDB Connection Management**: Multiple database connections with aliases
- **Document-Based Models**: Define MongoDB documents similar to Django models
- **Rich Field Types**: 20+ field types including geospatial, file, and embedded documents
- **QuerySet API**: Django-like querying interface with 15+ operators
- **REST Framework Integration**: Seamless serialization for APIs
- **Advanced Querying**: Aggregation, raw queries, and complex filtering
- **Validation System**: Built-in and custom data validation
- **Indexing Support**: Database indexing configuration
- **Signal System**: Pre/post save hooks
- **Context Managers**: Transaction-like operations

## 📦 Installation

```bash
pip install mongodb-rest
```

### Dependencies

- Python 3.8+
- Django 3.2+
- Django REST Framework 3.12+
- PyMongo 4.0+
- python-dateutil 2.8+

## 🚀 Quick Start

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
    password='password'
)
```

### 3. Define Documents

```python
from mongodb import Document
from mongodb.fields import StringField, IntField, EmailField, DateTimeField, ListField

class User(Document):
    name = StringField(required=True, max_length=100)
    email = EmailField(required=True)
    age = IntField(min_value=0, max_value=150)
    tags = ListField(StringField(max_length=50))
    created_at = DateTimeField(auto_now_add=True)

    meta = {
        'collection': 'users',
        'indexes': ['email', '-created_at']
    }

class BlogPost(Document):
    title = StringField(required=True, max_length=200)
    content = StringField()
    author = ReferenceField(User)
    published_at = DateTimeField()

    meta = {
        'collection': 'blog_posts',
        'ordering': ['-published_at']
    }
```

### 4. CRUD Operations

```python
# Create
user = User(name="John Doe", email="john@example.com", age=30)
user.save()

# Query
users = User.objects.all()
john = User.objects.filter(name="John Doe").first()
adults = User.objects.filter(age__gte=18)
recent_users = User.objects.filter(created_at__gte=datetime.now() - timedelta(days=7))

# Update
john.age = 31
john.save()

# Delete
john.delete()
```

### 5. Advanced Querying

```python
from mongodb.queryset import Q

# Complex queries
users = User.objects.filter(
    Q(age__gte=18) & Q(age__lte=65) | Q(is_premium=True)
)

# Aggregation
from mongodb.queryset import Sum, Avg, Count
stats = User.objects.aggregate(
    total_users=Count('id'),
    avg_age=Avg('age')
)

# Geospatial queries (if using PointField)
nearby_locations = Location.objects.filter(
    coordinates__near=[40.7128, -74.0060],
    coordinates__max_distance=1000
)
```

## 🔧 Field Types

The library supports 20+ field types:

```python
class Product(Document):
    # String fields
    name = StringField(required=True, max_length=100)
    email = EmailField()
    website = URLField()

    # Numeric fields
    price = DecimalField(min_value=0, max_digits=10, decimal_places=2)
    quantity = IntField(min_value=0)
    rating = FloatField(min_value=0.0, max_value=5.0)

    # Date/time fields
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    launch_date = DateField()

    # Complex fields
    tags = ListField(StringField(max_length=50))
    metadata = DictField()
    specifications = EmbeddedDocumentField('ProductSpecs')
    category = ReferenceField('Category')

    # File fields
    image = ImageField()
    manual = FileField()

    # Geospatial
    location = PointField()  # [longitude, latitude]

    # Other
    is_active = BooleanField(default=True)
    binary_data = BinaryField()
```

## 🌐 Django REST Framework Integration

```python
from mongodb.rest_framework.serializers import DocumentSerializer
from rest_framework import viewsets

class UserSerializer(DocumentSerializer):
    class Meta:
        model = User
        fields = '__all__'

class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        return User.objects.filter(is_active=True)

    @action(detail=False)
    def recent_users(self, request):
        recent = User.objects.filter(
            created_at__gte=datetime.now() - timedelta(days=7)
        )
        serializer = self.get_serializer(recent, many=True)
        return Response(serializer.data)
```

## 🔍 Query Operators

Support for 15+ MongoDB query operators:

```python
# Comparison
User.objects.filter(age__gt=18)        # Greater than
User.objects.filter(age__gte=18)       # Greater than or equal
User.objects.filter(age__lt=65)        # Less than
User.objects.filter(age__lte=65)       # Less than or equal
User.objects.filter(age__ne=25)        # Not equal

# String operations
User.objects.filter(name__contains='John')      # Contains
User.objects.filter(name__icontains='john')     # Case-insensitive contains
User.objects.filter(name__startswith='J')       # Starts with
User.objects.filter(name__regex=r'^J.*n$')      # Regex match

# List operations
User.objects.filter(tags__in=['python', 'django'])  # In list
User.objects.filter(tags__all=['python', 'web'])    # Contains all
User.objects.filter(tags__size=3)                   # List size

# Existence
User.objects.filter(phone__exists=True)   # Field exists
```

## 🔗 Multiple Database Connections

```python
# Configure multiple databases
connect('main_db', alias='default')
connect('analytics_db', alias='analytics')
connect('cache_db', alias='cache')

# Use specific database
class AnalyticsData(Document):
    event_name = StringField()
    timestamp = DateTimeField()

    meta = {
        'db_alias': 'analytics'
    }
```

## 📊 Advanced Features

### Signals

```python
from mongodb.signals import pre_save, post_save

@pre_save.connect
def update_timestamp(sender, document, **kwargs):
    if hasattr(document, 'updated_at'):
        document.updated_at = datetime.now()

@post_save.connect
def send_notification(sender, document, created, **kwargs):
    if created and isinstance(document, User):
        send_welcome_email(document.email)
```

### Custom Validation

```python
def validate_phone(value):
    if not re.match(r'^\+?1?\d{9,15}$', value):
        raise ValidationError('Invalid phone number')

class User(Document):
    phone = StringField(validation=validate_phone)

    def clean(self):
        if self.age < 13 and not self.parent_email:
            raise ValidationError('Users under 13 need parent email')
```

### Context Managers

```python
from mongodb.context_managers import switch_db, atomic

# Switch database temporarily
with switch_db(User, 'backup_db'):
    backup_users = User.objects.all()

# Atomic operations
with atomic():
    user = User(name='John')
    user.save()
    profile = UserProfile(user=user)
    profile.save()
```

### Indexing

```python
class User(Document):
    email = EmailField()
    name = StringField()
    location = PointField()

    meta = {
        'indexes': [
            'email',                           # Simple index
            ('name', 1),                       # Ascending
            ('created_at', -1),                # Descending
            [('name', 1), ('email', 1)],       # Compound
            ('location', '2dsphere'),          # Geospatial
            {
                'fields': ['email'],
                'unique': True,
                'sparse': True
            }
        ]
    }
```

## 🛠️ Error Handling

```python
from mongodb.errors import (
    ValidationError,
    DoesNotExist,
    MultipleObjectsReturned,
    ConnectionFailure
)

try:
    user = User.objects.get(email='john@example.com')
except User.DoesNotExist:
    print("User not found")
except User.MultipleObjectsReturned:
    user = User.objects.filter(email='john@example.com').first()
except ValidationError as e:
    print(f"Validation failed: {e}")
```

## 📈 Performance Best Practices

```python
# Use field selection for large documents
users = User.objects.only('name', 'email')

# Use select_related for references
posts = BlogPost.objects.select_related('author')

# Pagination for large datasets
users = User.objects.skip(offset).limit(page_size)

# Indexing for frequently queried fields
class User(Document):
    email = EmailField()
    meta = {
        'indexes': ['email', '-created_at']
    }
```

## 📚 Documentation

For complete documentation with all features, examples, and API reference, visit:

- **GitHub Repository**: [https://github.com/i-m-abhijit/mongodb-django-rest](https://github.com/i-m-abhijit/mongodb-django-rest)
- **Full Documentation**: See `DOCUMENTATION.md` in the repository

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- **PyPI**: [https://pypi.org/project/mongodb-rest/](https://pypi.org/project/mongodb-rest/)
- **GitHub**: [https://github.com/i-m-abhijit/mongodb-django-rest](https://github.com/i-m-abhijit/mongodb-django-rest)
- **Issues**: [https://github.com/i-m-abhijit/mongodb-django-rest/issues](https://github.com/i-m-abhijit/mongodb-django-rest/issues)
