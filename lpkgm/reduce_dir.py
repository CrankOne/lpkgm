#!/usr/bin/env python
"""
This Python script recursively walks in the given subject directory collecting
hashsums of files and sub-directories. Collected index is used then to reveal
duplicating entries with respect to same dir content or some another directory
considered as "original".

Simplest possible usage scenario is very similar to ``rmlint -D`` --
within a subtree of a single dir (subject dir), duplicating files will be
substituted by hardlinks. It is also possible to reveal identical directories
and substitute it with symlinks.

Being used against two directories (subject dir and base dir) will generate a
recursive difference object, (resembling to Python's standard ``filecmp.dircmp()``).
One can use this difference object then to substitute files and directories in
2nd dir by links leading to 1st (thus, turning 2nd dir to an "incrmental
snapshot" with respect to 1st).

It is also possible to invoke the module with three directories (subject dir,
base dir and destination dir) in order to preserve subject dir as is and have
"incremental snapshot" elsewhere.

Can generate two types of the byproducts: 1) a report containing summary of the
modifications or duplicating entries list and 2) serialized diff object (as
a JSON or Python pickle) for inspection or subsequent use.

All modes permit dry run, the difference object can be saved for inspection
or subsequent use.
"""
# TODO: files/dirs filtering -- globbing, omit empty, etc
# TODO: handle permissions, owner information and modification time
# TODO: print details (e.g. modification time) in the report near to entries
# TODO: unit tests
# TODO: turn in-memory lists and sets into tables in DB to handle really large
#       subtrees, provide progress indication, etc

import os, sys, copy
import glob, base64, hashlib, filecmp, pathlib, json, copy, logging \
     , itertools, shutil, gzip, pickle, functools, fnmatch

#import sqlite3  # TODO: optional

def file_md5(path, stack=None):
    """
    For given file, calculates MD5 sum, returns its stringified digest.
    """
    if not stack: stack = []
    with open(path, "rb") as f:
        fileHash = hashlib.md5()
        while chunk := f.read(8192):
            fileHash.update(chunk)
            for s in stack:
                s.update(chunk)
    return fileHash.digest()

def files_stats_in(pattern):
    """
    For given shell wildcard pattern, returns recursive scan of the directory,
    containing tuples with: (path, size, md5sum).
    """
    for filePath in glob.glob(pattern):
        if not os.path.isfile(filePath):
            continue
        size = os.path.getsize(filePath)
        md5sum = file_md5(filePath)
        yield (filePath, size, md5sum)

def are_hardlinked(a, b):
    if not (os.path.isfile(a) and os.path.isfile(b)): return False
    return os.path.samefile(a, b) or (os.stat(a).st_ino == os.stat(b).st_ino)

def is_subpath_of(subj, parent, ifSame=True):
    subj   = os.path.normpath(subj)
    parent = os.path.normpath(parent)
    if subj == parent: return ifSame
    return subj.startswith(parent)

def dfs_fs_items( path
                , root=None
                , symlinks='consider'
                , yieldFiles=True, yieldDirs=True
                , filesFilter=None, dirsFilter=None
                , md5Stack=None, sizesStack=None
                , _cache=None
                ):
    """
    Iterates FS subtree entries recursively in depth-first search (DFS) order.
    Yielded tuple:
        (type:'d|f|l', path:str, md5-digest:bytes, size:int)

    Use ``filesFilter`` and ``dirsFilter`` callables to omit certain files and
    direcotries. These callables are invoked
    with absolute path and shall return whether or not file or directory is
    considered.
    """
    assert symlinks in ('consider', 'dereference', 'ignore')
    if root is None: root = path
    if md5Stack is None:    md5Stack = [hashlib.md5(),]
    if sizesStack is None:  sizesStack = [0,]
    fsItems = os.listdir(path)
    files, dirs, links = [], [], []
    for item in fsItems:
        p = os.path.join(path, item)
        if os.path.islink(p):
            if 'consider' == symlinks:
                links.append(item)
            if symlinks in ('consider', 'ignore'):
                continue
            else:
                assert symlinks == 'dereference'
                p = os.path.abspath(p)
        if os.path.isfile(p):
            files.append(item)
            continue
        if os.path.isdir(p):
            dirs.append(item)
            continue
    for dirItem in dirs:
        if dirsFilter and not dirsFilter(os.path.join(path, dirItem)): continue  # omit dir
        md5Stack.append(hashlib.md5())
        sizesStack.append(0)
        yield from dfs_fs_items(os.path.join(path, dirItem), root=root
            , yieldFiles=yieldFiles, yieldDirs=yieldDirs
            , filesFilter=filesFilter, dirsFilter=dirsFilter
            , md5Stack=md5Stack, sizesStack=sizesStack
            , _cache=_cache
            )
        relPath = os.path.relpath(os.path.join(path, dirItem), root)
        r = ('d', relPath, md5Stack[-1].digest(), sizesStack[-1], None)
        if _cache: _cache.add(*r)
        if yieldDirs: yield r
        md5Stack.pop()
        sizesStack.pop()
    for fileItem in files:
        absPath = os.path.join(path, fileItem)
        md5 = file_md5(absPath, stack=md5Stack)
        relPath = os.path.relpath(absPath, root)
        size = os.path.getsize(absPath)
        for n in range(len(sizesStack)):
            sizesStack[n] += size
        if not filesFilter or filesFilter(absPath):
            r = ('f', relPath, md5, size, None)
            if _cache: _cache.add(*r)
            if yieldFiles: yield r
    for linkItem in links:
        absPath = os.path.join(path, linkItem)
        relPath = os.path.relpath(absPath, root)
        r = ('l', relPath, None, None, os.path.normpath(os.readlink(absPath)))
        if _cache: _cache.add(*r)
        yield r
        # ^^^ NOTE: readlink always resolves only 1 lvl


#class MemoryFSCache(object):
#    """
#    Caches directories lookup and files comparison results.
#    Simple in-memory cache object.
#    Primitive and reasonably fast. Will not be sufficient for really large
#    directory scans (use DB-based implementation).
#    """
#    def __init__(self, **kwargs):
#        pass
#
#    def add(self):
#        pass

#class DBCachedFSItems(object):
#    def __init__(self, iterable, dbPath=None):
#        self._open_db(dbPath)
#        # fill from iterable
#
#    def _open_db(self, dbPath=None):
#        if dbPath is None: dbPath = ':memory:'
#        self._con = sqlite3.connect(dbPath)
#        cur = self._con.cursor()
#
#        cmd = 'CREATE TABLE IF NOT EXISTS fsitems (' \
#            + 'parent INT, type INT, path TEXT, size INT, md5sum BLOB, linkdest TEXT);'
#        cur.execute(cmd)
#
#        cmd = 'CREATE TABLE IF NOT EXISTS matches (' \
#            + 'a INT, b INT;'
#        cur.execute(cmd)

