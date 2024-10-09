import os, logging, pickle, datetime

from collections import defaultdict

from lpkgm.utils import packages
from lpkgm.settings import gSettings
from lpkgm.utils import get_package_manifests

# networkx warning workaround (need only for Python 3.9)
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="networkx backend defined more than once: nx-loopback")
    import networkx as nx
#import networkx as nx

class PkgGraph(object):
    """
    Wrapper on networkx graph representing package dependencies.

    This graph is used to cache dependency relations claimed by package
    manifests, speeding up querying for dependencies/dependees.
    """
    def _build_dep_graph(self):
        """
        Generates networkx graph of dependencies based on package
        manifest files.
        """
        L = logging.getLogger(__name__)
        dg = nx.DiGraph()
        deps = []
        for pkgData, pkgFilePath in packages():
            pkgName, pkgVer = pkgData['package'], pkgData['version']['fullVersion']
            # add node to graph
            dg.add_node((pkgName, pkgVer))
            for dep in pkgData['dependencies']:
                deps.append(( (pkgName, pkgVer)
                            , tuple(dep)
                            ))
        # connect dependencies
        for depRel in deps:
            dg.add_edge(*depRel)
        return dg

    def __init__(self, forceRebuild=False, filePath=None):
        """
        Deserializes or builds global dependency graph.
        """
        L = logging.getLogger(__name__)
        if filePath:
            self._filePath = filePath
        else:
            self._filePath = os.path.join(gSettings['packages-registry-dir'], 'deps.nx.gpickle')
        if os.path.isfile(self._filePath) and not forceRebuild:
            # read cached
            L.debug(f'Using dependencies graph cache from {self._filePath}')
            with open(self._filePath, 'rb') as f:
                self.g = pickle.load(f)
            self._dirty = False
        else:
            # otherwise -- rebuild and save cache
            L.debug("Re-generating dependencies graph.")
            self.g = self._build_dep_graph()
            # we do not save cache immediately. This allows one to build in-memory
            # cache for read-only FS (e.g. CVMFS in userspace)
            #self.save()
            self._dirty = True

    def save(self):
        L = logging.getLogger(__name__)
        L.debug(f'Dependencies graph cached at {self._filePath}')
        with open(self._filePath, 'wb') as f:
            pickle.dump(self.g, f, pickle.HIGHEST_PROTOCOL)

    def dependency_of(self, pkgName, pkgVer):
        pv = pkgVer if type(pkgVer) is str else pkgVer['fullVersion']
        return list(item[0] for item in self.g.in_edges((pkgName, pv)))

    def depends_on(self, pkgName, pkgVer):
        pv = pkgVer if type(pkgVer) is str else pkgVer['fullVersion']
        return list(item[1] for item in self.g.out_edges((pkgName, pv)))

    def add(self, pkg1, pkg2):
        """
        Adds dependency meaning "pkg1 depends on (needs) pkg2"
        """
        self.g.add_edge(tuple(pkg1), tuple(pkg2))
        self._dirty = True

    def remove(self, pkg1, pkg2):
        """
        Removes dependency relation. Meaning "pkg1 does not depend on (don't need) pkg2"
        """
        self.g.remove_edge(tuple(pkg1), tuple(pkg2))
        self._dirty = True

    def remove_mult(self, ebunch):
        self.g.remove_edges_from(ebunch)
        self._dirty = True

    def remove_pkg(self, pkgName, pkgVer, force=False):
        """
        Removes package entry. Note, that all the dependency relation in
        which removed package is included will be removed as well.
        """
        L = logging.getLogger(__name__)
        L.debug(f'Removing pkg {pkgName}/{pkgVer} from deps. graph.')
        for dep in self.depends_on(pkgName, pkgVer):
            # This messages are used to detect possible inconsistencies in
            # the package removal process as these edges must be already
            # removed from graph (just a precaution)
            L.warning(f'Dep. graph remnant dependency will be forgotten:'
                    + f' {pkgName}/{pkgVer} depends on {dep[0]}/{dep[1]}')
        self.g.remove_node((pkgName, pkgVer))
        self._dirty = True

    def add_pkg(self, pkgName, pkgVer):
        self.g.add_node((pkgName, pkgVer))
        self._dirty = True

    def get_protecting_rules(self, pkgName, pkgVersion, installTime
            , protectionRules=None
            , recursive=True
            , r=None
            ):
        """
        Returns list of 3-element tuples:
            (pkgName:str, pkgStrVer:str ruleLabel:str)
        denoting reason of this package being protected from removal.
        If `recursive` is `False`, returned
        package name is always eponymous to the argument (`pkgName`),
        otherwise depenant packages can be pulled in.
        """
        if r is None:
            r = []
        if not recursive:
            if not protectionRules:
                # makes no sense -- current package without any protection
                # rules and without dependencies
                return r
            # for non-recursive check, make sure no protection rule covers
            # this package
            if pkgName not in protectionRules.keys():
                # no protection rule(s) covering this pkg
                return r
            protectedByRules = []
            for rule in protectionRules[pkgName]:
                if rule(pkgVersion, installTime):
                    protectedByRules.append(rule.label)
            r.append(pkgName, pkgVersion['fullVersion'], protectedByRules, [])
            return r
        # do the recursive check
        # Get all the packages depending on given, append the rules list
        for dpName, dpVer in self.dependency_of(pkgName, pkgVersion if type(pkgVersion) is str else pkgVersion['fullVersion']):
            rr = []
            # to get installed time of depending pkgs as we have to load full manifest :(
            dpData = get_package_manifests(dpName, dpVer)
            assert len(dpData) == 1
            dpData = dpData[0]
            dpInstalledAt = datetime.datetime.fromisoformat(dpData['installedAt'])
            self.get_protecting_rules(dpName, dpVer, dpInstalledAt
                    , protectionRules=protectionRules
                    , recursive=True, r=rr
                    )
            r.append((dpName, dpVer, None, rr))
        return r

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        L = logging.getLogger(__name__)
        if self._dirty:
            self.save()
        else:
            L.debug('Dep.graph did not change.')

def show_tree(outStream, pkgName, pkgVerStr, depGraph):
    # TODO: if pkgName and/or pkgVer is given, retrieve subtree
    nx.write_network_text(depGraph.g)
    #print(dg.in_edges(('xz', '5.6.2-opt')))  # input edges means that this package is a dep for smt other


def remove_unprotected_packages(depGraph, protectionRules):
    """
    Figures out packages that one can safely remove:
        1. Package is not protected one
        2. Package does not provide (is not dependency of) any protected package
    One has to be aware of order of these packages -- dependee should be removed
    first.
    """
    raise NotImplementedError('TODO: gc')
    # look for isolated sub-graphs
    pass
