import unittest
import lpkgm.dependencies
from lpkgm.protection import ProtectionRule, protecting_rules_report

class MockProtectionRule(ProtectionRule):
    def __init__(self, label='mock'):
        super().__init__(label)

    def __call__(self, *args, **kwargs):
        return True

class MockProtectionRuleVersionCheck(ProtectionRule):
    def __init__(self, version, label='mock'):
        self._version = version
        super().__init__(label)

    def __call__(self, version, time):
        return version == self._version

class TestDepPair(unittest.TestCase):
    # Simple case of two packages, foo depends from bar
    def setUp(self):
        self.depGraph = lpkgm.dependencies.PkgGraph(forceRebuild=False, filePath=f'/tmp/xxx.{__name__}.gpickle')
        self.depGraph.add( ('foo', '1.0.0'), ('bar', '1.0.0') )  # "foo" depends on "bar"

    def test_basic_dependencies_pair(self):
        # check dependencies are properly returned for this simple relation
        fooDeps = self.depGraph.depends_on('foo', '1.0.0')
        barDeps = self.depGraph.depends_on('bar', '1.0.0')
        self.assertEqual( len(fooDeps), 1 )  # "foo" has one dependency
        self.assertTrue(type(fooDeps[0]) in (list, tuple))
        self.assertEqual(len(fooDeps[0]), 2)
        self.assertEqual(fooDeps[0], ('bar', '1.0.0'))
        self.assertEqual( len(barDeps), 0 )  # "bar" has no dependencies

        barProvides = self.depGraph.dependency_of('bar', '1.0.0')
        self.assertEqual(len(barProvides), 1)
        self.assertEqual(barProvides[0], ('foo', '1.0.0'))