def find_duplicates_in( path
        , reduceDirs=True
        , **kwargs
        ):
    """
    Finds duplicating files and directories in the FS subtree starting from
    given path.

    Note, that if ``reduceDirs`` is set, it will avoid injecting
    ``a/foo.txt`` and ``b/foo.txt`` when ``a/`` and ``b/`` are duplicating
    directories, it still will provide `b/foo.txt` and `b/bar.txt` if these
    two files are duplicates (identical files within a dir which, in order,
    identical to another dir).

    TODO: switchg to DB or DB-like interface may severely affect this code...
    """
    L = logging.getLogger(__name__)
    # collect items with matching size and md5 sum
    itemsBySizeAndMD5 = {}
    fsItems = list(dfs_fs_items(path, **kwargs))  # cache subtree iteration result
    for fsType, relPath, md5, size, _ in fsItems:
        if fsType == 'l':
            # Links does not affect the similarity here (directories with matching
            # size and md5 and different links will be compared anyway)
            continue
        k = (fsType, size, md5)
        if k in itemsBySizeAndMD5:
            itemsBySizeAndMD5[k].append(relPath)
        else:
            itemsBySizeAndMD5[k] = [relPath,]
    # process possibly identic dirs: to identify two or more directories as
    # identical we require them all to have the same subtree
    maybeIdenticDirs = {}
    identicalDirs = []
    if reduceDirs:
        for (t, size, md5), candidates in itemsBySizeAndMD5.items():
            if 'd' == t: maybeIdenticDirs[(size, md5)] = copy.copy(candidates)
        for (_, md5), paths in maybeIdenticDirs.items():
            for a, b in itertools.combinations(paths, 2):
                # TODO: check if symbolic links to each other
                fullPathA = os.path.join(path, a)
                fullPathB = os.path.join(path, b)
                dirDiff = DirDiff( fullPathA
                                 , fullPathB
                                 , **kwargs)
                # ^^^ TODO: benefit from cache
                if dirDiff.isIdentical:
                    L.debug(f'Identical directories: {a} and {b}')
                    added = False
                    for group in identicalDirs:
                        if a in group or b in group:
                            group.add(a)
                            group.add(b)
                            added = True
                    if not added:
                        identicalDirs.append(set([a, b]))
                else:
                    L.debug('Directories differ although size and'
                            + f' hashsums match: {a} and {b}')
    # among matching file items, perform direct comparison to obtain identical
    # files
    identicalFiles = []
    for (t, size, md5), candidates in itemsBySizeAndMD5.items():
        if 'f' != t: continue
        if len(candidates) == 1: continue  # omit unique items
        equivalents = []
        # iterate over all pairwise combinations of files, possibly omitting
        # cases from duplicating dirs
        # TODO: code seems dirty and bogus, rethink/rewrite
        for pair in itertools.combinations(candidates, 2):
            if reduceDirs:
                fromDupDir = False
                dirA = os.path.dirname(pair[0])
                dirB = os.path.dirname(pair[1])
                # check, if pair of files belongs to duplicating dir
                for group in identicalDirs:
                    #assert len(group) > 2
                    if dirA in group and dirB in group:
                        fromDupDir = True
                        break
                if fromDupDir:
                    L.debug('Skipping identical files from duplicating'
                                + f' directories: {pair[0]}, {pair[1]}')
                    continue
            a = os.path.join(path, pair[0])
            b = os.path.join(path, pair[1])
            if filecmp.cmp(a, b, shallow=False):
                # a and b are identical -- true duplicate -- find appropriate
                # set with equivalents and append it
                appended = False
                for c in equivalents:
                    if a in c:
                        c.add(b)
                        appended = True
                        break
                    if b in c:
                        c.add(a)
                        appended = True
                        break
                if not appended:
                    equivalents.append(set([a, b]))
            else:
                # a and b actually different, despite their size and md5 match
                # This is a noteworthy event to be printed.
                L.info('Note: files have same MD5 sum and size, but'
                        + f' differ in their content: "{a}" and "{b}"')
                # - a
                appended = False
                for c in equivalents:
                    if a in c:
                        c.add(a)
                        appended = True
                        break
                if not appended:
                    equivalents.append(set([a,]))
                # - b
                appended = False
                for c in equivalents:
                    if b in c:
                        c.add(b)
                        appended = True
                        break
                if not appended:
                    equivalents.append(set([b,]))
        # equivalents now has groups if identical files (including trivial ones
        # with unique files)
        for identicalFilesSubGroup in equivalents:
            if len(identicalFilesSubGroup) == 1: continue  # omit trivial ones
            identicalFiles.append(identicalFilesSubGroup)
    return identicalFiles, identicalDirs

def _resolve_source(items, sourceResolvers, fsItemsStr=None):
    L = logging.getLogger(__name__)
    for srName, sr in sourceResolvers:
        orig = sr(sorted(items))
        if orig and type(orig) in (list, tuple) and 1 == len(orig):
            orig = orig[0]
        if type(orig) is str:
            L.debug('%s group %s resolved into %s by rule "%s"'%(
                'FS items' if fsItemsStr is None else fsItemsStr
                , ', '.join(sorted(items)), orig, srName))
            return orig, srName
    return None, None

def write_duplicates_report_ascii(stream
        , duplicates
        , sourceResolvers=None
        , forceKeep=None
        ):
    if duplicates:
        if not sourceResolvers: sourceResolvers = []
        if not forceKeep: forceKeep = []
        for nGroup, dups in enumerate(sorted(duplicates[0])):
            assert dups
            orig, srName = _resolve_source( dups, sourceResolvers, fsItemsStr='Files')
            stream.write(f'# files group #{nGroup}:\n')
            for dupItem in sorted(dups):
                if dupItem != orig:
                    if dupItem in forceKeep:
                        stream.write(f' == {dupItem}\n')
                    else:
                        stream.write(f'    {dupItem}\n')
                else:
                    stream.write(f' -> {dupItem} (choosen by "{srName}")\n')
        if not duplicates[0]:
            stream.write('# no duplicating files\n')
        for nGroup, dups in enumerate(sorted(duplicates[1])):
            assert dups
            orig, srName = _resolve_source( dups, sourceResolvers, fsItemsStr='Dirs')
            stream.write(f'# directories group #{nGroup}:\n')
            for dupItem in sorted(dups):
                if dupItem != orig:
                    if dupItem in forceKeep:
                        stream.write(f' == {dupItem}\n')
                    else:
                        stream.write(f'    {dupItem}\n')
                else:
                    stream.write(f' -> {dupItem} (choosen by "{srName}")\n')
        if not duplicates[1]:
            stream.write('# no duplicating directories\n')
    else:
        stream.write('# no duplicates found')


def write_duplicates_report_json(stream, duplicates):
    pass

def fs_tree(basePath, iterable):
    """
    Builds dictionary from FS subtree. Arguments are the same as
    for ``dfs_fs_items()``. Returned dict will reflect subtree with keys
    matching file names and a special property ``!ownProps`` containing
    size, md5, etc.
    """
    r = {}
    for fsType, relPath, md5, size, linkTarget in iterable:
        relPath = os.path.normpath(relPath)
        pathTokens = tuple(pathlib.PurePosixPath(relPath).parts)
        obj = {
                'path': relPath,
                'origPath': os.path.join(basePath, relPath),
                'size': size,
                'md5sum': md5,  #hashlib.md5(md5).hexdigest(),
                'nUses': 0,
                'meta': None,  # TODO
                'fsType': fsType,
                'linkTarget': linkTarget
            }
        c = r
        for k in pathTokens:
            c_ = c.get(k, None)
            if c_ is None:
                c[k] = {}
            c = c[k]
        c['!ownProps'] = obj
    return r

