# MongoDB REST Library - Usage Examples

## Installation

```bash
pip install mongodb-rest
```

## Basic Usage

### 1. Connecting to MongoDB

```python
from mongodb import connect, disconnect

# Connect to a MongoDB database
connect('my_database')

# Connect with custom settings
connect(
    db='my_database',
    host='localhost',
    port=27017,
    username='user',
    password='password'
)

# Disconnect when done
disconnect()
```

### 2. Defining Documents

```python
from mongodb import Document
from mongodb.fields import StringField, IntField, EmailField, DateTimeField

class User(Document):
    name = StringField(required=True, max_length=100)
    email = EmailField(required=True)
    age = IntField(min_value=0, max_value=150)
    created_at = DateTimeField()
    
    meta = {
        'collection': 'users',
        'indexes': ['email']
    }

class BlogPost(Document):
    title = StringField(required=True, max_length=200)
    content = StringField()
    author = ReferenceField(User)
    published_at = DateTimeField()
    tags = ListField(StringField(max_length=50))
    
    meta = {
        'collection': 'blog_posts'
    }
```

### 3. CRUD Operations

```python
# Create a new user
user = User(
    name="John Doe",
    email="john@example.com",
    age=30
)
user.save()

# Find users
users = User.objects.all()
john = User.objects.filter(name="John Doe").first()
adults = User.objects.filter(age__gte=18)

# Update a user
john.age = 31
john.save()

# Delete a user
john.delete()
```

### 4. Django REST Framework Integration

```python
from mongodb.rest_framework.serializers import DocumentSerializer
from rest_framework import viewsets
from rest_framework.response import Response

class UserSerializer(DocumentSerializer):
    class Meta:
        model = User
        fields = '__all__'

class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    
    def get_queryset(self):
        return User.objects.all()
    
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
```

### 5. Advanced Querying

```python
# Complex queries
recent_posts = BlogPost.objects.filter(
    published_at__gte=datetime.now() - timedelta(days=7)
).order_by('-published_at')

# Aggregation
from mongodb.queryset import Q

popular_authors = User.objects.filter(
    Q(blogpost__published_at__gte=datetime.now() - timedelta(days=30)) &
    Q(blogpost__tags__in=['python', 'django'])
).distinct()

# Pagination
page_1 = BlogPost.objects.all()[:10]  # First 10 posts
page_2 = BlogPost.objects.all()[10:20]  # Next 10 posts
```

### 6. Field Types

```python
from mongodb.fields import *

class Product(Document):
    name = StringField(required=True)
    price = DecimalField(min_value=0)
    description = StringField()
    category = ReferenceField('Category')
    tags = ListField(StringField())
    metadata = DictField()
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

### 7. Custom Validation

```python
from mongodb.errors import ValidationError

class User(Document):
    username = StringField(required=True)
    email = EmailField(required=True)
    
    def clean(self):
        # Custom validation
        if User.objects.filter(email=self.email).count() > 0:
            raise ValidationError('Email already exists')
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
```

### 8. Signals and Hooks

```python
from mongodb.signals import pre_save, post_save

@pre_save.connect
def update_timestamp(sender, document, **kwargs):
    if hasattr(document, 'updated_at'):
        document.updated_at = datetime.now()

@post_save.connect
def send_welcome_email(sender, document, created, **kwargs):
    if created and isinstance(document, User):
        # Send welcome email
        send_email(document.email, 'Welcome!')
```

## Django Integration

### settings.py
```python
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

### urls.py
```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('api/', include(router.urls)),
]
```

## Error Handling

```python
from mongodb.errors import ValidationError, ConnectionFailure

try:
    user = User(name="", email="invalid-email")
    user.save()
except ValidationError as e:
    print(f"Validation error: {e}")
except ConnectionFailure as e:
    print(f"Database connection error: {e}")
```

## Best Practices

1. **Always validate data** before saving
2. **Use indexes** for frequently queried fields
3. **Handle connection failures** gracefully
4. **Use transactions** for multi-document operations
5. **Monitor performance** with query optimization
6. **Implement proper error handling**
7. **Use connection pooling** for production

## Performance Tips

```python
# Use select_related for referenced documents
posts_with_authors = BlogPost.objects.select_related('author')

# Use only() to limit fields
user_names = User.objects.only('name', 'email')

# Use batch operations for bulk updates
User.objects.filter(age__lt=18).update(is_minor=True)

# Use aggregation for complex calculations
from mongodb.aggregation import Sum, Avg
stats = User.objects.aggregate(
    total_users=Count('id'),
    avg_age=Avg('age')
)
```

This library provides a powerful and intuitive way to work with MongoDB in Django applications while maintaining the familiar Django ORM-like interface!