class TestDepTriplet(unittest.TestCase):
    # Dependency graph
    #
    #   C -> A   # C depends on A
    #    `-> B   # C depends on B
    #
    # Cases to be tested:
    #
    #   1. if C is protected, A and B are also protected (protection propagated)
    #   2. if only A/B is protected, C and B/A are not protected (protection isolated)
    #   3. if A and B are protected, C is not
    def setUp(self):
        self.depGraph = lpkgm.dependencies.PkgGraph(forceRebuild=False, filePath=f'/tmp/xxx.{__name__}.gpickle')
        self.depGraph.add( ('C', '1'), ('A', '1') )  # C depends on A
        self.assertEqual( self.depGraph.depends_on('C', '1'), [('A', '1')] )
        self.assertEqual( self.depGraph.dependency_of('A', '1'), [('C', '1')] )
        self.depGraph.add( ('C', '1'), ('B', '1') )  # C depends on B
        self.installedTimesCache = { ('A', '1'): 123
                                   , ('B', '1'): 123
                                   , ('C', '1'): 123 }  # mock

    def test_dependency_propagation(self):
        protectC = {'C': [MockProtectionRule()]}
        # test plain and recursive cases of 1st for C:
        for isRecursive in (False, True):
            cRules = self.depGraph.get_protecting_rules('C', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertTrue(cRules)  # make sure it casts to True
            self.assertEqual(cRules, ('C', '1', ['mock'], []))
        # test that A got protection from C
        aRules = self.depGraph.get_protecting_rules('A', '1', 0
                    , protectionRules=protectC
                    , recursive=True
                    , installedTimesCache=self.installedTimesCache
                    )
        #print('==>', aRules)  # XXX
        self.assertTrue(aRules)  # make sure it casts to True
        self.assertEqual(aRules, ('A', '1', [], [('C', '1', ['mock'], [])]))
        report = '\n' + protecting_rules_report(aRules[3])  # just test that it won't fail
        #print(report)
        # test that A is not protected logically when recursion is disabled
        aRules = self.depGraph.get_protecting_rules('A', '1', 0
                    , protectionRules=protectC, recursive=False)
        self.assertFalse(aRules)

    def test_dependency_isolation_single(self):
        protectC = {'A': [MockProtectionRule()]}
        # test plain and recursive cases of 1st for C:
        for isRecursive in (False, True):
            cRules = self.depGraph.get_protecting_rules('C', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertFalse(cRules)
            bRules = self.depGraph.get_protecting_rules('B', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertFalse(bRules)
            # test that A got protected by itself
            aRules = self.depGraph.get_protecting_rules('A', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertTrue(aRules)  # make sure it casts to True
            self.assertEqual(aRules, ('A', '1', ['mock'], []))

    def test_dependency_isolation_mult(self):
        protectC = {'A': [MockProtectionRule('mock-a')], 'B': [MockProtectionRule('mock-b')]}
        # test plain and recursive cases of 1st for C:
        for isRecursive in (False, True):
            cRules = self.depGraph.get_protecting_rules('C', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertFalse(cRules)
            # test that A and B got protected by themselves
            aRules = self.depGraph.get_protecting_rules('A', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertTrue(aRules)  # make sure it casts to True
            self.assertEqual(aRules, ('A', '1', ['mock-a'], []))

            bRules = self.depGraph.get_protecting_rules('B', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=self.installedTimesCache
                    )
            self.assertTrue(bRules)
            self.assertEqual(bRules, ('B', '1', ['mock-b'], []))

class TestGenericCase(unittest.TestCase):
    # Tests for somewhat generic case, when overall graph consists of three
    # isolated dependency graphs
    #
    #  (a, 1) <- (b, 1)
    #         `- (b, 2)
    #
    #  (a, 2) <- (b, 3) <- (c, 1)
    #
    #
    #  (a, 3) <-
    #  (d, 1) <-`- (c, 2)
    def setUp(self):
        self.depGraph = lpkgm.dependencies.PkgGraph(forceRebuild=False, filePath=f'/tmp/xxx.{__name__}.gpickle')
        # add first sub-graph
        self.depGraph.add( ('b', '1'), ('a', '1') )  # b/1 depends on a/1
        self.depGraph.add( ('b', '2'), ('a', '1') )  # b/2 depends on a/1
        # add second sub-graph
        self.depGraph.add( ('b', '3'), ('a', '2') )  # b/3 depends on a/2
        self.depGraph.add( ('c', '1'), ('b', '3') )  # c/1 depends on a/2
        # add third sub-graph
        self.depGraph.add( ('c', '2'), ('a', '3') )  # c/2 depends on a/3
        self.depGraph.add( ('c', '2'), ('d', '1') )  # ... and on d/1
        # mock installaed times
        self.installedTimesCache = dict((k, 123) for k in self.depGraph.g.nodes)
        # testing assets:
        # - all possible edges
        # not needed? testing weakly connected components in nx itself seems redundant
        #self.edges = {
        #    # 1st
        #    (('b', '1'), ('a', '1')),
        #    (('b', '2'), ('a', '1')),
        #    # 2nd
        #    (('b', '3'), ('a', '2')),
        #    (('c', '1'), ('b', '3')),
        #    # 3rd
        #    (('c', '2'), ('a', '3')),
        #    (('c', '2'), ('d', '1')),
        #}

    def _mock_removal(self, unprotected):
        # with those rules -- test removal sorting
        rmTiers = self.depGraph.sort_for_removal(unprotected)
        removedItems = set()
        for tier in rmTiers:
            for item in tier:
                # test, dependency is not broken:
                # - none of dependencies are removed (yet)
                deps = self.depGraph.dependency_of(*item)
                self.assertFalse(set(deps) & removedItems)
                # - provided packages are removed or not scheduled for removal
                provided = self.depGraph.depends_on(*item)
                for providedOne in provided:
                    self.assertTrue( providedOne in removedItems
                                  or providedOne not in unprotected)
                # "remove"
                removedItems.add(item)
        # make sure all removed
        self.assertEqual(removedItems, set(unprotected))

    def test_components_isolation(self):
        # test that we can actually see sub-graphs ("components" in nx
        # terminology)
        nSubGraphs = 0
        for comp in self.depGraph.isolated_subgraphs():
            self.assertEqual(len(list(comp.edges)), 2)  # all sub-graphs have only two edges
            nSubGraphs += 1
        self.assertEqual(nSubGraphs, 3)

    # test, how remove all behaves (no protected pkgs)
    def test_removal_sorting(self):
        rmTiers = self.depGraph.sort_for_removal([
            ('b', '1'), ('a', '1'),
            ('b', '3'), ('c', '1'), ('a', '2'),
            ('c', '2'), ('a', '3')
            ])
        self.assertEqual(len(rmTiers), 3)
        removed = set()
        for tier in rmTiers:
            if ('a', '1') in tier:
                # 1st sub-graph
                self.assertEqual(tier, [('a', '1'), ('b', '1')])
            elif ('b', '3') in tier:
                # 2nd sub-graph
                self.assertEqual(tier, [('a', '2'), ('b', '3'), ('c', '1')])
            elif ('c', '2') in tier:
                # 3rd sub-graph
                self.assertEqual(tier, [('a', '3'), ('c', '2')])
            else:
                assert False  # must not be reached

    def test_garbage_collection_1(self):
        # case with a-1, a-3, b-3 being protected
        protectionRules = {
                'a': [ MockProtectionRuleVersionCheck('1', 'mock-a-1')
                     , MockProtectionRuleVersionCheck('3', 'mock-a-3')
                     ],
                'b': [MockProtectionRuleVersionCheck('3', 'mock-b-3')],
            }
        # test 1st level protection
        directlyProtected = self.depGraph.get_protected_rules_by_pkg(
                protectionRules, self.installedTimesCache)
        self.assertEqual(directlyProtected, {('a', '1'): ['mock-a-1']
            , ('a', '3'): ['mock-a-3']
            , ('b', '3'): ['mock-b-3']
            })
        # test all protected pkgs
        allProtected = self.depGraph.get_protected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertEqual(allProtected, set([('a', '1'), ('a', '3'), ('b', '3'), ('a', '2')]))
        # test all not protected
        checkScheduledForRemoval = set([('b', '1'), ('b', '2')
            , ('c', '1')
            , ('d', '1')
            , ('c', '2')
            ])
        unprotected = self.depGraph.get_unprotected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertEqual(unprotected, checkScheduledForRemoval)
        self._mock_removal(unprotected)

    def test_garbage_collection_2(self):
        # case with b-1, c-1, c-2 being protected
        protectionRules = {
                'c': [ MockProtectionRuleVersionCheck('1', 'mock-c-1')
                     , MockProtectionRuleVersionCheck('2', 'mock-c-2')
                     ],
                'b': [MockProtectionRuleVersionCheck('1', 'mock-b-1')],
            }
        # test 1st level protection
        directlyProtected = self.depGraph.get_protected_rules_by_pkg(
                protectionRules, self.installedTimesCache)
        self.assertEqual(directlyProtected, {('c', '1'): ['mock-c-1']
            , ('c', '2'): ['mock-c-2']
            , ('b', '1'): ['mock-b-1']
            })
        # test all protected pkgs
        allProtected = self.depGraph.get_protected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertEqual(allProtected, set([('a', '1'), ('b', '1')
            , ('a', '2'), ('b', '3'), ('c', '1')
            , ('a', '3'), ('d', '1'), ('c', '2')
            ]))
        # test all not protected
        checkScheduledForRemoval = set([('b', '2')])
        unprotected = self.depGraph.get_unprotected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertEqual(unprotected, checkScheduledForRemoval)
        self._mock_removal(unprotected)

    def test_garbage_collection_trivial_all(self):
        # case with b-1, c-1, c-2 being protected
        protectionRules = {}  # no protection rules
        # test 1st level protection
        directlyProtected = self.depGraph.get_protected_rules_by_pkg(
                protectionRules, self.installedTimesCache)
        self.assertFalse(directlyProtected)
        # test all protected pkgs
        allProtected = self.depGraph.get_protected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertFalse(allProtected)
        # test all not protected
        checkScheduledForRemoval = set(self.depGraph.g.nodes)
        unprotected = self.depGraph.get_unprotected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertEqual(unprotected, checkScheduledForRemoval)
        self._mock_removal(unprotected)

    def test_garbage_collection_trivial_none(self):
        # case with b-1, c-1, c-2 being protected
        protectionRules = {
                'c': [ MockProtectionRuleVersionCheck('1', 'mock-c-1')
                     , MockProtectionRuleVersionCheck('2', 'mock-c-2')
                     ],
                'b': [ MockProtectionRuleVersionCheck('1', 'mock-b-1')
                     , MockProtectionRuleVersionCheck('2', 'mock-b-2')
                     ],
            }
        # test 1st level protection
        directlyProtected = self.depGraph.get_protected_rules_by_pkg(
                protectionRules, self.installedTimesCache)
        self.assertEqual(directlyProtected, {('c', '1'): ['mock-c-1']
            , ('c', '2'): ['mock-c-2']
            , ('b', '1'): ['mock-b-1']
            , ('b', '2'): ['mock-b-2']
            })
        # test all protected pkgs
        allProtected = self.depGraph.get_protected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertEqual(allProtected, set(self.depGraph.g.nodes))
        # test all not protected
        unprotected = self.depGraph.get_unprotected_pkgs(
                protectionRules, self.installedTimesCache)
        self.assertFalse(unprotected)
        self._mock_removal(unprotected)

