import os, logging, pickle, datetime, copy

from collections import defaultdict
from fnmatch import fnmatch

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

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        L = logging.getLogger(__name__)
        if self._dirty:
            self.save()
        else:
            L.debug('Dep.graph did not change.')

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

    def get_protecting_rules(self, pkgName, pkgVersion
            , protectionRules=None
            , recursive=True
            ):
        """
        Returns list of 3-element tuples:
            (pkgName:str, pkgStrVer:str ruleLabel:str, [<dependencies>])
        denoting reason of this package being protected from removal.
        First returned package name is always eponymous to the argument
        (`pkgName`), others ...
        Used mainly to generate output usable for report printing.
        """
        if type(pkgVersion) is dict:
            pkgVersion = pkgVersion['fullVersion']
        L = logging.getLogger(__name__)
        r = tuple()
        # if no protection rule covers this package
        protectedByRules = []
        for rule in protectionRules.get(pkgName, []):
            if rule(pkgVersion):
                protectedByRules.append(rule.label)
        if protectedByRules:
            r = ( pkgName
               , pkgVersion
               , protectedByRules
               , []
               )
        if not recursive: return r
        # do the recursive check
        # Get all the packages depending on given (packages this one provides),
        # append the rules list, if need
        rr = []
        for dpName, dpVer in self.dependency_of(pkgName, pkgVersion):
            # to get installed time of depending pkgs as we have to load
            # full manifest :(
            assert type(dpVer) is str  # only stringified versions must be stored in graph
            dpRules = self.get_protecting_rules(dpName, dpVer
                    , protectionRules=protectionRules
                    , recursive=True
                    )
            if dpRules:
                rr.append(dpRules)
        if rr:
            r = ( pkgName
                , pkgVersion
                , protectedByRules
                , rr
                )
        return r

    def isolated_subgraphs(self):
        #return nx.weakly_connected_component_subgraphs(self.g)  # no longer maintained starting from >~2.8
        for nodesSet in nx.weakly_connected_components(self.g):
            yield self.g.subgraph(list(nodesSet))

    def unprotected_items(self):
        """
        Returns set of items which are:
            1. not protected by any rule by themselves
            2. do not provide any protected dependee
        Useful for "garbage collection" (deleting orphaned unprotected packages
        and their unprotected dependencies).
        """
        for subGraph in self.isolated_subgraphs():
            # within isolated sub-graph, apply a recursive algorithm to collect
            # unprotected nodes
            pass

    def get_protected_rules_by_pkg(self, protectionRules):
        """
        Returns dict of nodes and list of its protecting rules. Nodes not covered
        by protection rule(s) will not be added to the resulting
        dictionary (important!)
        """
        def _get_protection_rules(pkgName, pkgVer, allRules):
            r = set()
            if pkgName not in allRules.keys(): return r
            for rule in allRules[pkgName]:
                if not rule(pkgVer): continue
                r.add(rule.label)
            return list(sorted(r))
        r = dict()
        for node in self.g.nodes:
            thisProtectingRules = _get_protection_rules(*node
                    , protectionRules
                    )
            if not thisProtectingRules: continue
            r[node] = thisProtectingRules
        return r

    def get_protected_pkgs(self, protectionRules):
        """
        Returns set of all (directly or indirectly) protected nodes
        """
        
        # build set of is-protected pkgs (ones directly protected by at least one
        # of the rule)
        protected1st = set(self.get_protected_rules_by_pkg(protectionRules).keys())
        protectedAll = copy.copy(protected1st)
        for protected1stPkg in protected1st:
            # get all dependencies of "directly protected" package and add it to
            # the protected ones (note, that `descendants returns ALL the
            # descendants of arbitrary depth, not only the immediate ones)
            for desc in nx.descendants(self.g, protected1stPkg):
                protectedAll.add(desc)
        return protectedAll

    def get_unprotected_pkgs(self, protectionRules):
        allNodes = set(self.g.nodes)
        return allNodes - self.get_protected_pkgs(protectionRules)

    def get_matching_pkgs(self, pkgNamePat, pkgVerPat='*', protectionRules=None):
        L = logging.getLogger(__name__)
        if not protectionRules: protectionRules={}
        r = []
        for node in self.g.nodes:
            if not fnmatch(node[0], pkgNamePat):
                L.debug(f'{node[0]}/{node[1]} does not match pkg name "{pkgNamePat}"')
                continue  # doesn't match selection by name
            if pkgVerPat and not fnmatch(node[1], pkgVerPat):
                L.debug(f'{node[0]}/{node[1]} does not match version "{pkgVerPat}"')
                continue  # doesn't match sel by ver
            if protectionRules:
                protected = False
                if node[0] in protectionRules.keys():
                    for rule in protectionRules[node[0]]:
                        if not rule(node[1]): continue
                        protected = True  # got protection by at least one of the rules
                        L.debug(f'{node[0]}/{node[1]} is protected by rule "{rule.label}"')
                        break
                if protected: continue  # protected one
            L.debug(f'{node[0]}/{node[1]} match')
            r.append(node)
        return r

    def sort_for_removal(self, pkgs_):
        """
        Sorts given iterable `pkgs` for removal in a way that dependee always
        go before its dependency -- so that dependencies tree is kept
        consistent upon failures.
        """
        pkgs = set(pkgs_)
        tiers = []
        while pkgs:
            tgt = None
            for subGraphLarge in self.isolated_subgraphs():
                subPkgs = set(subGraphLarge.nodes) & pkgs
                if subPkgs:
                    tgt = subPkgs
                    break
            if not tgt:
                raise RuntimeError('No sub-graph found for any node of:'
                        + ', '.join(f'{nm}/{ver}' for (nm, ver) in pkgs) )  # TODO: details
            # got match with current subgraph and can remove some packages;
            pkgs -= tgt  # pull the "removed" ones
            # get sub-graph of to-remove nodes
            subGraphToRemove = self.g.subgraph(list(tgt))
            # put new tier as depth-first post-order
            tiers.append(list(nx.dfs_postorder_nodes(subGraphToRemove)))
        return tiers


def show_tree(outStream, pkgName, pkgVerStr, depGraph):
    # TODO: if pkgName and/or pkgVer is given, retrieve subtree
    nx.write_network_text(depGraph.g)
    #print(dg.in_edges(('xz', '5.6.2-opt')))  # input edges means that this package is a dep for smt other

