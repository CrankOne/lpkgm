from pkg_ver import parse_pkg_ver

import unittest

def compare_dicts_1st_level(a, b):
    if len(a) != len(b): return False
    for k, v in a.items():
        if k not in b: return False
        if v != b[k]: return False
    return True

#
# Test package version parsing

class TestPkgVersionParse(unittest.TestCase):
    """
    Test package version parsing routine.
    """
    def test_buildconf_and_commit(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('p348-daq.dbg.c3edf12')
                , {
                    'pkgName': 'p348-daq',
                    'buildConf': 'dbg',
                    'commit': 'c3edf12'
                }
            ) )

    def test_mj_mn_ver(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('p348-daq-0.41')
                , {
                    'pkgName': 'p348-daq',
                    'major': '0',
                    'minor': '41'
                }
            ) )

    def test_mj_mn_patch_ver(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('p348-daq-0.4.132')
                , {
                    'pkgName': 'p348-daq',
                    'major': '0',
                    'minor': '4',
                    'patchNum': '132'
                }
            ) )

    def test_buildconf_commit_and_flavour(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('p348-daq-3f45ac-45-standalone-lib.opt')
                , {
                    'pkgName': 'p348-daq',
                    'commit': '3f45ac',
                    'buildConf': 'opt',
                    'flavour': '45-standalone-lib'
                }
            ) )

    def test_buildconf_mj_and_commit(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('my-fancy-lib.v5-ae459f12')
                , {
                    'pkgName': 'my-fancy-lib',
                    'major': '5',
                    'commit': 'ae459f12',
                }
            ) )

    def test_buildconf_mj_mn_commit_and_flavour(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('na64sw-0.4.1-3f45ace-dev/45-standalone-lib.opt')
                    , {
                    'pkgName': 'na64sw',
                    'major': '0',
                    'minor': '4',
                    'patchNum': '1',
                    'commit': '3f45ace',
                    'flavour': 'dev/45-standalone-lib',
                    'buildConf': 'opt'
                }
            ) )

    def test_hyphen(self):
        self.assertTrue( compare_dicts_1st_level(
                parse_pkg_ver('orocos-log4cpp-2.3.4.opt')
                    , {
                    'pkgName': 'orocos-log4cpp',
                    'major': '2',
                    'minor': '3',
                    'patchNum': '4',
                    'buildConf': 'opt'
                }
            ) )

if '__main__' == __name__:
    #for s in gTestPkgVersionStrings:
    #    print(f'under testing \"{s}\":')
    #    parse_package_name_w_version(s)
    unittest.main()

