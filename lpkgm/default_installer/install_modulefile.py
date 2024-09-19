import os, copy, shutil, logging, pathlib
from lpkgm.settings import gSettings

def run(self, pkgName, pkgVer, parseDependencies=False):
    L = logging.getLogger(__name__)
    if 'modulefile' not in self._packageFiles:
        raise RuntimeError('No "modulefile" in package files provided by'
                ' previous stage(s)')
    fmtDct = copy.copy(self._fmtDict)
    fmtDct['pkgVer'] = pkgVer
    mfPath = os.path.join(gSettings['modulepath'], pkgName, pkgVer['fullVersion'])
    #mfPath = os.path.realpath(os.path.expandvars(moduleFileTemplate.format(**fmtDct)))
    mfPathDir = os.path.dirname(mfPath)
    if not os.path.isdir(mfPathDir):
        pathlib.Path(mfPathDir).mkdir(parents=True, exist_ok=True)
        #os.mkdir(mfPathDir, mode=0o775)
    # check prereq-all/prereq/etc
    if parseDependencies:
        with open(self._packageFiles['modulefile'], 'r') as f:
            # For details see: https://modules.readthedocs.io/en/latest/modulefile.html#dependencies-between-modulefiles
            # Quoting: `` ...re-requirement could be expressed with
            # prereq, prereq-any, prereq-all, depends-on, always-load,
            # module load, module switch, module try-load or module
            # load-any... ``
            for line_ in f.readlines():
                line = line_.strip()
                if not line: continue
                tok = line.split(None, 1)[0]  # take 1st part of whitespace split
                if tok in ('prereq-all', 'depends-on'):
                    # take 2nd part of the line and interpret it as a list of
                    # dependencies
                    for tok in line.split()[1:]:
                        if tok in ('--optional', '--modulepath'):
                            L.warning(f'Unsupported module dependency option: "{tok}", ignored')
                            continue
                        if tok.count('/') != 1:
                            L.warning(f'Unsupported modulefile reference: "{tok}", ignored')
                            continue
                        depPkgName, depPkgVer = tok.split('/')
                        pkgData = self.depends(depPkgName, depPkgVer)
                        if not pkgData:
                            #L.error(f'Failed to resolve dependency "{tok}" with available modules.')
                            raise RuntimeError(f'Failed to resolve dependency "{tok}" with available modules.')
                        else:
                            assert type(pkgData) is dict
                            L.info(f'Depends on {tok} (saved).')
                    continue
                if tok in ('prereq', 'prereq-any', 'depends-on', 'always-load'):
                    L.warning(f'Unsupport module dependency command "{tok}" -- can'
                            + ' verify dependency is tracked by lpkgm.')
                    continue
                # otherwise, just ignore the line
    # copy module file
    shutil.copyfile(self._packageFiles['modulefile'], mfPath)
    self._installedFSEntries.append(mfPath)
    L.info(f'Modulefile {mfPath} installed.')
