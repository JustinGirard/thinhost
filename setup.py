# setup.py
from setuptools import setup, find_packages

# read requirements.txt for convenience
#with open("requirements.txt") as f:
#    reqs = [
#        line.strip() for line in f
#        if line.strip() and not line.startswith("#")
#    ]
reqs = ""
setup(
    name="decelium_simple_host", 
    version="0.1.0",
    packages=find_packages(),
    install_requires=reqs,       # <-- this is what pip reads
    python_requires=">=3.7",
)
