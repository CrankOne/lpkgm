About LPKGM
===========

LPKGM is "local (or lightweight) package manager". It provides some extent of
automatization to deploy software builds for HPC environment (mostly on file
shares). Comparing to `spack <https://spack.io/>`_ this package is much more
lightweight, straightforward (and, one has to admit, is deliberately made
rather rudimantary).

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

What it does:

- deliver and deploy CI/CD packages from GitHub, Gitlab, etc.
- relying on user-provided shell-scripts, build from sources and then deploy
  some packages in the userspace/custom location (by prefix installation).
- track on the installed versions and files, foreseeing some degree of
  runtime control by means
  of `Linux Environment Modules <https://modules.readthedocs.io/en/latest/modulefile.html>`_
  and thus providing abilities to work with different versions and bundles of
  package versions
- maintain dependency tree composed of multiple package versions within
  filesystem subtree.
- track changes of large amount of static files brought by some packages,
  providing de-duplication by means of soft and hard links.

What it does not (or not well-suited for):

- Cross-platform builds
- Binary-deterministic builds in isolated environments
  (for this kind of tool, see `Bob <https://bobbuildtool.dev/>`_)
- Does not maintain entire Linux distribution (LFS)
- Management of thousands of installed packages should be tedious due to
  absence of database.

General idea is to leverage management of some software ecosystem installed on
top of certain Linux distribution -- locally, or within HTC/HPC software
shares.

Example Scenario
================

Having few packages on different repositories a team would like to maintain
CI/CD pipeline which will:

- handle certain commits (in branch or tagged)
- build, test, deploy and uninstall packages on the network file share(s)
- labeled with certain version tag, provide access to multiple versions
  switching between them with Linux environment modules
- maintain packages with fairly large amount static assets (e.g. calibration
  data, databases, etc)

In cases when CMake is used, the package can be distributed
with `CPack <https://cmake.org/cmake/help/latest/module/CPack.html>`_. If it
is not enough, an installer extension module can be utilized (up to lowest
level of a shell script).

Reference document structure
============================

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
