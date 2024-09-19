import setuptools, re

"""
Local package manager.
"""

def find_version(fname):
    """
    Attempts to find the version number in the file names fname.
    Raises RuntimeError if not found.
    """
    version = ''
    with open(fname, 'r') as fp:
        reg = re.compile(r'__version__ = [\'"]([^\'"]*)[\'"]')
        for line in fp:
            m = reg.match(line)
            if m:
                version = m.group(1)
                break
    if not version:
        raise RuntimeError('Cannot find version information')
    return version

def get_requirements(fname):
    deps = []
    with open(fname, 'r') as f:
        deps = [ l for l in f if l and '#' != l[0] ]
    return list(deps)


d = {
        'name' : 'lpkgm',
        'version' : find_version('lpkgm/__init__.py'),
        'description' : 'Local lightweight package manager.',
        'author' : 'Renat R. Dusaev',
        'license' : 'MIT',
        'long_description' : __doc__,
        'author_email' : 'renat.dusaev@cern.ch',
        'packages' : ['lpkgm'],
        'install_requires' : get_requirements( 'requirements.txt' ),
        'entry_points' : {
            'console_scripts': [
                'lpkgm=lpkgm.lpkgm:main',
                'lpkgm-dir-diff=lpkgm.reduce_dir:main'
            ]
        },
    }

setuptools.setup(**d)

