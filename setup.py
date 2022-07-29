#!/usr/bin/env python
# encoding: utf-8

from setuptools import setup
import re
import os
import io
from configparser import ConfigParser

MODULE = 'account_bank'
PREFIX = 'trytonspain'
MODULE2PREFIX = {'account_payment_type': 'trytonspain', 'company_bank': 'trytonspain'}
OWNER = {
    'trytonspain': 'NaN-tic',
}


def read(fname):
    return io.open(
        os.path.join(os.path.dirname(__file__), fname),
        'r', encoding='utf-8').read()


def get_require_version(name):
    if minor_version % 2:
        require = '%s >= %s.%s.dev0, < %s.%s'
    else:
        require = '%s >= %s.%s, < %s.%s'
    require %= (name, major_version, minor_version,
        major_version, minor_version + 1)
    return require

def get_requires(depends='depends'):
  requires = []
  for dep in info.get(depends, []):
      if not re.match(r'(ir|res)(\W|$)', dep):
          prefix = MODULE2PREFIX.get(dep, 'trytond')
          owner = OWNER.get(prefix, prefix)
          if prefix == 'trytond':
              requires.append(get_require_version('%s_%s' % (prefix, dep)))
          else:
              requires.append(
                  '%(prefix)s-%(dep)s@git+https://github.com/%(owner)s/'
                  'trytond-%(dep)s.git@%(branch)s'
                  '#egg=%(prefix)s-%(dep)s-%(series)s'%{
                          'prefix': prefix,
                          'owner': owner,
                          'dep':dep,
                          'branch': branch,
                          'series': series,})

  return requires

config = ConfigParser()
config.readfp(open('tryton.cfg'))
info = dict(config.items('tryton'))
for key in ('depends', 'extras_depend', 'xml'):
    if key in info:
        info[key] = info[key].strip().splitlines()

version = info.get('version', '0.0.1')
major_version, minor_version, _ = version.split('.', 2)
major_version = int(major_version)
minor_version = int(minor_version)

requires = []

series = '%s.%s' % (major_version, minor_version)
if minor_version % 2:
    branch = 'master'
else:
    branch = series

requires += get_requires('depends')

tests_require = [
    get_require_version('proteus'),

    ]
tests_require += get_requires('extras_depend')
requires += [get_require_version('trytond_account'),get_require_version('trytond_account_invoice'),get_require_version('trytond_account_payment')]

dependency_links = []

if minor_version % 2:
    # Add development index for testing with proteus
    dependency_links.append('https://trydevpi.tryton.org/')

setup(name='%s_%s' % (PREFIX, MODULE),
    version=version,
    description='',
    long_description=read('README'),
    author='trytonspain',
    url='http://www.nan-tic.com/',
    download_url='https://github.com:trytonspain/trytond-account_bank',
    package_dir={'trytond.modules.%s' % MODULE: '.'},
    packages=[
        'trytond.modules.%s' % MODULE,
        'trytond.modules.%s.tests' % MODULE,
        ],
    package_data={
        'trytond.modules.%s' % MODULE: (info.get('xml', [])
            + ['tryton.cfg', 'locale/*.po', 'tests/*.rst', 'view/*.xml',
            'icons/*.svg']),
        },
    project_urls = {
       "Source Code": 'https://github.com:trytonspain/trytond-account_bank'
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Plugins',
        'Framework :: Tryton',
        'Intended Audience :: Developers',
        'Intended Audience :: Financial and Insurance Industry',
        'Intended Audience :: Legal Industry',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Natural Language :: Catalan',
        'Natural Language :: English',
        'Natural Language :: Spanish',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Office/Business',
        ],
    license='GPL-3',
    install_requires=requires,
    dependency_links=dependency_links,
    zip_safe=False,
    entry_points="""
    [trytond.modules]
    %s = trytond.modules.%s
    """ % (MODULE, MODULE),
    test_suite='tests',
    test_loader='trytond.test_loader:Loader',
    tests_require=tests_require,

    )