class DirDiff(object):
    """
    Represents recursive differences between two directories.

    Inspired by ``filecmp.dircmp()`` and some other solutions, this class
    exploits MD5-based caching to recursively compare two directories with
    sub-structure, figuring out identical branches.

    The primary usage scenario is to maintain directories with large amount
    of duplicating data with nearly-identical structure. Having to directories,
    say, A and B one would like to re-use data from A in B by creating symlinks
    in the B pointing to same entities in A. Within such scenario, this class
    represents relative differences between A and B, which can be used then
    to create links (symbolic or hard).
    """

    reportColors = {
            'no': '\033[2m',
            'lb': '\033[1m',
            'cl': '\033[0m',

            '+f': '[+] \033[32m',
            '~f': '[~] \033[33m',
            '=f': '[=] \033[34m',
            '-f': '[-] \033[31m',

            '+d': '[+] \033[1;32m',
            '~d': '[~] \033[1;33m',
            '=d': '[=] \033[1;34m',
            '-d': '[-] \033[1;31m',

            '+l': '[+] \033[1;36m',
            '~l': '[~] \033[36m',
            '=l': '[=] \033[36m',
            '-l': '[-] \033[2;36m',
        }

    reportNoColors = {
                'no': '', 'lb': '', 'cl': '',
                '+f': '', '~f': '', '=f': '', '-f': '',
                '+d': '', '~d': '', '=d': '', '-d': '',
                '+l': '', '~l': '', '=l': '', '-l': ''
            }

    def __init__(self, pathA, pathB, recursive=True, a=None, b=None
            , _savedObj=None, **kwargs):
        L = logging.getLogger(__name__)
        self._pathA = pathA
        self._pathB = pathB
        if os.path.realpath(pathA) == os.path.realpath(pathB):
            raise RuntimeError(f'Can not compare same directory: both "{pathA}"'
                    + f' and "{pathB}" resolved to "{os.path.realpath(pathA)}".')
        # scan dirs if result not given
        if a is None: a = fs_tree(pathA, dfs_fs_items(pathA, **kwargs))
        self._a = a
        if b is None: b = fs_tree(pathB, dfs_fs_items(pathB, **kwargs))
        self._b = b
        # find identic directories
        itemsA, itemsB = [], []
        for k in self._a.keys():
            if k.startswith('!'): continue
            itemsA.append((k, self._a[k]['!ownProps']['fsType']))
        for k in self._b.keys():
            if k.startswith('!'): continue
            itemsB.append((k, self._b[k]['!ownProps']['fsType']))
        itemsA, itemsB = set(itemsA), set(itemsB)
        self._onlyInA = itemsA - itemsB
        self._onlyInB = itemsB - itemsA
        self._common  = itemsA & itemsB  # only common names
        # among common entries, compare sizes and hashsums
        mayBeIdentic = []
        for k, fsType in self._common:
            if fsType == 'l':
                # symlinks are considered identic when they do refer to the
                # same target
                assert k in self._a.keys()
                assert k in self._b.keys()
                if self._a[k]['!ownProps']['linkTarget'] != self._b[k]['!ownProps']['linkTarget']:
                    L.debug(f'Links "{k}" refer to different targets:'
                            + f' \"{self._a[k]["!ownProps"]["linkTarget"]}\" from {os.path.join(self._pathA, k)} and'
                            + f' \"{self._b[k]["!ownProps"]["linkTarget"]}\" from {os.path.join(self._pathB, k)}')
                    continue
            if self._a[k]['!ownProps']['size']    != self._b[k]['!ownProps']['size']:
                L.debug(f'FS items differ in size: {k}')
                continue
            if self._a[k]['!ownProps']['md5sum']  != self._b[k]['!ownProps']['md5sum']:
                L.debug(f'FS items differ in md5: {k}')
                continue
            L.debug(f'FS items may be identical (size and md5 match or link target match): {k}')
            mayBeIdentic.append((k, fsType))
            # NOTE: obtain different eponymous as (self._common - mayBeIdentic)
        self._recursive = recursive
        if not recursive:
            self._mayBeIdentic = set(mayBeIdentic)
        else:
            # Otherwise, perform recursive traversal
            # 1. compare files in this dir
            self._identicFiles = set()
            # identicFilesCache can be provided externally to avoid actual
            # disk IO (for instance, while loading from saved file for
            # directories that already gone).
            if _savedObj is None:
                for maybeIdenticFile, fsType in mayBeIdentic:
                    if fsType == 'd': continue  # omit dirs
                    # compare two files (or links)
                    fullPathInA = os.path.join(pathA, maybeIdenticFile)
                    fullPathInB = os.path.join(pathB, maybeIdenticFile)
                    if fsType == 'l':
                        # symlinks were compared previously and if link in this
                        # set, it is identic in fact
                        self._identicFiles.add((maybeIdenticFile, 'l'))
                        L.debug(f'Links are identical: {fullPathInA}, {fullPathInB}')
                        continue
                    if are_hardlinked(fullPathInA, fullPathInB) \
                    or filecmp.cmp(fullPathInA, fullPathInB, shallow=False):
                        # files match
                        self._identicFiles.add((maybeIdenticFile, 'f'))
                        L.debug(f'Files are truly identical: {fullPathInA} {fullPathInB}')
                    else:
                        L.debug(f'Files differ: {fullPathInA} {fullPathInB}')
            else:
                self._identicFiles = set(_savedObj['identicFiles'])
            # 2. compare directories using this class
            subDirs = set(nm for nm, fsType in (itemsA & itemsB) if 'd' == fsType)
            self._subDiff = {}
            for maybeIdenticDir in subDirs:
                # compare two files
                fullPathInA = os.path.join(pathA, maybeIdenticDir)
                fullPathInB = os.path.join(pathB, maybeIdenticDir)
                if not _savedObj:
                    self._subDiff[maybeIdenticDir] = DirDiff(fullPathInA, fullPathInB
                        , recursive=self._recursive
                        , **kwargs)
                else:
                    self._subDiff[maybeIdenticDir] = DirDiff(fullPathInA, fullPathInB
                        , a=a[maybeIdenticDir], b=b[maybeIdenticDir]
                        , recursive=self._recursive
                        , _savedObj=_savedObj['sub'][maybeIdenticDir]
                        , **kwargs)

    @functools.cached_property
    def isIdentical(self):
        if not self._recursive:
            raise RuntimeError('Can not determine if dirs are identic as object'
                    ' is not recusrsive')
        # if we have entries present only in one of the dirs, current directory
        # is not identic for sure
        if self._onlyInA: return False
        if self._onlyInB: return False
        # if not all the files and/or symlinks are identical, result in
        # dirs not being identical
        if self._identicFiles != set(c for c in self._common if c[1] in 'lf'):
            return False
        # if any of the subdir is not identical, this (parent) is not identical
        for subDiff in self._subDiff.values():
            if not subDiff.isIdentical: return False
        # dirs are identical
        return True

    @property
    def a(self):
        return self._pathA

    @property
    def b(self):
        return self._pathB

    @functools.cached_property
    def identicDirs(self):
        if not self._recursive:
            # todo: well, for flat directories it still may have sense...
            raise RuntimeError('Can not determine if dirs are identic as object'
                    ' is not recusrsive')
        return set(nm for nm, dirItem in self._subDiff.items() if dirItem.isIdentical)

    @property
    def identicLinks(self):
        return set(f for f, t in self._identicFiles if t == 'l')

    @functools.cached_property
    def differentLinks(self):
        return set(nm for nm, t in self._common if 'l' == t) - self.identicLinks

    @functools.cached_property
    def differentDirs(self):
        return set(nm for nm in self._subDiff.keys()) - self.identicDirs

    @functools.cached_property
    def nonTrivialDiffs(self):
        return dict((k, self._subDiff[k]) for k in self.differentDirs)

    @property
    def identicFiles(self):
        return set(f for f, t in self._identicFiles if t == 'f')

    @functools.cached_property
    def differentFiles(self):
        return set(nm for nm, t in self._common if 'f' == t) - self.identicFiles


    @property
    def createdItems(self):
        return self._onlyInB

    @property
    def removedTiems(self):
        return self._onlyInA


    def print_report(self, stream=sys.stdout, nIndent=0, onlyDiff=False
            , colors=None, labels=True):
        """
        Prints human-readable summary of two directories difference.
        """
        if not colors:
            colors = self.__class__.reportNoColors
        elif type(colors) is bool and colors:
            colors = self.__class__.reportColors
        assert type(colors) is dict
        indent = '  '*nIndent
        if (not onlyDiff) or (self._onlyInA or self._onlyInB):
            if (not onlyDiff) or self._onlyInA:
                if labels: stream.write(indent + f'{colors["lb"]}Only in {self._pathA}{colors["cl"]}:\n')
                for nm in sorted(nm for nm, t in self._onlyInA if 'd' == t):
                    stream.write(indent + f'  {colors["-d"]}{nm}/{colors["cl"]}\n')  # dir
                for nm in sorted(nm for nm, t in self._onlyInA if 'l' == t):
                    stream.write(indent + f'  {colors["-l"]}{nm}{colors["cl"]}\n')  # link
                for nm in sorted(nm for nm, t in self._onlyInA if 'f' == t):
                    stream.write(indent + f'  {colors["-f"]}{nm}{colors["cl"]}\n')   # file
                if not self._onlyInA:
                    stream.write(indent + f'  {colors["no"]}(no exclusives for A){colors["cl"]}\n')
            if (not onlyDiff) or self._onlyInB:
                if labels: stream.write(indent + f'{colors["lb"]}Only in {self._pathB}{colors["cl"]}:\n')
                for nm in sorted(nm for nm, t in self._onlyInB if 'd' == t):
                    stream.write(indent + f'  {colors["+d"]}{nm}/{colors["cl"]}\n')
                for nm in sorted(nm for nm, t in self._onlyInB if 'l' == t):
                    stream.write(indent + f'  {colors["+l"]}{nm}{colors["cl"]}\n')
                for nm in sorted(nm for nm, t in self._onlyInB if 'f' == t):
                    stream.write(indent + f'  {colors["+f"]}{nm}{colors["cl"]}\n')
                if not self._onlyInB:
                    stream.write(indent + f'  {colors["no"]}(no exclusives for B){colors["cl"]}\n')

        if not self._recursive:
            # For non-recursive diff, print "for sure different" and
            # "may be identical" items
            differ = self._common - self._mayBeIdentic
            if (not onlyDiff) or differ:
                if labels:
                    stream.write(indent + f'{colors["lb"]}Eponymous common FS entries{colors["lb"]}:\n')
                    stream.write(indent + '  {colors["lb"]}Different{colors["cl"]}:\n')
                for nm in sorted(nm for nm, t in differ if 'd' == t):
                    stream.write(f'    {colors["~d"]}{nm}/{colors["cl"]}\n')
                for nm in sorted(nm for nm, t in differ if 'l' == t):
                    stream.write(f'    {colors["~l"]}{nm}{colors["cl"]}\n')
                for nm in sorted(nm for nm, t in differ if 'f' == t):
                    stream.write(f'    {colors["~f"]}{nm}{colors["cl"]}\n')
                if not differ:
                    stream.write(indent + '    {colors["no"]}(no obvious diffs){colors["cl"]}\n')
            if (not onlyDiff) or self._mayBeIdentic:
                if labels: stream.write(indent + '  {colors["lb"]}May be identical{colors["cl"]}:\n')
                for nm in sorted(nm for nm, t in self._mayBeIdentic if 'd' == t):
                    stream.write(indent + f'    {colors["=d"]}{nm}/{colors["cl"]}\n')
                for nm in sorted(nm for nm, t in self._mayBeIdentic if 'l' == t):
                    stream.write(indent + f'    {colors["=l"]}{nm}{colors["cl"]}\n')
                for nm in sorted(nm for nm, t in self._mayBeIdentic if 'f' == t):
                    stream.write(indent + f'    {colors["=f"]}{nm}{colors["cl"]}\n')
                if not (self._mayBeIdentic):
                    stream.write(indent + '    {colors["no"]}(no may-be-identical){colors["cl"]}\n')
        else:
            identicalDirs  = self.identicDirs
            differentDirs  = self.differentDirs
            differentFiles = self.differentFiles  #set(nm for nm, t in self._common if 'f' == t) - self._identicFiles

            if (not onlyDiff) or differentDirs or differentFiles:
                if labels: stream.write(indent + f'{colors["lb"]}Eponymous common FS entries:{colors["cl"]}\n')

            if not onlyDiff:
                if labels: stream.write(indent + f'  {colors["lb"]}Identical:{colors["cl"]}\n')
                # Identical dirs:
                for nm in sorted(identicalDirs):
                    stream.write(indent + f'    {colors["=d"]}{nm}/{colors["cl"]}\n')
                # Identical links:
                for nm in sorted(self.identicLinks):
                    stream.write(indent + f'    {colors["=l"]}{nm}{colors["cl"]}\n')
                # Identical files
                for identicalFile in sorted(self.identicFiles):
                    stream.write(indent + f'    {colors["=f"]}{identicalFile}{colors["cl"]}\n')
                # fallback msg
                if (not identicalDirs) and (not self.identicFiles) and (not self.identicLinks):
                    stream.write(indent + f'    {colors["no"]}(no identical items){colors["cl"]}\n')

            if (not onlyDiff) or (differentDirs or differentFiles):
                if labels: stream.write(indent + f'  {colors["lb"]}Different:{colors["cl"]}\n')
                for nm in sorted(differentDirs):
                    stream.write(indent + f'    {colors["~d"]}{nm}/{colors["cl"]}\n')
                    self._subDiff[nm].print_report(stream=stream, nIndent=nIndent+3, colors=colors
                            , onlyDiff=onlyDiff, labels=labels)
                for nm in sorted(self.differentLinks):
                    stream.write(indent + f'    {colors["~l"]}{nm}{colors["cl"]}\n')
                for nm in sorted(differentFiles):
                    stream.write(indent + f'    {colors["~f"]}{nm}{colors["cl"]}\n')
                if not (differentDirs or differentFiles):
                    stream.write(indent + f'    {colors["no"]}(no different items){colors["cl"]}\n')

    def _cache_to_save(self):
        """
        Aux routine returning recursive dict containing cache of identical
        files. Used in (de)serialization routines.
        """
        r = {'identicFiles': list(self._identicFiles), 'sub': {}}
        for subDir, subDiff in self._subDiff.items():
            r['sub'][subDir] = subDiff._cache_to_save()
        return r

    def serializable_dict(self):
        """
        Produces minified set of data, suitable for saving. Returned dictionary
        can be written as JSON or it can be pickle for further restore.
        """
        # make deepcopy of dir structures, as we going to turn bytes into
        # encoded strings; save original paths
        savedObj = { 'a': copy.deepcopy(self._a), 'pathA': self._pathA
                   , 'b': copy.deepcopy(self._b), 'pathB': self._pathB
                   }
        # aux function to encode bytes as strings
        def _bytes_to_hex(obj):
            if '!ownProps' in obj.keys():
                if 'md5sum' in obj['!ownProps'].keys() and obj['!ownProps']['md5sum']:
                    obj['!ownProps']['md5sum'] = hashlib.md5(obj['!ownProps']['md5sum']).hexdigest()
                if 'meta' in obj['!ownProps'].keys() and obj['!ownProps']['meta']:
                    obj['!ownProps']['meta'] = base64.b64encode(obj['!ownProps']['meta'])
            for k in obj.keys():
                if k.startswith('!'): continue
                obj[k] = _bytes_to_hex(obj[k])
            return obj
        # convert bytes to strings
        savedObj['a'] = _bytes_to_hex(savedObj['a'])
        savedObj['b'] = _bytes_to_hex(savedObj['b'])
        # if recursive, save file comparison results to avoid FS queries on
        # restoration
        if self._recursive:
            savedObj.update(self._cache_to_save())
        return savedObj

    @classmethod
    def from_dict(cls, obj):
        """
        Uses dictionary created with ``serializable_dict()`` to restore
        ``DirDiff`` object.
        """
        # converts encoded bytes to Python bytes
        def _hex_to_bytes(obj):
            if '!ownProps' in obj.keys():
                if 'md5sum' in obj['!ownProps'].keys() and obj['!ownProps']['md5sum']:
                    obj['!ownProps']['md5sum'] = bytes.fromhex(obj['!ownProps']['md5sum'])
                if 'meta' in obj['!ownProps'].keys() and obj['!ownProps']['meta']:
                    obj['!ownProps']['meta'] = base64.b64decode(obj['!ownProps']['meta'])
            for k in obj.keys():
                if k.startswith('!'): continue
                obj[k] = _hex_to_bytes(obj[k])
            return obj
        # get 
        a = _hex_to_bytes(obj['a'])
        obj.pop('a')
        pathA = obj['pathA']
        obj.pop('pathA')

        b = _hex_to_bytes(obj['b'])
        obj.pop('b')
        pathB = obj['pathB']
        obj.pop('pathB')

        if 'identicFiles' in obj.keys():
            return cls(pathA, pathB, a=a, b=b, recursive=True, _savedObj=obj)
        return cls(pathA, pathB, a=a, b=b, recursive=False, _savedObj=obj)


