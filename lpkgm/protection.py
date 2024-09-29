import lpkgm.ordered_versions
import io

class ProtectionRule(object):
    """
    A "protection rule" object is applied to set of eponymous packages (i.e.
    packages that are different only by their versions) to figure out whether
    the particular package (i.e. pkg name + pkg version) is "protected". This
    information is used then to test if particular package(s) can be removed.

    This is an abstract base class for protection rules.
    """
    def __init__(self, label='abstract'):
        self._label = label

    @property
    def label(self):
        return self._label

    def __call__(self, pkgVersion, installTime):
        raise NotImplementedError('Abstract protection rule in use (call).')

    def account_versions(self, versionsAndTime):
        raise NotImplementedError('Abstract protection rule in use (account_versions).')

#                       * * *   * * *   * * *

class KeepAll(ProtectionRule):
    """
    Protection rule that keeps all the packages provided.
    """
    def __init__(self, label):
        super().__init__(label)

    def __call__(self, pkgVersion, installTime):
        return True

    def account_versions(self, versionsAndTime):
        pass
#                       * * *   * * *   * * *

class KeepNone(ProtectionRule):
    """
    Abstract protection rule that does not keep all the packages provided.
    """
    def __init__(self, label):
        super().__init__(label)

    def __call__(self, pkgVersion, installTime):
        return False

    def account_versions(self, versionsAndTime):
        pass

#                       * * *   * * *   * * *

class KeepLatestProtectionRule(ProtectionRule):
    """
    Protects latest N versions of the package.
    """
    def __init__( self
                , label='latest'
                , attrsOrder=None
                , flavourFrom=None
                , latestLimit=1
                ):
        assert latestLimit
        super().__init__(label)
        self._limit = latestLimit
        self._order = lpkgm.ordered_versions.VersionsOrder(
                attributesOrder=attributesOrder,
                ortogonalBy=flavourFrom
                )
        self._sorted = {}

    def account_versions(self, versionsAndTime):
        self._order(versionsAndTime)

    def __call__(self, pkgVersion, installTime):
        fl, ver = self._order.canonic_version_tuple(pkgVersion, installTime=installTime)
        return ver in self._sorted[fl]

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

    Note, that protection rules does not take into account dependency tree
    propagation.
    """
    packagesByName = defaultdict(list)  # for protection rules
    for pkgData, pkgFilePath in packages():
        # append packages dict
        packagesByName[pkgName].append(
                ( pkgData['version']['fullVersion']
                , datetime.datetime.fromisoformat(pkgData['installedAt'])
                )
            )
    # for every package definition in settings, construct protection rule,
    # taking into account collected version history
    protectionRules = {}
    for pkgName, pkgDef in gSettings['packages'].items():
        pkgProtectionRules = []
        if 'protection-rules' not in pkgDef.keys():
            L.debug(f'No protection rules for package {pkgName}')
            continue
        if pkgName not in packagesByName.keys():
            L.debug(f'Package {pkgName} not installed -- ignoring protection rule')
            continue
        # instantiate protection rules and init them with installed
        # packages data
        for ruleDescription in pkgDef['protection-rules']:
            rule = instantiate_protection_rule(**ruleDescription)
            rule.account_versions(packagesByName[pkgName])
            pkgProtectionRules.append(rule)
            L.info(f'Package "{pkgName}" protected with rule "{rule.label}"')
        protectionRules['pkgName'] = pkgProtectionRules
    return protectionRules

#                       * * *   * * *   * * *

def protecting_rules_report(items, indent=0):
    returnValue = False
    f = io.StringIO("")

    for peName, peVer, peRule, peSub in items:
        f.write('    '*indent + f'"{peName}-{peVer}"')
        if peRule:
            f.write(f' is protected by "{peRule}"')
        if peSub:
            f.write((' and' if peRule else '') + ' provides packages:\n')
            f.write(protecting_rules_report(peSub, indent=indent+1))
        else:
            f.write('\n')
    return f.getvalue()

tst = [
        ['a', '0.0.1', 'rule-1', []],
        ['b', '1.0', None, [
                ['c', '1.1', None, []],
                ['d', '023', None, []]
            ]],
        ['e', '0.0.452', 'rule-2', [
                ['f', '10.45', None, [
                        ['g', 'Nov-23', 'rule-3', []],
                        ['h', '1.0', None, []]
                    ]],
                ['i', '1.0', None, []]
            ]]
    ]

if __name__ == "__main__":
    print(protecting_rules_report(tst))

