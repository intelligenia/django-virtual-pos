# -*- coding: utf-8 -*-

# Copyright (c) 2015 by intelligenia <info@intelligenia.es>
#
# The MIT License (MIT)
#
# Copyright (c) 2016 intelligenia soluciones informáticas

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
from setuptools import setup, find_packages
from os import path

current_path = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(current_path, 'README.rst')) as f:
    long_description = f.read()

data_files = []
for dirpath, dirnames, filenames in os.walk('.'):
    for i, dirname in enumerate(dirnames):
        if dirname.startswith('.'):
            del dirnames[i]
    if '__init__.py' in filenames:
        continue
    elif filenames:
        data_files.append([dirpath, [os.path.join(dirpath, f) for f in filenames]])

setup(
    name="django-virtual-pos",
    version="1.6.8.3",
    install_requires=[
        "django",
        "beautifulsoup4",
        "lxml",
        "pycrypto",
        "pytz",
        "requests"
    ],
    author="intelligenia",
    author_email="mario@intelligenia.es",
    description="django-virtual-pos is a module that abstracts the flow of paying in several online payment platforms.",
    long_description=long_description,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Framework :: Django',
        'License :: OSI Approved :: MIT License',
    ],
    license="MIT",
    keywords=["virtual", "point-of-sale", "puchases", "online", "payments"],
    url='https://github.com/intelligenia/django-virtual-pos',
    packages=find_packages('.'),
    data_files=data_files,
    include_package_data=True,
)