def create_incremental_copy( dirDiff #baseDir, subjDir
        , outDir=None, filesFilter=None
        , dirsFilter=None, link=os.symlink, dryRun=False):
    """
    Creates an "incremental snapshot" directory at ``outDir`` that will contain
    all the files and/or directories from ``subjDir`` which are identical to
    ones from ``baseDir`` substituted by soft/hard links referring to ones from
    ``baseDir``. I.e. ``outDir`` content will repeat ``subjDir``, but with
    links to ``baseDir`` where it is possible.

    Normally, symbolic links will be created, unless ``hardLinks`` is set.

    Use ``filesFilter`` and ``dirsFilter`` (will be called for both dirs).
    Arguments have same meaning as eponymous at `dfs_fs_items()`.

    Note: if ``outDir`` is ``None`` or matches ``subjDir`` changes will be done
    in-place.

    Note: ``dryRun=True`` prevents ``link`` from being called at all (so if
    ``link()`` is also behaving dry, you won't see any messages anyway).
    """
    L = logging.getLogger(__name__)
    baseDir, subjDir = dirDiff.a, dirDiff.b
    if outDir is None: outDir = subjDir
    # destructive mode means that we modify subject dir
    destructive = os.path.realpath(outDir) == os.path.realpath(subjDir)
    if dirDiff.isIdentical:
        L.info(f'Linking "{baseDir}" -> "{outDir}" as subject matches base.')
        # both directories are identical -- just create a link and that's it
        if not dryRun: link(baseDir, outDir)
        return True
    if not os.path.isdir(outDir):
        os.makedirs(outDir, exist_ok=True)
    # - identic items
    #       in destructive mode we remove existing item and create links
    #       instead, while for non-destructive mode we only create links
    if destructive:
        for identicDir in dirDiff.identicDirs:
            dir2rm = os.path.join(outDir, identicDir)
            L.info(f'Removing dir "{dir2rm}"')
            if not dryRun: shutil.rmtree(dir2rm)
        for identicFile in dirDiff.identicFiles:
            file2rm = os.path.join(outDir, identicFile)
            L.info(f'Removing file "{file2rm}"')
            if not dryRun: os.remove(file2rm)
    for identicDir in dirDiff.identicDirs:
        srcDir = os.path.join(baseDir, identicDir)
        dstDir = os.path.join(outDir,  identicDir)
        if not dryRun: link(srcDir, dstDir)
    for identicFile in dirDiff.identicFiles:
        srcFile = os.path.join(baseDir, identicFile)
        dstFile = os.path.join(outDir,  identicFile)
        L.info(f'Linking file "{srcFile}" -> "{dstFile}"')
        if not dryRun: link(srcFile, dstFile)
    # - new items (exist only in subject dir)
    #       for destructive mode we simply do not touch items that exist only
    #       in the subject dir, while for non-destructive we copy them
    if not destructive:
        for newItem, t in dirDiff.createdItems:
            if 'd' == t:
                srcDir = os.path.join(subjDir, newItem)
                dstDir = os.path.join(outDir,  newItem)
                L.info(f'Copying dir "{srcDir}" -> "{dstDir}"')
                if not dryRun: shutil.copytree( srcDir, dstDir )
            elif 'f' == t:
                srcFile = os.path.join(subjDir, newItem)
                dstFile = os.path.join(outDir,  newItem)
                L.info(f'Copying file "{srcFile}" -> "{dstFile}"')
                if not dryRun: shutil.copy( srcFile, dstFile )
            else:
                raise RuntimeError(f"Unsupported FS entry type: {t}")
    # - files changed in the new dir
    #       for destructive mode we just keep it, for non-destructive we must
    #       copy
    if not destructive:
        for changedFile in dirDiff.differentFiles:
            srcFile = os.path.join(subjDir, changedFile)
            dstFile = os.path.join(outDir,  changedFile)
            L.info(f'Copying "{srcFile}" -> "{dstFile}"')
            if not dryRun: shutil.copy(srcFile, dstFile)
    # - changed directories
    for subDir, subDirDiff in dirDiff.nonTrivialDiffs.items():
        subOutDir = None
        if not destructive:
            subOutDir = os.path.join(outDir, subDir)
        create_incremental_copy( subDirDiff
                , outDir=subOutDir
                , filesFilter=filesFilter, dirsFilter=dirsFilter
                , link=link, dryRun=dryRun
                )

