from pathlib import Path
from setuptools import setup, find_packages

long_description = Path("README.md").read_text(encoding="utf-8")

setup(
    name="thinhost",
    version="0.2.0",
    description="Thin HTTP hosts for Decelium microsite workflows",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Justin Girard",
    author_email="justingirard@decelium.com",
    url="https://github.com/Decelium/thinhost",
    license="MIT",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
    ],
    packages=find_packages(),
    install_requires=[
        "nodejobs>=0.3.0",
        "flask",
        "flask-cors",
        "requests",
        "httpx",
        "psutil",
        "python-dotenv",
        "urllib3",
        "werkzeug",
    ],
    python_requires=">=3.7",
)
