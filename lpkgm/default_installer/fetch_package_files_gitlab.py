import os, copy, logging, tempfile, shutil
from collections import defaultdict
from fnmatch import fnmatch
from datetime import datetime
import gitlab
from lpkgm.settings import gSettings
from lpkgm.utils import get_gitlab_project_token, download_file_http

# Note: at some point datetime.fromisoformat() stopped to work with timestamp
#       provided by GitLab API, so we moved to hardcoded format here.
gTSFmtISO="%Y-%m-%dT%H:%M:%S.%f%z"

def run(self, pkgName, pkgVer
        , server=None
        , projectID=None
        , files=None
        , pkgType='generic'  # optional, query parameter
        , quietOnNoFiles=False
        , publishedAtTimeInterval=None
        , keepFiles=False
        , sourceCodeVersion=None
        ):
    """
    Fetches package of certain version from Project's gitlab package registry
    and returns dictionary with file details definitions.
    """
    L = logging.getLogger(__name__)
    fmtDct = copy.copy(self._fmtDict)
    fmtDct.update(pkgVer)
    if publishedAtTimeInterval is None:
        publishedAtTimeInterval = [None, None]
    if publishedAtTimeInterval[0] and type(publishedAtTimeInterval[0]) is str:
        publishedAtTimeInterval[0] = datetime.strptime(publishedAtTimeInterval[0], gTSFmtISO)
    if publishedAtTimeInterval[1] and type(publishedAtTimeInterval[1]) is str:
        publishedAtTimeInterval[1] = datetime.strptime(publishedAtTimeInterval[1], gTSFmtISO)
    # authenticate GitLab API and get files matching patterns to pick up
    assert projectID is not None
    token = get_gitlab_project_token(projectID, server=server)
    assert token is not None
    gl = None
    if 'private-token' == token[0]:
        gl = gitlab.Gitlab(server, private_token=token[1])
        gl.auth()
    elif 'job-token':
        gl = gitlab.Gitlab(server, job_token=token[1])
    assert gl
    project = gl.projects.get(int(projectID))

    assert files
    # make `filePatterns' to contain only tuples (contrary to `files')
    filePatterns = defaultdict(list)
    for fileDefName, fileDefPatterns in files.items():
        if type(fileDefPatterns) is str:
            fileDefPatterns = (fileDefPatterns.format(**fmtDct),)
        for fileDefPattern in fileDefPatterns:
            filePatterns[fileDefName].append(fileDefPattern.format(**fmtDct))

    selectedFiles = defaultdict(list)
    pkgQueryParams = {}
    if pkgVer:
        # NOTE: we make distinction here between "source code version"
        # which does not include build configuration and "package version"
        # which does. This plays a role when different builds are published
        # under the same version, like:
        #   `-1.2.3:  # source code version
        #       |- pgk-1.2.3.opt.cpack.tar.gz  # package version for opt build
        #       `- pkg-1.2.3.dbg.cpack.tar.gz  # package version for dbg build
        # by default we expect the version to match (i.e. source code version
        # is the same as package version), but package settings can provide
        # "sourceCodeVersion" which will be used instead for querying package.
        pkgQueryParams['package_version']=pkgVer['fullVersion']
        if sourceCodeVersion:
            fmtDict = copy.copy(self._fmtDict)
            fmtDict.update(pkgVer)
            if type(sourceCodeVersion) is str:
                sourceCodeVersion = [sourceCodeVersion]
            for scv in sourceCodeVersion:
                try:
                    pkgQueryParams['package_version']=scv.format(**fmtDict)
                    break
                except KeyError as e:
                    continue
    if pkgName: pkgQueryParams['package_name']=pkgName
    if pkgType: pkgQueryParams['package_type']=pkgType
    emptyList=True
    for pkg in project.packages.list(**pkgQueryParams):
        # ^^^ query options, examples:
        #   - package_type='generic'
        #   - package_version='0.4.dev'
        #   - package_name='na64sw'
        emptyList=False
        for pf in pkg.package_files.list(get_all=True):
            for fileDefName, fileDefPatterns in filePatterns.items():
                for pat in fileDefPatterns:
                    if fnmatch(pf.file_name, pat):
                        selectedFiles[fileDefName].append((pf, pkg))
    if not selectedFiles or emptyList:
        if quietOnNoFiles:
            return None  # TODO: empty dict?
        L.error('Error details:\n'
                + f'- Query parameters: {pkgQueryParams}\n'
                + f'- Files lookup parameters: {files}\n'
                + f'- ...expanded to: {filePatterns}'
                )
        if emptyList:
            L.error('(!) EMPTY LIST was returned for these query parameters!')
        strAux = '- Available packages and files:\n'
        for pkg in project.packages.list():
            strAux += f'    - {pkg.id} {pkg.name} {pkg.version}\n'
            for pf in pkg.package_files.list():
                strAux += f'      * {pf.file_name} {pf.size}\n'
        L.info(strAux)
        raise RuntimeError('No files found to fetch for query parameters.')

    # strip old files from download if timestamp is not specified
    filesToFetch = {}
    for fileDefName, thisFiles in selectedFiles.items():
        sortedByCreation \
            = sorted(thisFiles, key=lambda f: datetime.strptime(f[0].created_at, gTSFmtISO))
        if publishedAtTimeInterval[0]:
            sortedByCreation = filter(lambda f: f[0].created_at > publishedAtTimeInterval[0], sortedByCreation)
        if publishedAtTimeInterval[1]:
            sortedByCreation = filter(lambda f: f[0].created_at < publishedAtTimeInterval[1], sortedByCreation)
        if not sortedByCreation:
            raise RuntimeError('No files matching required creation time'
                    + f' interval for {fileDefName}')
        filesToFetch[fileDefName] = list(sortedByCreation)[-1]  # most recent
    # Print available package files and their creation dates, mark the files
    # selected for download
    infoStr = ''
    for k, v in selectedFiles.items():
        infoStr += f'{k}:\n'
        for fdef in v:
            ln = f'{fdef[0].created_at} {fdef[0].file_name}'
            if k in filesToFetch and fdef[0].id == filesToFetch[k][0].id:
                ln = '-> \033[1m' + ln + '\033[0m'
            else:
                ln = '   ' + ln
            infoStr += '  ' + ln + '\n'
    L.info(infoStr)
    self._pkgDir = tempfile.mkdtemp(prefix=gSettings.get('tmp-dir-prefix', None))
    def _em_rm_pkg_dir(emergency):
        if os.path.isdir(self._pkgDir):
            if not emergency:
                L.info(f' + deleting {self._pkgDir}')
                shutil.rmtree(self._pkgDir)
            else:
                L.warning(f' - {self._pkgDir} is kept for inspection')
    if not keepFiles:
        self._onExit.append(_em_rm_pkg_dir) # install on-exit handler to delete tmp dir
    for fileDefName, (glFile, _) in filesToFetch.items():  # , glPackage
        # download file by ID
        fileURL = f'{server}/{project.path_with_namespace}/-/package_files/{glFile.id}/download'
        outFPath = os.path.join(self._pkgDir, glFile.file_name)
        L.debug(f'Downloading:\n    {fileURL} -> {outFPath}')
        download_file_http(fileURL, outFPath)
        self._packageFiles[fileDefName] = outFPath
        #with open(outFPath, 'wb') as f:
        #    for data in tqdm(response.iter_content()):
        #        f.write(data)
        # #1: works, but has argument for particular file ID (in case of
        # duplicating names) -- no use for datetime sort...
        #fileURL = f'{project.generic_packages.path}/{glPackage.name}/{glPackage.version}/{glFile.file_name}'
        #outFPath = os.path.join(tmpDir, glFile.file_name)
        #with open(outFPath, 'wb') as f:
        #    sys.stdout.write(f'{fileURL} -> {outFPath}\n')  # XXX
        #    gl.http_get(fileURL
        #            , streamed=True
        #            , action=f.write )
        # #2: works, but has argument for particular file ID (in case of
        # duplicating names) -- no use for datetime sort...
        #with open(os.path.join(tmpDir, glFile.file_name), 'wb') as f:
        #    project.generic_packages.download(
        #            package_name=glPackage.name,
        #            package_version=glPackage.version,
        #            file_name=glFile.file_name,
        #            streamed=True,
        #            action=f.write
        #        )
    return self._packageFiles
