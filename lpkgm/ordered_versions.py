import copy
from collections import defaultdict

def convert_version_subnum(n):
    if n is None: return 0
    return int(n)

# ... other version subnum converters?

def converter_from_str(name):
    if 'convert_version_subnum' == name:
        return convert_version_subnum
    if 'literal' == name or 'identical' == name or 'identic' == name:
        return lambda x: x
    raise RuntimeError('Can not interpret conversion function'
            + f' name "{name}" in the version attribute reference')

def attr_item_to_getter(attrItem, default_cnv=convert_version_subnum):
    if type(attrItem) is str:
        return (attrItem, default_cnv)
    if type(attrItem) in (tuple, list) \
    and 2 == len(attrItem) \
    and type(attrItem[0]) is str:
        if type(attrItem[1]) is str:
            return attrItem[0], converter_from_str(attrItem[1])
        elif callable(attrItem[1]):
            return tuple(attrItem)
    raise RuntimeError('Can not interpret reference to version attribute.')


class VersionsOrder(object):
    """
    Based by attributes order and list of ortogonal version attributes, builds
    index of ordered versions.
    """
    defaultAttrsOrder=( ('major',  'convert_version_subnum')
                      , ('minor',  'convert_version_subnum')
                      , ('patch',  'convert_version_subnum')
                      , ('patch1', 'convert_version_subnum')
                      , ('patch2', 'convert_version_subnum')
                      , ('patch3', 'convert_version_subnum')
                      , ('_installTime', 'literal')
                      )
    defaultOrtogonalAttrs=(('buildConf', 'literal'),)

    def __init__( self
                , attributesOrder=None
                , ortogonalBy=None
                ):
        if not attributesOrder:
            attributesOrder = type(self).defaultAttrsOrder
        self._attrOrder = list(attr_item_to_getter(attr) for attr in attributesOrder)
        if ortogonalBy is None:
            ortogonalBy = type(self).defaultOrtogonalAttrs
        self._ortogonalBy = list(attr_item_to_getter(attr, default_cnv=lambda x: x) for attr in ortogonalBy)

    def canonic_version_tuple(self, pkgVer_, installTime=None):
        """
        Converts version object into "canonic version tuple". Returns (<flavour:tuple>, <version:tuple>)
        """
        # append with `_installTime' if (most probably) package version
        # was not artificially annotated with it
        pkgVer = copy.copy(pkgVer_)
        if '_installTime' not in pkgVer.keys(): pkgVer['_installTime'] = installTime
        ortoKeys = tuple(cnv(pkgVer_.get(k, None)) for k, cnv in self._ortogonalBy) if self.flavourKeys else None
        version  = tuple(cnv(pkgVer.get(k, None)) for k, cnv in self._attrOrder)
        # build key to sort by
        return ortoKeys, version 

    @property
    def flavourKeys(self):
        return list(c for c, _ in self._ortogonalBy) if self._ortogonalBy else [None,]

    def __call__(self, pkgVersionsAndDate):
        # build list of items: {(attrs...): pkgVerDict}
        versionsByOrtogonalAttr = defaultdict(dict)
        for pkgVer_, installTime in pkgVersionsAndDate:
            ortoKeys, verKey = self.canonic_version_tuple(pkgVer_, installTime)
            versionsByOrtogonalAttr[ortoKeys][verKey] = (pkgVer_, installTime)
        # Use tuple comparison to sort resulting "keys",
        # see "Lexicographical comparison" in
        #       https://docs.python.org/3/reference/expressions.html#value-comparisons
        # (TODO: test?)
        # leave only N most recent ones
        #self._protectedVersions = list(sorted(versions.keys()))[-self._limit:]
        result = {}
        for orthoKey, versions in versionsByOrtogonalAttr.items():
            yield orthoKey, list((k, versions[k]) for k in sorted(versions.keys()))
        

testVersions = [
    ({'major': 1,    'minor': 2,    'patch': None, 'commit': None      , 'buildConf': 'test'}, 123),
    ({'major': 1,    'minor': None, 'patch': 23,   'commit': 'deadbeef', 'buildConf': None  }, 325),
    ({'major': 1,    'minor': 0,    'patch':  1,   'commit': '12ef32ea', 'buildConf': None  }, 457),
    ({'major': 1,    'minor': 0,    'patch':  1,   'commit': '12ef32ea'                     }, 456),
]

if "__main__" == __name__:
    order = VersionsOrder(ortogonalBy=None)  # set to =[] to disable flavours
    for flavour, versions in order(testVersions):
        print(dict(zip(order.flavourKeys, flavour)))
        for vk, verObject in versions:
            print(' *', verObject)
    #
    order = VersionsOrder(ortogonalBy=[])
    for flavour, versions in order(testVersions):
        print(dict(zip(order.flavourKeys, flavour)))
        for vk, verObject in versions:
            print(' *', verObject)
