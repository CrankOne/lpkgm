import os, logging, pickle

from lpkgm.utils import packages
from lpkgm.settings import gSettings

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
        dg = nx.DiGraph()
        deps = []
        for pkgData, pkgFilePath in packages():
            pkgName, pkgVer = pkgData['package'], pkgData['version']['fullVersion']
            dg.add_node((pkgName, pkgVer))
            for dep in pkgData['dependencies']:
                deps.append(( (pkgName, pkgVer)
                            , tuple(dep)
                            ))
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
        return list(item[0] for item in self.g.in_edges((pkgName, pkgVer)))

    def depends_on(self, pkgName, pkgVer):
        return list(item[1] for item in self.g.out_edges((pkgName, pkgVer)))

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

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        L = logging.getLogger(__name__)
        if self._dirty:
            self.save()
        else:
            L.debug('Dep.graph did not change.')

