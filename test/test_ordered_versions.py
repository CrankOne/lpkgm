import unittest
import lpkgm.ordered_versions

testVersions = [
    ({'major': 1,    'minor': 2,    'patch': None, 'commit': None      , 'buildConf': 'test'}, 123),
    ({'major': 1,    'minor': None, 'patch': 23,   'commit': 'deadbeef', 'buildConf': None  }, 325),
    ({'major': 1,    'minor': 0,    'patch':  1,   'commit': '12ef32ea', 'buildConf': None  }, 457),
    ({'major': 1,    'minor': 0,    'patch':  1,   'commit': '12ef32ea'                     }, 456),
]

class TestOrderedVersions(unittest.TestCase):
    def test_sorting_order_no_orto(self):
        order = lpkgm.ordered_versions.VersionsOrder(ortogonalBy=[])
        ls_ = list(order(testVersions))
        self.assertEqual(1, len(ls_))  # by ortogonal
        flv, ls = ls_[0]
        # first element, (1.0.1, t=456)
        k, verVal = ls[0]
        verDict, t = verVal
        self.assertEqual(t, 456)
        # last element, (1.2.0, 123)
        k, verVal = ls[3]
        verDict, t = verVal
        self.assertEqual(t, 123)

    def test_sorting_order_default_orto(self):
        order = lpkgm.ordered_versions.VersionsOrder(ortogonalBy=None)
        for flavour, versions in order(testVersions):
            flv = dict(zip(order.flavourKeys, flavour))
            self.assertIn('buildConf', flv.keys())
            if flv['buildConf'] is None:
                l = list(versions)
                self.assertEqual(len(l), 3)
                self.assertEqual(l[0][1][1], 456)
                self.assertEqual(l[2][1][1], 325)
            else:
                self.assertEqual(flv['buildConf'], 'test')
                l = list(versions)
                self.assertEqual(len(l), 1)
                self.assertEqual(l[0][1][1], 123)
            
