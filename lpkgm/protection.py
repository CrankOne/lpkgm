import lpkgm.ordered_versions

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
        raise NotImplementedError('Abstract protection rule in use.')

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