#
# Runtime utilities

def mk_soft_link(src, dest, relative=True, dryRun=False):
    L = logging.getLogger(__name__)
    src_ = src
    if relative:
        src_ = os.path.relpath(src, os.path.dirname(dest))
    else:
        src_ = os.path.abspath(src)
        src = src_
    L.debug(f'Creating symbolic link "{src}" -> "{dest}"'
            + (f', relative is "{src_}"' if relative else '')
            + (' (dry run)' if dryRun else ''))
    if not os.path.exists(src):
        raise RuntimeError(f'Soft link source path "{src}" does not exist')
    if os.path.exists(dest):
        raise RuntimeError(f'Soft link destination path "{dest}" exists')
    if not dryRun:
        os.symlink(src_, dest)

def mk_soft_link__rel(src, dest):
    return mk_soft_link(src, dest, relative=True, dryRun=False)

def mk_soft_link__rel_dry(src, dest):
    return mk_soft_link(src, dest, relative=True, dryRun=True)

def mk_soft_link__abs(src, dest):
    return mk_soft_link(src, dest, relative=False, dryRun=False)

def mk_soft_link__abs_dry(src, dest):
    return mk_soft_link(src, dest, relative=False, dryRun=False)


def mk_hard_link(src, dest, exist_ok=True, dryRun=False):
    L = logging.getLogger(__name__)
    L.debug(f'Creating hard link "{src}" <-> "{dest}"' + (' (dry run)' if dryRun else ''))
    if not os.path.exists(src):
        raise RuntimeError(f'Hard link source path "{src}" does not exist')
    if os.path.exists(dest):
        if exist_ok:
            if os.path.isdir(dest):
                L.debug(f'Removing existing dir \"{dest}\" to be substituted by hard link')
                if not dryRun: shutil.rmtree(dest)
            else:
                L.debug(f'Removing existing file \"{dest}\" to be substituted by hard link')
                if not dryRun: os.remove(dest)
        else:
            raise RuntimeError(f'Hard link destination path "{dest}" exists')
    if not dryRun:
        os.link(src, dest)

