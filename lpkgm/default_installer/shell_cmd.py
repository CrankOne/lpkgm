"""
LPKGM installer extension module. 
"""

import os, copy, logging, tempfile, shutil, glob
from collections import defaultdict

from lpkgm.utils import execute_command
from lpkgm.settings import gSettings

def run( self, pkgName, pkgVer, cmd
       , files=None, cwd=None, assetFiles=None):
    """
    Runs shell command to install the package. Parameterised with command to
    run (as a list of shell tokens given in ``cmd``):

    1. Interpolates the struct with definitions in installer's formatting dict,
       expands environment variables in the ``cmd``
    2. if ``cwd`` (current working dir) is not given, creates a temporary
       directory
    3. Appends execution environment with LPKGM-specific environment variables:
        * ``_LPKGM_DEPENDENCIES`` -- colon-separated list of dependencies given
          in a form fitting to Linux environment modules
        * ``_LPKGM_TOKENS_DIR`` -- path to Git(hub/lab) project tokens
        * ``_LPKGM_PLATFORM`` -- build platform, if ``platform`` is given in
          the definitions dict, otherwise set to ``x86-64-linux-unknown``
        * ``MODULEPATH`` -- set from ``gSettings["modulepath"]``
        * ``_LPKGM_MODULESCRIPT`` -- set to ``self._modulescript`` if it is not
          ``None``.
    4. If first token in ``cmd`` is local file, copies it to the build dir and
       changes first token to be this copy
    5. Copies assets files (expanded and formatted paths) to cwd

    Meaning of ``files`` is the same as for installer.

    If ``cwd`` was not given, the (temp) dir will be removed on successful
    finishing, otherwise dir is kept for investigation.

    Note: assets files can be any of the package's local directories. After
    copying to cwd those paths will be reduced to ``$cwd/filename``.
    """
    L = logging.getLogger(__name__)
    if files is None: files = {}
    if not assetFiles: assetFiles = []
    # append (local copy of) formatting dict with version info
    fmtDct = copy.copy(self._fmtDict)
    fmtDct.update(pkgVer)
    # interpolate cmd, expand environment variables
    cmd_ = []
    for tok in cmd:
        tok_ = tok.format(**fmtDct)
        tok_ = os.path.expandvars(tok_)
        cmd_.append(tok_)
    # create current workind directory if need
    removeCwd = False
    if cwd is None:
        removeCwd = True
        # current working dir is not provided -- create temp
        cwd = tempfile.mkdtemp(prefix=gSettings.get('tmp-dir-prefix', None))
    if not os.path.isdir(cwd):
        os.mkdir(cwd)

    # append execution environment with dependencies list
    env = dict(os.environ)
    env['_LPKGM_DEPENDENCIES'] = ':'.join('/'.join([d['package'], d['version']['fullVersion']]) \
            for d in self._dependencies)
    env['_LPKGM_TOKENS_DIR'] = gSettings['gitlab-tokens-dir']
    env['_LPKGM_PLATFORM'] = fmtDct.get('platform', 'x86_64-linux-unknown')
    env['MODULEPATH'] = gSettings['modulepath']
    if self._modulescript:
        env['_LPKGM_MODULESCRIPT'] = self._modulescript
    else:
        L.warning('Note/warning: shell script is running without _LPKGM_MODULESCRIPT')

    if cwd:
        if os.path.isfile(cmd_[0]):
            # TODO: check that file is really "local" (i.e. not, say, /bin/bash)
            # this is a local script; we copy it to a tmp dir
            shutil.copy(cmd_[0], cwd)  # copy() keeps permissions and dest can be a dir
            cmd_[0] = './' + os.path.basename(cmd_[0])
        for assetFilePath_ in assetFiles:
            assetFilePath = os.path.normpath(os.path.expandvars(assetFilePath_.format(**fmtDct)))
            if not os.path.isfile(assetFilePath):
                raise RuntimeError(f'No such (asset) file: "{assetFilePath}"')
            shutil.copy(assetFilePath, cwd)
    try:
        execute_command(cmd_, cwd=cwd, env=env, joinStreams=True)
    except Exception as e:
        if cwd and removeCwd:
            L.warning(f'Directory {cwd} is kept for investigation.')
            removeCwd = False
        raise e from None

    selectedFiles = defaultdict(list)
    for fileDefName, filePatterns in files.items():
        for filePattern in filePatterns:
            #fg = glob.glob(filePattern.format(fmtDct), root_dir=cwd):
            # root_dir parameter appeared in Python>=3.10
            if filePattern.startswith('/'):
                fg = glob.glob(filePattern.format(fmtDct))
            else:
                fg = glob.glob(cwd + '/' + filePattern.format(fmtDct))
            for filePath in fg:
                fullPath = filePath if cwd is None else os.path.join(cwd, filePath)
                selectedFiles[fileDefName].append(fullPath)
        if not selectedFiles[fileDefName]:
            raise RuntimeError(f'Error: no file(s) for "{fileDefName}" have'
                    ' been provided after execution of shell command.')
    for fileDefName, files_ in selectedFiles.items():
        mostRecentFile = list(sorted(files_, key=lambda f: os.path.getmtime(f)))
        mostRecentFile = mostRecentFile[-1]
        if fileDefName == 'installed-files-list':  # a very special type
            with open(mostRecentFile) as f:
                for l in f:
                    fsEntry = l.strip()
                    self._installedFSEntries.append(fsEntry)
            continue  # do not consider files list as a special package file
        L.info(f'{fileDefName} provided: {mostRecentFile}')
        self._packageFiles[fileDefName] = mostRecentFile
    # set clean-up handler
    def _em_rm_cwd(emergency):
        if os.path.isdir(cwd):
            if not emergency:
                L.info(f' + deleting {cwd}')
                shutil.rmtree(cwd)
            else:
                L.warning(f' - {cwd} is kept for inspection')
    if removeCwd:
        self._onExit.append(_em_rm_cwd)
