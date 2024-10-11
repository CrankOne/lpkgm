import io, datetime, logging, copy

from collections import defaultdict
from fnmatch import fnmatch

import lpkgm.ordered_versions

class ProtectionRule(object):
    """
    A "protection rule" object is applied to set of eponymous packages (i.e.
    packages that are different only by their versions) to figure out whether
    the particular package (i.e. pkg name + pkg version) is "protected". This
    information is used then to test if particular package(s) can be removed.

    This is an abstract base class for protection rules.
    """
    def __init__(self, label='abstract', **kwargs):
        self._label = label

    @property
    def label(self):
        return self._label

    def __call__(self, pkgVersion):
        raise NotImplementedError('Abstract protection rule in use (call).')

#                       * * *   * * *   * * *

class KeepAll(ProtectionRule):
    """
    Protection rule that keeps all the packages provided.
    """
    def __init__(self, label, **kwargs):
        super().__init__(label)

    def __call__(self, pkgVersion):
        return True

#                       * * *   * * *   * * *

class KeepVersion(ProtectionRule):
    """
    Protects wildcard-matching versions.    
    """
    def __init__(self, label, versionPattern, **kwargs):
        super().__init__(label)
        self._versionPattern = versionPattern

    def __call__(self, pkgVersion):
        return fnmatch(pkgVersion, self._versionPattern)

#                       * * *   * * *   * * *

class KeepNone(ProtectionRule):
    """
    Abstract protection rule that does not keep all the packages provided.
    """
    def __init__(self, label, **kwargs):
        super().__init__(label)

    def __call__(self, pkgVersion):
        return False

#                       * * *   * * *   * * *

class KeepLatestProtectionRule(ProtectionRule):
    """
    Protects latest N versions of the package, with respect to versions
    sorting order (defined by list of attributes and flavours). Exploits
    `lpkgm.ordered_versions.VersionsOrder` to define sorting order(s).

    This rule needs to know all the installed package version first, so
    its constructor needs to load package's manifests first.
    """
    def __init__( self
                , pkgName
                , label='latest'
                , attrsOrder=None
                , flavourFrom=None
                , latestLimit=1
                , **kwargs
                ):
        from lpkgm.utils import packages  # import here to avoid circular import
        L = logging.getLogger(__name__)
        assert latestLimit
        super().__init__(label)
        self._pkgName = pkgName
        # load manifests if (TODO: if _installTime in the attrs/flavours)
        self._versionsCache = {}
        for pkgData, manifestPath in packages(pkgName):
            if pkgData['package'] != pkgName:
                raise RuntimeError(f'Package manifest file {manifestPath}'
                    f' is inconsistent: defined package name is \"{pkgData["package"]}\",'
                    f' while "{pkgName}" is expected.')
            verStr = pkgData['version']['fullVersion']
            if verStr in self._versionsCache.keys():
                raise RuntimeError('Installed packages manifests inconsistent:'
                        + f' Version {verStr} installed twice'
                        + f' (2nd time in {manifestPath}) -- can not apply'
                        + ' "keep latest" rule.')
            assert verStr not in self._versionsCache.keys()  # guaranteed by above check
            its  = datetime.datetime.fromisoformat(pkgData['installedAt'])
            self._versionsCache[verStr] = copy.copy(pkgData['version'])
            self._versionsCache[verStr]['_installTime'] = its
            L.debug(f'Accounted {pkgName}/{verStr} installed at {its.isoformat()}')
        self._limit = latestLimit
        self._order = lpkgm.ordered_versions.VersionsOrder(
                attributesOrder=attrsOrder,
                ortogonalBy=flavourFrom
                )
        # init order with installation time cache (supplementary)
        self._sorted = {}
        for flavour, linVersions in \
                self._order(list( self._versionsCache.values()) ):
            self._sorted[flavour] = linVersions

    def __call__(self, pkgVersion):
        L = logging.getLogger(__name__)
        assert type(pkgVersion) is str
        if pkgVersion not in self._versionsCache.keys():
            raise KeyError(f'{self._pkgName}/{pkgVersion} is not known.')
        fl, ver = self._order.canonic_version_tuple(self._versionsCache[pkgVersion])
        # based on falvour, get list of sorted versions, truncated by limit
        linVersion = self._sorted[fl]
        matches = ver in set(item[0] for item in self._sorted[fl][-self._limit:])
        # ^^^ every item of linVersion is 2-tuple of:
        #  1. N-tuple of "canonic version"
        #  2. version dictionary
        # elements are in the TODO order (sorted)
        L.debug( f'Testing {pkgVersion}{str(ver)} version of {self._pkgName} with respect'
              + ' to (sorted) versions: ' + ', '.join(f"{item[1]['fullVersion']}{str(item[0])}" for item in linVersion)
              + f' by taking only {self._limit} most recent (go last): protected={matches}'
              )
        return matches

