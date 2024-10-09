import os, requests, logging, json, subprocess, glob
from fnmatch import fnmatch
from tqdm import tqdm

from lpkgm.settings import gSettings

def pkg_manifest_file_path(pkgName, pkgVer):
    # NOTE: shell-style wildcard will result in a wildcard
    # path (that's an anticipated case)
    pkgVerStr = pkgVer
    if type(pkgVer) is dict:
        pkgVerStr = pkgVer['fullVersion']
    return os.path.join(gSettings['packages-registry-dir'], pkgName, pkgVerStr + '.json')

def pkg_manifest_file_path_to_name_and_ver(path):
    assert path.endswith('.json')
    pkgVer  = os.path.basename(path)[:-5]  # get filename and strip off .json suffix
    pkgName = os.path.basename(os.path.dirname(path))
    return pkgName, pkgVer

def get_package_manifests(pkgName, pkgVer_, exclude=None):
    """
    Loads package manifests according to given package name and version.
    Both can be wildcards (globs).
    Optionally, can exclude certain items, if ``exclude`` is given. In this
    case ``exclude`` is expected to be a list of pairs of wildcards (name
    and version) to omit from loading. Items within the ``exclude`` will
    be applied at once (logic and).
    """
    if exclude is None: exclude = []
    exclude_ = []
    for excludeItem in exclude:
        exclude_.append(pkg_manifest_file_path(*excludeItem))
    pkgVerStr = pkgVer_
    if type(pkgVer_) is dict:
        pkgVerStr = pkgVer_['fullVersion']
    assert type(pkgVerStr) is str
    # pkgName and pkgVerStr can be a shell-style wildcard, resulting
    # in a wildcard path
    manifestFilePathPat = pkg_manifest_file_path(pkgName, pkgVerStr)
    r = []
    for manifestFilePath in glob.glob(manifestFilePathPat):
        skip = False
        for excludeItem in exclude_:
            if fnmatch(manifestFilePath, excludeItem):
                skip = True
                break
        if skip: continue  # excluded
        with open(manifestFilePath) as f:
            r.append(json.load(f))
    return r

def sizeof_fmt(num, suffix="B"):
    """
    Returns human-readable size format.
    """
    for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def stats_summary(stats):
    """Shortcut for package stats summary (size and numbers of entries)"""
    return f'{sizeof_fmt(stats["size"])} in {stats["nFiles"]} files'

def get_gitlab_project_token(projectID, server=None):
    """
    If ``CI_JOB_TOKEN`` is not specified, tries to obtain it from the file by
    the location specified in settings.
    """
    assert projectID
    assert type(projectID) is str
    L = logging.getLogger(__name__)
    fmtDct = {'server': server}
    fmtDct.update(gSettings['definitions'])
    jobToken = os.environ.get('CI_JOB_TOKEN', None)
    if jobToken is None:
        tokenFilePath = os.path.join( os.path.expandvars(gSettings['gitlab-tokens-dir'].format(**fmtDct))
                , f'{projectID}.txt'
                )
        L.debug(f'No job token; trying to read one from {tokenFilePath}')
        if not os.path.isfile(tokenFilePath):
            raise RuntimeError(f'Not a file: {tokenFilePath}')
        with open(tokenFilePath) as f:
            return ('private-token', f.read().strip())
    else:
        return ('job-token', jobToken)

def download_file_http(fileURL, outFPath):
    """
    Downloads file from HTTP enpoint with progress bar.
    TODO: gitlab auth?
    """
    response = requests.get(fileURL, stream=True, allow_redirects=True)
    if response.status_code != 200:
        response.raise_for_status()
        raise RuntimeError(f"Request to {fileURL} returned status code {response.status_code}")
    totalSize = int(response.headers.get("Content-Length", 0))
    blockSize = 1024
    received = 0
    with tqdm(total=totalSize, unit="B"
            , unit_scale=True, ascii='.#'
            , bar_format='{desc:<5.5}{percentage:3.0f}%|{bar:40}{r_bar}') as pb:
        with open(outFPath, "wb") as file:
            for data in response.iter_content(blockSize):
                pb.update(len(data))
                file.write(data)
                received += len(data)
    if totalSize != received:
        raise RuntimeError(f'Failed to download {fileURL} into {outFPath}: only'
                + f' {received} bytes received out of {totalSize}')

def execute_command(cmd, cwd=None, env=os.environ, joinStreams=False):
    """
    Common thin wrapper on shell command execution for more verbose logging
    and error handling.
    """
    L = logging.getLogger(__name__)
    cmdString = '$ ' + ' '.join(cmd)
    if cwd:
        cmdString = cwd + ' ' + cmdString
    L.info(cmdString)
    #
    p = subprocess.Popen( cmd
            , shell=False
            , stdout=subprocess.PIPE, stderr=(subprocess.PIPE if not joinStreams else subprocess.STDOUT)
            , env=env
            , cwd=cwd
            )
    outs, errs = p.communicate()
    if 0 != p.returncode:
        L.error('Error occured during shell execution.')
        if not joinStreams:
            L.error(f'stderr output of the command (exit code {p.returncode}):')
            L.error(errs.decode())
        else:
            L.error(f'combined stdout and stderr output of the command (exit code {p.returncode}):')
            L.error(outs.decode())
        raise RuntimeError(f'Shell command failed with code {p.returncode}.')
    # forward stderr output, if any
    #if errs:
    #    L.warning(errs.decode())
    return outs, errs, p.returncode

def packages(pkgNamePattern=None, pkgVerPattern=None):
    """
    Generator function yielding all packages known to registry.
    """
    L = logging.getLogger(__name__)
    for pkgFilePath in glob.glob(gSettings['packages-registry-dir'] + '/*/*.json'):
        with open(pkgFilePath, 'r') as pkgFile:
            pkgData = json.load(pkgFile)
        if not ('package' in pkgData and 'version' in pkgData):
            L.warning(f'Warning: file "{pkgFilePath}" does not'
                    + ' seem to be a package file (ignored).')
            continue  # omit .json as it is not the package file
        # TODO: fnmatch(.lower())
        #if pkgName and pkgName.lower() not in pkgData['package'].lower(): continue
        yield pkgData, pkgFilePath
