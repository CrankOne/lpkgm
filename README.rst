About LPKGM
===========

LPKGM is "local (or lightweight) package manager". It provides some extent of
automatization to deploy software builds for HPC environment (mostly on file
shares). Comparing to `spack <https://spack.io/>`_ this script is much more
lightweight, straightforward (and rudimantary, the LPKGM's itself is
about two thousands lines of code).

Its primary purpose is to fetch and deploy packages produced by CI/CD
pipelines, keep track of continiously updated versions, facilitate fast and
transparent access to different versions of same package.

The logic of this scripts is very permissive (which is generally bad, but
here it is done on purpose):

- for CI/CD pipelines it relies on Git packages registry, assuming the
  package is already compatible with the environment.
- package version can be of arbitrary form, with some elaborated updates
  logic.
- for packages not provided by CI/CD it just forwards execution to shell
  scripts most of the time).

One might be interested in one of the follwoing use cases within this
document:

- if you are one of the Collaborators interested in just using or querying
  available packages. In this case see :ref:`Users Guidelines`.
- if you would like to have your package published on the NA64 CVMFS, see
  :ref:`Maintainer Guidelines`.
- if a disaster has happened and CERN is updating their default computing
  environemnt, see :ref:`Admin Guidelines`.

LPKGM was written by NA64 Collaboration (CERN) to maintain their software
environment on HPC network share (CVMFS).

.. _Users Guidelines:

User's Guidelines
=================

...

.. _Maintainer Guidelines:

Package Maintainer Guidelines
=============================

...

.. _Admin Guidelines:

Admin Guidelines
================

It is steered by command-line interface to ``lpkgm.py`` script, expecting one
of sub-commands (``install``, ``remove`` or ``show``) being provided with
subject *package name* and *package version*. See ``lpkgm.py -h`` for details
on its command line interface.
