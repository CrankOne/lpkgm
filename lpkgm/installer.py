import os, copy, importlib
from collections import defaultdict
import logging, shutil, tempfile, pathlib, glob
import gitlab
from fnmatch import fnmatch
from datetime import datetime

from lpkgm.settings import gSettings
from lpkgm.utils import execute_command

gInstallerPluginPrefix='lpkgm_installer_'

# import default plugins
#import lpkgm.lpkgm_installer_shell_cmd

class Installer(object):
    """
    Gets created in order to install particular package, represents
    installation pipeline (a singular purpose of this class).

    Gets constructed based on package manifest and evolve dynamically-composed
    installation pipeline. The pcakage manifest should provide a sequence of
    calls of methods listed below in section "methods".
    """
    def __init__(self, items, modulescript=None, pkgDefs=None):
        import importlib, pkgutil
        L = logging.getLogger(__name__)
        self._items = copy.copy(items)
        self._onExit = []
        self._packageFiles = {}
        self._installedFSEntries = []
        self._dependencies = []
        if modulescript and not os.path.isfile(self._modulescript):
            raise RuntimeError(f'Module script is not a file ("{self._modulescript}")')
        self._modulescript=modulescript
        # build formatting dictionary for package
        self._fmtDict = copy.deepcopy(gSettings['definitions'])
        if pkgDefs:
            self._fmtDict.update(pkgDefs)
        # dynamically import methods
        self._plugins = {}
        for ext in gSettings['installer-extensions']:
            module = importlib.import_module(ext)
            for importer, modname, ispkg in pkgutil.walk_packages(
                    path=module.__path__,
                    prefix=module.__name__ + '.'
                    ):
                subModule = importlib.import_module(modname)
                if not hasattr(subModule, 'run'):
                    L.debug(f'Module {subModule} has no run(), omitting')
                    continue
                extName = subModule.__name__.split('.')[-1]
                if extName not in self._plugins.keys():
                    L.debug(f'Adding {extName} installer extension (module'
                            f' "{subModule.__name__}")')
                else:
                    L.info(f'Overriding {extName} installer extension with'
                            f' "{subModule.__name__}"')
                self._plugins[extName] = subModule
        if not self._plugins:
            L.warning('No installer plugins loaded.')
        else:
            L.info('Known installer plugins: ' + ', '.join(sorted(self._plugins.keys())))


    def __call__(self, *args, **kwargs):
        L = logging.getLogger(__name__)
        hadError = False
        # check all the need plugins are loaded beforehand
        for item in self._items:
            pluginName = item['type'].replace('-', '_')
            if pluginName not in self._plugins:
                raise ImportError(f'No installer plugin {pluginName}')
        # run the installation procedures
        for item in self._items:
            kwargs_ = copy.copy(item)
            kwargs_.pop('type')
            kwargs_.update(dict(kwargs))
            pluginName = item['type'].replace('-', '_')
            pluginModule = self._plugins[pluginName]
            assert pluginModule
            mtd = getattr(pluginModule, 'run')
            if not mtd:
                raise ImportError(gInstallerPluginPrefix + pluginName + '.run')
            try:
                mtd(self, *args, **kwargs_)
            except Exception as e:
                L.error(f'Error occured during evaluation of procedure {item["type"]}:')
                L.exception(e)
                #traceback.print_exc()
                hadError = True
                break
        if hadError:
            L.error('Exit due to an error.')
            return False
        return True

    @property
    def installedFiles(self):
        return self._installedFSEntries

    @property
    def dependenciesList(self):
        return list((dep['package'], dep['version']['fullVersion']) for dep in self._dependencies)

    @property
    def stats(self):
        L = logging.getLogger(__name__)
        r = {'size': 0, 'nFiles': 0, 'nDirs': 0, 'nLinks': 0}
        for fse in self._installedFSEntries:
            if os.path.isfile(fse):
                r['size'] += os.path.getsize(fse)
                r['nFiles'] += 1
                continue
            if os.path.isdir(fse):
                r['nDirs'] += 1
                continue
            if os.path.islink(fse):
                r['nLinks'] += 1
                continue
            L.warning(f'Unknown/non-existing fs-entry: "{fse}"')
        return r

    def on_exit(self, emergency=True):
        L = logging.getLogger(__name__)
        L.info('Performing on-exit cleanup procedures (%s):'%('emergency' if emergency else 'normal'))
        if not self._onExit:
            L.info('    (no on-exit handlers)')
        for exitHandler in reversed(self._onExit):
            try:
                exitHandler(emergency)
            except Exception as e:
                L.error('Error occured during evaluation of'
                        ' exit handler:')
                #traceback.print_exc()
                L.exception(e)

    def depends(self, pkgName, pkgVer):
        """
        Appends dependency if need.
        """
        L = logging.getLogger(__name__)
        try:
            for depItem in self._dependencies:
                if pkgName != depItem['package']: continue
                # name match, check version
                if pkgVer == depItem['version']['fullVersion']:
                    return depItem
                #if type(depItem[1]) is dict:
                #    assert 'fullVersion' in depItem[1].keys()
                #    if pkgVer == depItem[1]['fullVersion']: return depItem[1]
                #else:  # str version
                #    if pkgVer == depItem[1]: return depItem[1]
            # otherwise, no match found in already added dependencies -- append
            return self.resolve_dependency(pkgName, pkgVer)
        except Exception as e:
            L.error(f'Failed to resolve {pkgName}/{pkgVer}')
            L.exception(e)
            return None

    def resolve_dependency(self, pkgName, pkgVer):
        assert type(pkgName) is str
        assert type(pkgVer) in (str, dict)
        pkgData = get_package_manifests(pkgName, pkgVer)
        if not pkgData:
            raise RuntimeError(f'Package is not installed: {pkgName} of'
                + f' version {pkgVerStr} (no install manifest file exists)')
        if 1 != len(pkgData):
            raise RuntimeError(f'Multiple packages match {pkgName}/{pkgVerStr}')
        #self._dependencies.append(pkgData[0])  # xxx?
        #pkgVerStr = pkgVer if type(pkgVer) is str else pkgVer['version']['fullVersion']
        #print('xxx', (pkgName, pkgVer['version']) )
        self._dependencies.append(pkgData[0])
        return pkgData[0]

    #                                                                 _______
    # ______________________________________________________________/ Methods
    # this method get called dynamically, in order given in "install"
    # argument of the package description object
