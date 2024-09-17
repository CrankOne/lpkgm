import os, logging, json, glob

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

    'packages'              : {}
}

def _packages_from_descriptions(descriptions, settingsDir):
    L = logging.getLogger(__name__)
    for item in descriptions:
        if type(item) is dict:
            pkgName = item['name']
            item.pop('name')
            yield pkgName, item, settingsDir
        elif type(item) is str:
            pathItem = os.path.expandvars(item.format(**gSettings['definitions']))
            if os.path.isfile(pathItem):
                with open(pathItem, 'r') as f:
                    item = json.load(f)
                pkgName = item['name']
                item.pop('name')
                yield pkgName, item, pathItem
            else:
                L.debug(f'Getting package descriptions from {pathItem}')
                nPkgs = 0
                for pkgDefFilePath in glob.glob(pathItem):
                    # derive package name from dir
                    pkgDir, _ = os.path.split(pkgDefFilePath)
                    pkgDir, pkgName = os.path.split(pkgDir)
                    L.debug(f"Loading package definition from {pkgDefFilePath} for"
                            f" package \"{pkgName}\"")
                    with open(pkgDefFilePath) as f:
                        pkgDef = json.load(f)
                    # append packages' "definitions" attribute with package's local
                    #if 'definitions' not in pkgDef: pkgDef['definitions'] = {}
                    #pkgDef['definitions']['pkgDir'] = pkgDir
                    # interpolate special variable in the package definition object
                    # (recursively)
                    yield pkgName, pkgDef, pkgDefFilePath
                    nPkgs += 1
                if not nPkgs:
                    L.warning(f'No packages found in {pathItem}')

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
    assert 'definitions' in settings.keys()
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
