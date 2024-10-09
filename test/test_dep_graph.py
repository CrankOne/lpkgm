import unittest
import lpkgm.dependencies
from lpkgm.protection import ProtectionRule, protecting_rules_report

class MockProtectionRule(ProtectionRule):
    def __init__(self, label='mock'):
        super().__init__(label)

    def __call__(self, *args, **kwargs):
        return True

class TestDepGraph(unittest.TestCase):
    def test_basic_dependencies_pair(self):
        depGraph = lpkgm.dependencies.PkgGraph(forceRebuild=False, filePath=f'/tmp/xxx.{__name__}.gpickle')
        depGraph.add( ('foo', '1.0.0'), ('bar', '1.0.0') )  # "foo" depends on "bar"

        # check dependencies are properly returned for this simple relation
        fooDeps = depGraph.depends_on('foo', '1.0.0')
        barDeps = depGraph.depends_on('bar', '1.0.0')
        self.assertEqual( len(fooDeps), 1 )  # "foo" has one dependency
        self.assertTrue(type(fooDeps[0]) in (list, tuple))
        self.assertEqual(len(fooDeps[0]), 2)
        self.assertEqual(fooDeps[0], ('bar', '1.0.0'))
        self.assertEqual( len(barDeps), 0 )  # "bar" has no dependencies

        barProvides = depGraph.dependency_of('bar', '1.0.0')
        self.assertEqual(len(barProvides), 1)
        self.assertEqual(barProvides[0], ('foo', '1.0.0'))

    def test_protection_triplet(self):
        # Dependency graph
        #
        #   C -> A   # C depends on A
        #    `-> B   # C depends on B
        #
        # Cases to be tested:
        #
        #   1. if C is protected, A and B are also protected
        #   2. if only A is protected, C and B are not protected
        depGraph = lpkgm.dependencies.PkgGraph(forceRebuild=False, filePath=f'/tmp/xxx.{__name__}.gpickle')
        depGraph.add( ('C', '1'), ('A', '1') )  # C depends on A
        self.assertEqual( depGraph.depends_on('C', '1'), [('A', '1')] )
        self.assertEqual( depGraph.dependency_of('A', '1'), [('C', '1')] )
        depGraph.add( ('C', '1'), ('B', '1') )  # C depends on B
        installedTimesCache = { ('A', '1'): 123
                              , ('B', '1'): 123
                              , ('C', '1'): 123 }  # mock
        # check 1st
        protectC = {'C': [MockProtectionRule()]}
        # test plain and recursive cases of 1st for C:
        for isRecursive in (False, True):
            cRules = depGraph.get_protecting_rules('C', '1', 0
                    , protectionRules=protectC
                    , recursive=isRecursive
                    , installedTimesCache=installedTimesCache
                    )
            self.assertTrue(cRules)  # make sure it casts to True
            self.assertEqual(cRules, ('C', '1', ['mock'], []))
        # test that A got protection from C
        aRules = depGraph.get_protecting_rules('A', '1', 0
                    , protectionRules=protectC
                    , recursive=True
                    , installedTimesCache=installedTimesCache
                    )
        #print('==>', aRules)  # XXX
        self.assertTrue(aRules)  # make sure it casts to True
        self.assertEqual(aRules, ('A', '1', [], [('C', '1', ['mock'], [])]))
        report = '\n' + protecting_rules_report(aRules[3])  # just test that it won't fail
        #print(report)
        # test that A is not protected logically when recursion is disabled
        aRules = depGraph.get_protecting_rules('A', '1', 0
                    , protectionRules=protectC, recursive=False)
        self.assertFalse(aRules)