def mk_hard_link__dry(src, dest):
    return mk_hard_link(src, dest, exist_ok=True, dryRun=True)

#def mk_hard_link__
# ...


class BasePathWildcard(object):
    def __init__(self, pattern):
        self._pat = pattern

    def __call__(self, paths):
        return list(p for p in paths if fnmatch.fnmatch(p, self._pat))

# Example of possible conflict:
#   - a/ and b/ are duplicating
#   - both containse foo/ (which naturally duplicates)
#   - a/ defined by resolver as original b/w (a, b) and b/foo defined as original
#     for (a/foo, b/foo)
# If (a/foo, b/foo) gets processed first, then:
#   - a/foo becomes symlink to b/foo (a/foo gets deleted)
#   - b/ becomes symlink to a/ (while b/ gets deleted)
#   => a/foo becomes dangling symlink and the data is lost!
# To avoid this situation, we must process duplicating dir in order that:
#   - first a/ and b/ resolved (b/ is not symlink to a/)
#   - b/foo is removed from (a/foo, b/foo) set, b/foo is no longer a
#     duplicate -- remove or ignore set of single element (yet, there might be
#     still c/foo, that then becomes a link to a/foo if resolver permits...
#     (though, resolver may want to keep b/foo as the original?)
# How to sort it then?
#
#   {dir-a/foo, dir-b/bar, dir-c/dir-d/zum}
#   {dir-a/bar, dir-c/}
#   

