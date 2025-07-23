# MongoDB REST Library - Publishing Guide

## Overview
Your MongoDB REST library is now ready for publication to PyPI! This guide will walk you through the publishing process.

## Package Information
- **Package Name**: `mongodb-rest`
- **Version**: 0.1.0
- **Description**: A MongoDB library with Django REST framework integration
- **Author**: Abhijit Dey <abhideybnk@gmail.com>

## Prerequisites

### 1. Create PyPI Accounts
You'll need accounts on both:
- **Test PyPI**: https://test.pypi.org/account/register/
- **Production PyPI**: https://pypi.org/account/register/

### 2. Generate API Tokens
For security, use API tokens instead of passwords:

#### Test PyPI Token:
1. Go to https://test.pypi.org/manage/account/
2. Scroll to "API tokens" section
3. Click "Add API token"
4. Name: "mongodb-rest-test"
5. Scope: "Entire account" (or specific to your project)
6. Copy the token (starts with `pypi-`)

#### Production PyPI Token:
1. Go to https://pypi.org/manage/account/
2. Follow same steps as above
3. Name: "mongodb-rest-prod"

### 3. Configure Twine
Create a `.pypirc` file in your home directory:

```bash
# Create the file
touch ~/.pypirc
chmod 600 ~/.pypirc
```

Add this content to `~/.pypirc`:
```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR_PRODUCTION_TOKEN_HERE

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-YOUR_TEST_TOKEN_HERE
```

## Publishing Steps

### Step 1: Test on Test PyPI (Recommended)
```bash
# Activate virtual environment
source test_env/bin/activate

# Upload to Test PyPI
twine upload --repository testpypi dist/*
```

### Step 2: Test Installation from Test PyPI
```bash
# Create a new test environment
python3 -m venv test_install_env
source test_install_env/bin/activate

# Install from Test PyPI
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ mongodb-rest

# Test the installation
python -c "from mongodb.connection import connect; print('Package works!')"
```

### Step 3: Publish to Production PyPI
```bash
# Upload to production PyPI
twine upload dist/*
```

### Step 4: Verify Production Installation
```bash
# Install from production PyPI
pip install mongodb-rest

# Test the installation
python -c "from mongodb.connection import connect; print('Production package works!')"
```

## Alternative Publishing Methods

### Using Environment Variables
Instead of `.pypirc`, you can use environment variables:

```bash
# For Test PyPI
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-YOUR_TEST_TOKEN_HERE
export TWINE_REPOSITORY_URL=https://test.pypi.org/legacy/
twine upload dist/*

# For Production PyPI
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-YOUR_PRODUCTION_TOKEN_HERE
unset TWINE_REPOSITORY_URL
twine upload dist/*
```

### Interactive Upload
If you prefer to enter credentials interactively:
```bash
twine upload --repository testpypi dist/*
# You'll be prompted for username and password
```

## Post-Publication

### Update Package Information
After publishing, consider updating:
1. **GitHub Repository**: Update URLs in `pyproject.toml`
2. **Documentation**: Add installation instructions
3. **Version Control**: Tag the release

### Monitor Your Package
- Check your package page: https://pypi.org/project/mongodb-rest/
- Monitor download statistics
- Watch for issues and user feedback

## Updating Your Package

For future updates:
1. Update version in `pyproject.toml`
2. Rebuild the package: `python -m build`
3. Upload new version: `twine upload dist/*`

## Troubleshooting

### Common Issues:
1. **Package name already exists**: Choose a different name in `pyproject.toml`
2. **Version already exists**: Increment version number
3. **Authentication failed**: Check your API tokens
4. **File already exists**: Clear `dist/` folder and rebuild

### Getting Help:
- PyPI Help: https://pypi.org/help/
- Packaging Guide: https://packaging.python.org/
- Twine Documentation: https://twine.readthedocs.io/

## Security Notes
- Never commit API tokens to version control
- Use API tokens instead of passwords
- Regularly rotate your tokens
- Use project-scoped tokens when possible

## Success!
Once published, users can install your package with:
```bash
pip install mongodb-rest
```

And use it in their projects:
```python
from mongodb import connect, Document, DocumentSerializer

# Connect to MongoDB
connect('your-database-name')

# Use your library!
```