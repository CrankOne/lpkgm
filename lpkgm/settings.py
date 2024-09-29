import os, logging, json, glob, re
import lpkgm.protection

#
# Default settings specific to particular deployment share. Gets overloaded
# by settings .json file at entry point.

gSettings = {
    # Location of installed packages manifests
    'packages-registry-dir' : './registry.d',
    # GitLab tokens are stored here (per-project); sometimes they are not
    # needed, as within CI/CD pipelines the (temporary) pipeline token is used
    'gitlab-tokens-dir'     : '/etc/gitlab-ci-tokens/',
    # Dictionary of common definitions used to format paths, additionaly to
    # package's ones
    'definitions'           : {},
    # Build directory prefix; gettempprefix() is used, if None
    'tmp-dir-prefix'        : None,
    # Where modules of installed files should be located
    'modulepath'            : '/usr/share/modules/modulefiles/',
    # Known packages list
    'packages'              : {},
    # List of user's extensions (must be Python modules)
    'installer-extensions'  : ['lpkgm.default_installer']
}

def _packages_from_descriptions(descriptions, settingsDir):
    L = logging.getLogger(__name__)
    for item in descriptions:
        if type(item) is str:
            # assumed a standalone package in a file -- load for
            # further treatment. If "name" is not given explicitly within
            # loaded object, use filename without extension as package name
            if not os.path.isfile(item):
                raise RuntimeError(f'Not a file: {item}')
            with open(item, 'r') as f:
                pkgData = json.load(f)
            if 'name' not in pkgData:
                pkgData['name'] = os.path.splitext(os.path.basename(item))[0]
            L.debug(f'Loaded JSON package data from {item}')
            item = pkgData
        if type(item) is dict:
            # assumed a standalone package -- get the "name" from object
            # and use the rest as package definition
            pkgName = item['name']
            item.pop('name')
            yield pkgName, item, settingsDir
        elif type(item) in (list, tuple) and 2 == len(item):
            # otherwise, assume a complex case, used for large software
            # bundles repo: a file lookup wildcard with regular expression
            pathWildcard, rx = item
            pathWildcard = os.path.expandvars(pathWildcard.format(**gSettings['definitions']))
            L.debug('Getting package descriptions from glob'
                    + f' pattern {pathWildcard} matching regular expression "{rx}"')
            rx = re.compile(rx)
            nPkgs = 0
            for pkgDefFilePath in glob.glob(pathWildcard):
                m = rx.match(pkgDefFilePath)
                if not m:
                    L.debug(f'{pkgDefFilePath} does not match regular expression')
                    continue
                # parse path extracting user-defined additions to the package's
                # definitions
                pathSemantics = dict(m.groupdict())
                # load package data
                with open(pkgDefFilePath) as f:
                    pkgDef = json.load(f)
                pkgName = None
                if 'name' in pkgDef.keys():
                    # "name" given in .json has priority over regular
                    # expression tokens
                    pkgName = pkgDef['name']
                    pkgDef.pop('name')
                elif 'name' in pathSemantics.keys():
                    # otherwise -- try to get package name from "name" rx
                    # matching group
                    pkgName = pathSemantics['name']
                    pathSemantics.pop('name')
                else:
                    # otherwise, consider filename without extension as package
                    # name
                    pkgName = os.path.splitext(os.path.basename(pkgDefFilePath))[0]
                assert pkgName
                pkgDir, _ = os.path.split(pkgDefFilePath)
                L.debug(f"Loaded package definition from {pkgDefFilePath} for"
                        f" package \"{pkgName}\"")
                yield pkgName, pkgDef, pkgDefFilePath
                nPkgs += 1
            if not nPkgs:
                L.warning(f'No packages found in {pathWildcard}')
        else:
            raise RuntimeError(f'Unable to interpret "packages" entry "{item}"'
                    + ' as package(s) definition.')

def read_settings_file(settingsFilePath, definitions=None):
    """
    Reads settings file (.json).

    This file has particular schema which we are planning to standardize at
    some point. This is NOT a pure function as it changes ``gSettings``
    object.
    """
    L = logging.getLogger(__name__)
    # initialize definitions to empty list, if not given
    if not definitions: definitions=[]
    # load file
    if not os.path.isfile(settingsFilePath):
        raise RuntimeError(f"Not a file: \"{settingsFilePath}\"")
    with open(settingsFilePath) as f:
        settings = json.load(f)
    if 'definitions' not in settings.keys():
        settings['definitions'] = {}
    # append some common definitions
    if 'pwd' not in settings['definitions'].keys():
        settings['definitions']['pwd'] = os.getcwd()
    # expand variables in definitions until there is no more to expand; note
    # that it directly affects gSettings
    # (todo: detect infinite loop?)
    if definitions:
        for entry in definitions:
            k, v = entry.split('=')
            gSettings['definitions'][k] = v
    for k, v in settings['definitions'].items():
        gSettings['definitions'][k] = os.path.expandvars(v)
    while True:
        hadChange = False
        for k, v in gSettings['definitions'].items():
            newVal = v.format(**gSettings['definitions'])
            if newVal != v:
                adChange = True
            gSettings['definitions'][k] = newVal
        if not hadChange: break
    # modify gSettings, substituting 1st level entries
    for k, v in settings.items():
        if k in ('packages', 'definitions'): continue  # omit some keys
        if v is None:
            gSettings[k] = None
            continue
        gSettings[k] = os.path.expandvars(v.format(**gSettings['definitions']))
    # interpolate "packages" wildcards, load package definitions
    pkgDescrs = settings['packages']
    settings.pop('packages')
    for pkgName, pkgDescr, path in _packages_from_descriptions(pkgDescrs
            , os.path.dirname(settingsFilePath)):
        if 'definitions' not in pkgDescr: pkgDescr['definitions'] = {}
        if os.path.isfile(path):
            if 'pkgDir' not in pkgDescr['definitions']:
                pkgDescr['definitions']['pkgDir'] = os.path.dirname(path)
            if 'pkgFile' not in pkgDescr['definitions']:
                pkgDescr['definitions']['pkgFile'] = path
            L.debug(f'Appending "{pkgName}" package\'s definitions'
                    f' with pkgDir="{pkgDescr["definitions"]["pkgDir"]}",'
                    f' pkgFile="{pkgDescr["definitions"]["pkgFile"]}"')
        elif os.path.isdir(path):
            if 'pkgDir' not in pkgDescr['definitions']:
                pkgDescr['definitions']['pkgDir'] = path
            L.debug(f'Appending "{pkgName}" package\'s definitions'
                    f' with pkgDir="{pkgDescr["definitions"]["pkgDir"]}"')
        gSettings['packages'][pkgName] = pkgDescr
    assert 'packages' in gSettings
    if 0 == len(gSettings['packages']):
        L.warning('No packages descriptions loaded.')
    else:
        L.info(f'{len(gSettings["packages"])} package(s) known overall.')
    # normalize tokens and registry dir paths
    for k in ('gitlab-tokens-dir', 'packages-registry-dir'):
        gSettings[k] = os.path.normpath(gSettings[k])
    return settings