def deduplicate(root, dupFiles, dupDirs, sourceResolvers=None
        , forceKeep=None
        , dryRun=False
        , link_dir=mk_soft_link__rel
        , link_file=mk_hard_link
        ):
    """
    TODO: destdir
    TODO: switching to DB may severely change this code...
    ...
    """
    L = logging.getLogger(__name__)
    if sourceResolvers is None: sourceResolvers = []
    if forceKeep: forceKeep = []
    linkFileIsSymbolic = link_file in ( mk_soft_link
                    , mk_soft_link__abs
                    , mk_soft_link__abs_dry
                    , mk_soft_link__rel
                    , mk_soft_link__rel_dry)
    # process directories first
    itemsToDelete = {}       # files and directories to be substituted by links (path -> (src, rule name))
    itemsToKeep = {}         # files and directories to become link targets (path -> rule name)
    for dirGroup in dupDirs:
        origDir, resolverName = _resolve_source(dirGroup, sourceResolvers, fsItemsStr='Dirs')
        if origDir is None or type(origDir) is not str:
            raise RuntimeError('Failed to resolve single source for'
                    + ' duplicate directories group: %s'%(
                        ', '.join(sorted(dirGroup))))
        origFullPath = os.path.realpath(os.path.join(root, origDir))
        itemsToKeep[origFullPath] = (resolverName, 'd')
        for d2rm in dirGroup:
            if d2rm == origDir: continue
            dfp = os.path.realpath(os.path.join(root, d2rm))
            if dfp in itemsToDelete.keys():
                if itemsToDelete[dfp][0] != origFullPath:
                    raise RuntimeError(f'Conflicting paths for {dfp}:'
                            + f' {itemsToDelete[dfp][0]} choosen by rule'
                            + f' "{itemsToDelete[dfp][1]}" and'
                            + f' {origFullPath} choosen by "{resolverName}"')
            itemsToDelete[dfp] = (origFullPath, resolverName, 'd')
    if linkFileIsSymbolic:
        # for soft links -- also process file linking
        for fileGroup in dupFiles:
            origFile, resolverName = _resolve_source(fileGroup, sourceResolvers, fsItemsStr='')
            if origFile is None or type(origFile) is not str:
                raise RuntimeError('Failed to resolve single source for'
                        + ' duplicate files group: %s'%(
                            ', '.join(sorted(fileGroup))))
            origFullPath = os.path.realpath(os.path.join(root, origFile))
            itemsToKeep[origFullPath] = (resolverName, 'f')
            for f2rm in fileGroup:
                if f2rm == origFile: continue
                ffp = os.path.realpath(os.path.join(root, f2rm))
                if ffp in itemsToDelete.keys():
                    if itemsToDelete[ffp][0] != origFullPath:
                        raise RuntimeError(f'Conflicting paths for {ffp}:'
                                + f' {itemsToDelete[ffp][0]} choosen by rule'
                                + f' "{itemsToDelete[ffp][1]}" and'
                                + f' {origFullPath} choosen by {resolverName}')
                itemsToDelete[ffp] = (origFullPath, resolverName, 'f')
    # check that none of the "original" (source) items will be deleted
    for pathToKeep, (resolverName, t) in itemsToKeep.items():
        assert pathToKeep not in itemsToDelete.keys()  # should prohibited logically
        # check if path to keep is sub-path of any of the path to delete
        for c in itemsToDelete.keys():
            if not is_subpath_of(pathToKeep, c): continue
            raise RuntimeError(f'Conflict: {"directory" if t == "d" else "file"}'
                    f' "{os.path.relpath(pathToKeep, root)}" must be kept'
                    f' according to the rule "{resolverName}", but'
                    f' rule "{itemsToDelete[c][1]}" prescribes it to be deleted.'
                    )
    # avoid repeatative deletions by removing children
    deleteItems = set(p for p in itemsToDelete.keys())
    hadRemovals = True
    while hadRemovals:
        deletedItems = None
        hadRemovals = False
        for cItem in sorted(deleteItems):
            if cItem not in itemsToDelete.keys(): continue  # already un-queued
            origFullPath, _, fsType = itemsToDelete[cItem]
            if fsType != 'd': continue
            deletedItems = set(p for p in deleteItems if is_subpath_of(p, cItem))
            deletedItems.remove(cItem)
            if not deletedItems: continue
            L.debug( f'Deleting of {os.path.relpath(cItem, root)} will delete'
                   + f' also {", ".join(os.path.relpath(p, root) for p in sorted(deletedItems))}')
            hadRemovals = True
            for deleteItem in deletedItems:
                itemsToDelete.pop(deleteItem)
            deleteItems -= set(deletedItems)
            break
    # delete and link
    for cItem in sorted(deleteItems):
        origFullPath, _, fsType = itemsToDelete[cItem]
        if 'd' == fsType:
            L.info(f'Substituting directory {os.path.relpath(cItem, root)}'
                    + f' with link to {os.path.relpath(origFullPath, root)})')
            if not dryRun:
                shutil.rmtree(cItem)
                link_dir(origFullPath, cItem)
        elif 'f' == fsType:
            assert linkFileIsSymbolic
            # ^^^ TODO: this is permitted case as user still might want to have
            #     selection for hard links. In this case we should remove
            #     processed entries from file duplicates list
            L.info(f'Substituting file {os.path.relpath(cItem, root)}'
                    + f' with link to {os.path.relpath(origFullPath, root)})')
            if not dryRun:
                os.remove(cItem)
                link_file(origFullPath, cItem)
    if not linkFileIsSymbolic:
        # for hard links it does not matter which we took as original
        for fileGroup in dupFiles:
            if len(fileGroup) < 2: continue
            L.debug('Joining files: ' + ', '.join(sorted(fileGroup)))
            filesToLink = list(sorted(fileGroup))
            orig = filesToLink[0]
            filesToLink = filesToLink[1:]
            for linkTgt in filesToLink:
                L.debug(f'Linking "{orig}" <-> "{linkTgt}"')
                if not dryRun:
                    os.remove(linkTgt)
                    link_file(orig, linkTgt)

#
# Aux for command line invocation

def add_argument_parser_options(p):
    p.add_argument('subjDir', help='Subject directory, a "modified version".')
    p.add_argument('--base', help='Base directory used as the "original'
            ' directory".', dest='baseDir')
    p.add_argument('--dest', help='Output directory where resulting snapshot'
            ' of the modified dir will be put.', dest='destDir')
    #p.add_argument('-e', '--exclude-files', help='Exclude files directory'
    #        ' or file.', action='append')
    #p.add_argument('--no-empty-dirs', help='Omit empty directories.'
    #        , action='store_true')
    #p.add_argument('--min-file-size', help='Omit files of size less than given'
    #        ' (in bytes).')
    #p.add_argument('--min-dir-size', help='Omit files of size less than given'
    #        ' (in bytes).')
    #p.add_argument('--', ...)
    p.add_argument('--originals', help='Wildcard for symbolic link sources.'
            , action='append', dest='origRules'
            )
    p.add_argument('--handle-symlinks', help='Way to handle symlinks in subject'
            ' and/or base directory. Has no effect when'
            ' --use-diff is specified.'
            , choices=['consider', 'dereference', 'ignore']
            , default='consider'
            , dest='handleSymlinks'
            )
    p.add_argument('--links-type', help='Type of the links to create.'
            ' If "hard" is specified, symbolic relative links will be used'
            ' for directories.'
            , choices=['symbolic-relative', 'symbolic-absolute', 'hard']
            , default='symbolic-relative'
            , dest='links'
            )
    p.add_argument('-f', '--apply', help='Apply the anticipated changes and'
            ' modify FS trees. If -q/--quiet is not given, only intentions will'
            ' be printed.'
            , dest='dryRun', action='store_false')
    p.add_argument('-i', '--use-diff', help='Input directories diff object to use'
            ' (previously saved with -o/--write-diff).'
            , dest='useDiff')
    p.add_argument('-o', '--write-diff', help='Output file to write found'
            ' directories diff object. Can be used further with -i/--use-diff'
            ' option.', dest='outDiff')

    # Report printing and formatting options
    p.add_argument('-p', '--print-report', help='Prints human-readable report.'
            ' If argument is given, it will be interpreted as a file,'
            ' otherwise prints to stdout.', dest='printReport', nargs='?'
            , const=True, default=None)
    p.add_argument('--report-print-only-diffs', help='Report will not include'
            ' identical items.', action='store_true', dest='reportOnlyDiff')
    p.add_argument('--report-no-labels', help='Disables labels in the report'
            ' output', dest='reportLabels', action='store_false')
    reportColorsGroup = p.add_mutually_exclusive_group()
    reportColorsGroup.add_argument('--report-colors', help='Forces coloring in'
            ' report printing.'
            , action='store_true', dest='reportColors', default=None)
    reportColorsGroup.add_argument('--report-no-colors', help='Forcefully'
            ' disables colors in report printing.'
            , action='store_true', dest='reportNoColors', default=None)


