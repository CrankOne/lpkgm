import os, pathlib, copy, pathlib

from lpkgm.utils import execute_command

def run(self, pkgName, pkgVer, prefix=None):
    """
    Very similar to ``unpack_dist_archive()``, but with slightly different
    naming. In principle should benefit from cpack's special features,
    but so far is unclaimed...
    """
    if 'cpack-archive' not in self._packageFiles:
        raise RuntimeError('No "cpack-archive" in package files provided'
                ' by previous stage(s).')
    if not prefix:
        raise RuntimeError('Invalid prefix argument; can\'t install cpack archive.')
    fmtDct = copy.copy(self._fmtDict)
    fmtDct.update(pkgVer)
    prefix = prefix.format(**fmtDct)
    pathlib.Path(prefix).mkdir(parents=True, exist_ok=True)
    # installation of cpack archive is rather simple:
    #   tar xf ${pkg_dist} -C ${INSTALL_PATH} --strip-components=1
    cmd = ['tar', 'xvf', self._packageFiles['cpack-archive'], '-C', prefix, '--strip-components=1']

    outs, _, _ = execute_command(cmd)
    # collect files list (for uninstall)
    for l in outs.decode().splitlines():
        pp = pathlib.Path(*pathlib.Path(l).parts[1:])
        pp = os.path.join(prefix, pp)
        self._installedFSEntries.append(pp)
