import os.path
import logging, tarfile

def run( self, pkgName, pkgVer
       , tarFile, baseDir, cvmfsServer
       , deleteDir=None  # todo: we assume this *can* be a list
       , createDir=None  # todo: we assume this *can* be a list
       , prefix=None
       ):
    """
    Uses CVMFS ingestion mechanism to install files provided in a tarball.
    See this report for details: https://indico.cern.ch/event/732678/contributions/3021405/attachments/1665124/2669090/CVM-FS_Tarball_Ingestion_Deep.pdf

    Notes: quoting help string of `cvmfs_server -h ingest':
     ingest          -t tarfile
                     -b base directory
                     [-d <folder to delete>]
                     [-c create nested catalog in base directory]
                     <fully qualified name>
                     Extract the content of the tarfile inside the base directory,
                     in the same transaction it also delete the required folders.
                     Use '-' as -t argument to read the tarball from STDIN
    TODO: not clear from the help, whether:
    1) -d can be given multiple times (presume yes)
    2) -d necessarily executed _before_ unpacking the tarball (presume yes)
    3) -c can be given multiple times (presume yes)
    4) -c necessarily executed _before_ unpacking the tarball (presume yes)
    5) Why the long form of the options are not quoted anywhere in the reference?
    According to their "(CVMFS) tests, it does not seems to support multiple
    directories (or it is not tested), the order is also not tested:
        https://github.com/cvmfs/cvmfs/blob/e4c16795062f8b9363dd019ee06b43a0f46387d8/test/src/657-tarball_remove_base_directory/main#L95
    """
    L = loggiung.getLogger(__name__)
    # build cmd args
    cmd_ =  ['cvmfs_server', 'ingest']
    # handle dir to delete
    if deleteDir:
        deleteDir = []
    elif type(deleteDir) is str:
        deleteDir = [deleteDir]
    assert type(deleteDir) in (tuple, list)
    for dd in deleteDir:
        cmd_ += ['-d', dd]
    # handle create dir
    if createDir:
        createDir = []
    elif type(createDir) is str:
        createDir = [createDir]
    assert type(createDir) in (tuple, list)
    for dd in createDir:
        cmd_ += ['-c', dd]
    # handle archive
    assert tarFile
    cmd_ += ['--tar_file', tarFile]
    # list files to be installed to render the manifest
    installedFiles = None
    with tarfile.open(tarFile, 'r') as tf:
        installedFiles = tf.getnames()
    # handle base dir
    assert baseDir
    cmd_ += ['--base_dir', baseDir]
    # finalize command template with cvmfs server
    assert cvmfsServer
    cmd += [cvmfsServer]
    # Format the tokens expanding variables and stuff:
    # - append (local copy of) formatting dict with version info
    fmtDct = copy.copy(self._fmtDict)
    fmtDct.update(pkgVer)
    # - interpolate cmd, expand environment variables
    cmd = []
    for tok_ in cmd_:
        tok_ = tok.format(**fmtDct)
        cmd.append(os.path.expandvars(tok_))
    # try to apply the commands
    execute_command(cmd, cwd=cwd, env=env, joinStreams=True)
    # FIXME: we ignore deleted directory(ies) as LPKGM currently have
    #        no means to maintain this kind of change in the package manifest
    for relPath in installedFiles:
        absPath = os.path.join(baseDir, relPath)
        if not os.path.exists(absPath):
            raise RuntimeError(f'FS entry {absPath} does not exist after tarball ingestion')
        self._installedFSEntries.append(absPath)