def run( subjDir, baseDir=None, destDir=None, dryRun=False, useDiff=None
        , outDiff=None
        , handleSymlinks='consider'
        , origRules=None
        , printReport=False, reportOnlyDiff=True
            , reportColors=None, reportNoColors=None, reportLabels=True
        , links='symbolic-relative'
        ):
    """
    Generalized entry point procedure.
    """
    filesFilter = None  # TODO
    dirsFilter = None  # TODO
    sourceResolvers = None  # TODO
    if origRules:
        sourceResolvers = []
        for pat in origRules:
            assert pat
            sourceResolvers.append((pat, BasePathWildcard(pat)))

    if type(links) is str:
        if 'symbolic-relative' == links:
            links = mk_soft_link__rel_dry if dryRun else mk_soft_link__rel
        elif 'symbolic-absolute' == links:
            links = mk_soft_link__abs_dry if dryRun else mk_soft_link__abs
        elif 'hard' == links:
            links = mk_hard_link__dry if dryRun else mk_hard_link

    L = logging.getLogger(__name__)
    # at the end of subsequent if-clauses exactly one of these two must be set
    dirDiff, duplicates = None, None
    # load dir-diff if need
    if useDiff:
        assert type(useDiff) is str
        diffObj = None
        if useDiff.lower().endswith('.json.gz'):
            with gzip.open(useDiff, 'r') as fJsGz:
                bDiffStr = fJsGz.read()
            diffObj = json.loads(bDiffStr.decode())
        elif useDiff.lower().endswith('.pickle'):
            with open(useDiff, 'rb') as f:
                diffObj = pickle.load(f)
        else:
            with open(useDiff, 'r') as f:
                diffObj = json.load(f)
        assert diffObj
        dirDiff = DirDiff.from_dict(diffObj)
    if baseDir:
        # at least subj and base are given -- compute diff
        if dirDiff is not None:
            raise RuntimeError('Base and subject directories are given together'
                    ' with loaded dir-diff object. Use either dirs or dir-diff.')
        dirDiff = DirDiff(baseDir, subjDir, recursive=True, yieldFiles=True
                , yieldDirs=True, filesFilter=filesFilter, dirsFilter=dirsFilter
                , symlinks=handleSymlinks)
    else:
        duplicates = find_duplicates_in(subjDir)

    # check result of above if-clause that must result in exactly one of the
    # two to be set
    if not (dirDiff or duplicates):
        raise RuntimeError('No dir-diff, no subject dir for duplicates lookup'
                ' -- nothing to do')
    if dirDiff and duplicates:
        raise RuntimeError('Dir-diff object is not used as duplicates lookup'
                ' implied.')

    if dirDiff:
        # save dir-diff if need
        if outDiff:
            diffObj = dirDiff.serializable_dict()
            if outDiff.lower().endswith('.json.gz'):
                with gzip.open(outDiff, 'w') as fJsGz:
                    fJsGz.write(json.dumps(diffObj).encode())
            elif outDiff.lower().endswith('.pickle'):
                with open(outDiff, 'wb') as f:
                    pickle.dump(diffObj, f)
            else:
                with open(outDiff, 'w') as fJs:
                    json.dump(diffObj, fJs, sort_keys=True, indent=2)
        # print report if need
        if printReport:
            assert not (reportColors and reportNoColors)
            reportStream = None
            enableColors = None
            if type(printReport) is str and printReport != '-':
                reportStream = open(printReport, 'w')
                # default behaviour for to-file report if colors are
                # not forced -- turn colors off
                if reportColors is None and reportNoColors is None: enableColors=False
            else:
                reportStream = sys.stdout
                # default behaviour for to stdout report if colors are
                # not forced -- turn colors on
                if reportColors is None and reportNoColors is None: enableColors=True
            try:
                dirDiff.print_report(stream=reportStream
                        , onlyDiff=reportOnlyDiff
                        , colors=enableColors
                        , labels=reportLabels
                        )
            except Exception as e:
                L.error('Error during printing report.')
                L.exception(e)
                return False
            finally:
                if type(printReport) is str and printReport != '-':
                    reportStream.close()
        # apply diff if need
        create_incremental_copy(dirDiff, outDir=destDir
            , filesFilter=filesFilter, dirsFilter=dirsFilter
            , dryRun=dryRun, link=links
            )
    else:
        # duplicates lookup and/or de-duplicating procedure
        if printReport:
            if type(printReport) is str:
                if printReport.lower().endswith('.json.gz'):
                    with gzip.open(printReport, 'w') as fJsGz:
                        fJsGz.write(json.dumps(duplicates).encode())
                elif printReport.lower().endswith('.json'):
                    with open(printReport, 'w') as fJs:
                        json.dump(duplicates, fJs, sort_keys=True, indent=2)
                elif printReport.lower().endswith('.pickle'):
                    with open(printReport, 'wb') as f:
                        pickle.dump(duplicates, f)
                else:
                    with open(printReport, 'w') as f:
                        write_duplicates_report_ascii(f, duplicates)
            else:
                write_duplicates_report_ascii(sys.stdout, duplicates
                        , sourceResolvers=sourceResolvers)
        deduplicate(subjDir, *duplicates, sourceResolvers=sourceResolvers, dryRun=dryRun)
        #if links in ( mk_soft_link
        #            , mk_soft_link__abs
        #            , mk_soft_link__abs_dry
        #            , mk_soft_link__rel
        #            , mk_soft_link__rel_dry
        #            ):
        #    # todo: anticipate some rule to choose among candidates for target
        #    # of symbolic links?
        #    raise RuntimeError("De-duplication procedure"
        #            " can not use symbolic links.")
        #raise NotImplementedError('TODO: duplicates')


gColoredPrfxs = {
        logging.CRITICAL : "\033[1;41;33m\u2592E\033[0m",
        logging.ERROR    : "\033[2;41;32m\u2591e\033[0m",
        logging.WARNING  : "\033[1;43;31m\u2591w\033[0m",
        logging.INFO     : "\033[1;44;37m\u2591i\033[0m",
        logging.DEBUG    : "\033[2;40;36m\u2591D\033[0m",
        logging.NOTSET   : "\033[31;2;11m\u2591?\033[0m"
    }

class ConsoleColoredFormatter(logging.Formatter):
    def format( self, record ):
        m = super(ConsoleColoredFormatter, self).format(record)
        m = gColoredPrfxs[record.levelno] + ' ' + m
        return m

gLoggingConfig = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'standard': {
            '()': ConsoleColoredFormatter,
            'format': "\033[3m%(asctime)s\033[0m %(message)s",
            'datefmt': "%H:%M:%S"
        }
    },
    'handlers': { 
        'default': { 
            'level': 'NOTSET',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
    },
    'loggers': { 
        '': {  # root logger
            'handlers': ['default'],
            'level': 'INFO',
            'propagate': False
        },
    }
}

def main():
    import argparse
    import logging.config
    p = argparse.ArgumentParser(prog=sys.argv[0]
            , description='Creates incremental directory snapshot or'
                ' substitutes duplicating files and dirs with links within'
                ' a directory.'
            , epilog=__doc__
            )
    verbGroup = p.add_mutually_exclusive_group()
    verbGroup.add_argument('-v', '--verbose', help='Verbose output.'
            , action='store_true')
    verbGroup.add_argument('-q', '--quiet', help='Silent output -- only warning and'
            ' errors are printed (except for information requested with'
            ' --report)'
             , action='store_true')
    add_argument_parser_options(p)
    args = p.parse_args(sys.argv[1:])
    argsDict = vars(args)

    # setup logging
    thisLoggingConfig = copy.deepcopy(gLoggingConfig)
    if argsDict.get('quiet', False):
        thisLoggingConfig['loggers']['']['level'] = 'WARNING'
    elif argsDict.get('verbose', False):
        thisLoggingConfig['loggers']['']['level'] = 'NOTSET'
    argsDict.pop('quiet')
    argsDict.pop('verbose')
    logging.config.dictConfig(thisLoggingConfig)

    subjDir = argsDict.get('subjDir', None)
    argsDict.pop('subjDir')
    sys.exit(main(subjDir, **argsDict))

if '__main__' == __name__:
    main()
