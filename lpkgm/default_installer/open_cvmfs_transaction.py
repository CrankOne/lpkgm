import logging
from lpkgm.utils import execute_command

def run(self, pkgName, pkgVer
       , cvmfsServer=None
       , timeoutSec=60  # can be None
       ):
    """
    Tries to open transaction on given CVMFS share.
    Sets up on-exit handler, publishing or aborting the transaction
    at exit.
    """
    L = logging.getLogger(__name__)
    # TODO ...
    #"cvmfs-server": "na64.cern.ch",
    #"sft-root-path": "/cvmfs/na64.cern.ch/sft"
    cmds = ["cvmfs_server", "transaction", cvmfsServer]
    if timeoutSec:
        cmds += ['-t', f'{timeoutSec}']
    _, _, rc = execute_command(cmd=cmds, joinStreams=True, cwd='/')
    def _em_finalize_cvmfs_transaction(emergency):
        if not emergency:
            L.info(f' + publishing {cvmfsServer}')
            cmds = ["cvmfs_server", "publish", cvmfsServer]
            execute_command(cmd=cmds, joinStreams=True, cwd='/')
        else:
            L.warning(f' - aborting {cvmfsServer}')
            cmds = ["cvmfs_server", "abort", '-f', cvmfsServer]
            execute_command(cmd=cmds, joinStreams=True, cwd='/')
    if 0 == rc:
        self._onExit.append(_em_finalize_cvmfs_transaction)
    else:
        L.warning('Note: on-exit handler is not installed'
                + f' for cvmfs transaction due to return code {rc}.')