#                       * * *   * * *   * * *

def instantiate_protection_rule(**kwargs):
    type_ = kwargs.get('type')
    kwargs.pop('type')

    if type_.lower() in ('always', 'keep', 'system', 'keepall', 'keep_all', 'keep-all'):
        return KeepAll(**kwargs)
    if type_.lower() in ('never', 'none'):
        return KeepNone(**kwargs)
    if type_.lower() in ('latest'):
        return KeepLatestProtectionRule(**kwargs)
    # ... other protection rules
    raise KeyError(type_)

#                       * * *   * * *   * * *

def build_protection_rules():
    """
    Returns dictionary containing list of protection rules defined for certain
    package, the dictionary is indexed by package name. Rules are initialized
    with installed packages, if any were available.

    Note, that protection rules do not take into account dependency tree
    propagation.
    """
    from lpkgm.utils import packages  # import here to avoid circular import
    from lpkgm.settings import gSettings

    L = logging.getLogger(__name__)

    #packagesByName = defaultdict(list)  # for protection rules
    #for pkgData, pkgFilePath in packages():
    #    pkgName, pkgVer = pkgData['package'], pkgData['version']['fullVersion']
    #    # append packages dict
    #    packagesByName[pkgName].append(
    #            ( pkgData['version']['fullVersion']
    #            , datetime.datetime.fromisoformat(pkgData['installedAt'])
    #            )
    #        )

    # for every package definition in settings, construct protection rule,
    # taking into account collected version history
    protectionRules = {}
    for pkgName, pkgDef in gSettings['packages'].items():
        pkgProtectionRules = []
        if 'protection-rules' not in pkgDef.keys():
            L.debug(f'No protection rules for package {pkgName}')
            continue
        #if pkgName not in packagesByName.keys():
        #    L.debug(f'Package {pkgName} not installed -- ignoring protection rule')
        #    continue
        # instantiate protection rules and init them with installed
        # packages data
        for ruleDescription in pkgDef['protection-rules']:
            ruleDescriptionDict = copy.copy(ruleDescription)
            if 'pkgName' not in ruleDescriptionDict: ruleDescriptionDict['pkgName'] = pkgName
            rule = instantiate_protection_rule(**ruleDescriptionDict)
            pkgProtectionRules.append(rule)
            L.debug(f'Package "{pkgName}" protected with rule "{rule.label}"')
        if not pkgProtectionRules:
            L.warning(f'Package "{pkgName}" is not protected by a protection rule.')
        protectionRules[pkgName] = pkgProtectionRules
    return protectionRules

#                       * * *   * * *   * * *

def protecting_rules_report(items, indent=0):
    returnValue = False
    f = io.StringIO("")

    for peName, peVer, peRules, peSub in items:
        f.write('    '*indent + f'"{peName}/{peVer}" depends on the subject')
        if peRules:
            f.write(f', is protected by rules: {", ".join(peRules)}')
        if peSub:
            f.write(' and provides packages:\n')
            f.write(protecting_rules_report(peSub, indent=indent+1))
        else:
            f.write('\n')
    return f.getvalue()

# Report printing example:
#tst = [
#        ['a', '0.0.1', 'rule-1', []],
#        ['b', '1.0', None, [
#                ['c', '1.1', None, []],
#                ['d', '023', None, []]
#            ]],
#        ['e', '0.0.452', 'rule-2', [
#                ['f', '10.45', None, [
#                        ['g', 'Nov-23', 'rule-3', []],
#                        ['h', '1.0', None, []]
#                    ]],
#                ['i', '1.0', None, []]
#            ]]
#    ]
#
#if __name__ == "__main__":
#    print(protecting_rules_report(tst))

