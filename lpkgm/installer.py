import copy
from collections import defaultdict
import logging, shutil, tempfile, pathlib, glob
import gitlab
from fnmatch import fnmatch
from datetime import datetime

class Installer(object):
    """
    Gets created in order to install particular package, represents
    installation pipeline (a singular purpose of this class).

    Gets constructed based on package manifest and evolve dynamically-composed
    installation pipeline. The pcakage manifest should provide a sequence of
    calls of methods listed below in section "methods".
    """
    def __init__(self, items, modulescript=None):
        self._items = copy.copy(items)
        self._onExit = []
        self._packageFiles = {}
        self._installedFSEntries = []
        self._dependencies = []
        self._modulescript=modulescript

    def __call__(self, *args, **kwargs):
        L = logging.getLogger(__name__)
        hadError = False
        for item in self._items:
            kwargs_ = copy.copy(item)
            kwargs_.pop('type')
            kwargs_.update(dict(kwargs))
            try:
                getattr(self, item['type'].replace('-', '_'))(*args, **kwargs_)
            except Exception as e:
                L.error(f'Error occured during evaluation of procedure {item["type"]}:')
                L.exception(e)
                #traceback.print_exc()
                hadError = True
                break
        if hadError:
            L.error('Exit due to an error.')
            return False
        return True

    @property
    def installedFiles(self):
        return self._installedFSEntries

    @property
    def dependenciesList(self):
        return list((dep['package'], dep['version']['fullVersion']) for dep in self._dependencies)

    @property
    def stats(self):
        L = logging.getLogger(__name__)
        r = {'size': 0, 'nFiles': 0, 'nDirs': 0, 'nLinks': 0}
        for fse in self._installedFSEntries:
            if os.path.isfile(fse):
                r['size'] += os.path.getsize(fse)
                r['nFiles'] += 1
                continue
            if os.path.isdir(fse):
                r['nDirs'] += 1
                continue
            if os.path.islink(fse):
                r['nLinks'] += 1
                continue
            L.warning(f'Unknown/non-existing fs-entry: "{fse}"')
        return r

    def on_exit(self, emergency=True):
        L = logging.getLogger(__name__)
        L.info('Performing on-exit cleanup procedures (%s):'%('emergency' if emergency else 'normal'))
        if not self._onExit:
            L.info('    (no on-exit handlers)')
        for exitHandler in reversed(self._onExit):
            try:
                exitHandler(emergency)
            except Exception as e:
                L.error('Error occured during evaluation of'
                        ' exit handler:')
                #traceback.print_exc()
                L.exception(e)

    def depends(self, pkgName, pkgVer):
        """
        Appends dependency if need.
        """
        L = logging.getLogger(__name__)
        try:
            for depItem in self._dependencies:
                if pkgName != depItem['package']: continue
                # name match, check version
                if pkgVer == depItem['version']['fullVersion']:
                    return depItem
                #if type(depItem[1]) is dict:
                #    assert 'fullVersion' in depItem[1].keys()
                #    if pkgVer == depItem[1]['fullVersion']: return depItem[1]
                #else:  # str version
                #    if pkgVer == depItem[1]: return depItem[1]
            # otherwise, no match found in already added dependencies -- append
            return self.resolve_dependency(pkgName, pkgVer)
        except Exception as e:
            L.error(f'Failed to resolve {pkgName}/{pkgVer}')
            L.exception(e)
            return None

    def resolve_dependency(self, pkgName, pkgVer):
        assert type(pkgName) is str
        assert type(pkgVer) in (str, dict)
        pkgData = get_package_manifests(pkgName, pkgVer)
        if not pkgData:
            raise RuntimeError(f'Package is not installed: {pkgName} of'
                + f' version {pkgVerStr} (no install manifest file exists)')
        if 1 != len(pkgData):
            raise RuntimeError(f'Multiple packages match {pkgName}/{pkgVerStr}')
        #self._dependencies.append(pkgData[0])  # xxx?
        #pkgVerStr = pkgVer if type(pkgVer) is str else pkgVer['version']['fullVersion']
        #print('xxx', (pkgName, pkgVer['version']) )
        self._dependencies.append(pkgData[0])
        return pkgData[0]

    #                                                                 _______
    # ______________________________________________________________/ Methods
    # this method get called dynamically, in order given in "install"
    # argument of the package description object
    def fetch_package_files_gitlab(self, pkgName, pkgVer
            , server=None
            , projectID=None
            , files=None
            , pkgType='generic'  # optional, query parameter
            , quietOnNoFiles=False
            , publishedAtTimeInterval=None
            , keepFiles=False
            , sourceCodeVersion=None
            ):
        """
        Fetches package of certain version from Project's gitlab package registry
        and returns dictionary with file details definitions.
        """
        L = logging.getLogger(__name__)
        fmtDct = copy.copy(pkgVer)
        fmtDct.update(gSettings['definitions'])
        if publishedAtTimeInterval is None:
            publishedAtTimeInterval = [None, None]
        if publishedAtTimeInterval[0] and type(publishedAtTimeInterval[0]) is str:
            publishedAtTimeInterval[0] = datetime.fromisoformat(publishedAtTimeInterval[0])
        if publishedAtTimeInterval[1] and type(publishedAtTimeInterval[1]) is str:
            publishedAtTimeInterval[1] = datetime.fromisoformat(publishedAtTimeInterval[1])
        # authenticate GitLab API and get files matching patterns to pick up
        assert projectID is not None
        token = get_gitlab_project_token(projectID, server=server)
        assert token is not None
        gl = None
        if 'private-token' == token[0]:
            gl = gitlab.Gitlab(server, private_token=token[1])
            gl.auth()
        elif 'job-token':
            gl = gitlab.Gitlab(server, job_token=token[1])
        assert gl
        project = gl.projects.get(int(projectID))

        assert files
        # make `filePatterns' to contain only tuples (contrary to `files')
        filePatterns = defaultdict(list)
        for fileDefName, fileDefPatterns in files.items():
            if type(fileDefPatterns) is str:
                fileDefPatterns = (fileDefPatterns.format(**fmtDct),)
            for fileDefPattern in fileDefPatterns:
                filePatterns[fileDefName].append(fileDefPattern.format(**fmtDct))

        selectedFiles = defaultdict(list)
        pkgQueryParams = {}
        if pkgVer:
            # NOTE: we make distinction here between "source code version"
            # which does not include build configuration and "package version"
            # which does. This plays a role when different builds are published
            # under the same version, like:
            #   `-1.2.3:  # source code version
            #       |- pgk-1.2.3.opt.cpack.tar.gz  # package version for opt build
            #       `- pkg-1.2.3.dbg.cpack.tar.gz  # package version for dbg build
            # by default we expect the version to match (i.e. source code version
            # is the same as package version), but package settings can provide
            # "sourceCodeVersion" which will be used instead for querying package.
            pkgQueryParams['package_version']=pkgVer['fullVersion']
            if sourceCodeVersion:
                fmtDict = copy.copy(gSettings['definitions'])
                fmtDict.update(pkgVer)
                if type(sourceCodeVersion) is str:
                    sourceCodeVersion = [sourceCodeVersion]
                for scv in sourceCodeVersion:
                    try:
                        pkgQueryParams['package_version']=scv.format(**fmtDict)
                        break
                    except KeyError as e:
                        continue
        if pkgName: pkgQueryParams['package_name']=pkgName
        if pkgType: pkgQueryParams['package_type']=pkgType
        emptyList=True
        for pkg in project.packages.list(**pkgQueryParams):
            # ^^^ query options, examples:
            #   - package_type='generic'
            #   - package_version='0.4.dev'
            #   - package_name='na64sw'
            emptyList=False
            for pf in pkg.package_files.list(get_all=True):
                for fileDefName, fileDefPatterns in filePatterns.items():
                    for pat in fileDefPatterns:
                        if fnmatch(pf.file_name, pat):
                            selectedFiles[fileDefName].append((pf, pkg))
        if not selectedFiles or emptyList:
            if quietOnNoFiles:
                return None  # TODO: empty dict?
            L.error('Error details:\n'
                    + f'- Query parameters: {pkgQueryParams}\n'
                    + f'- Files lookup parameters: {files}\n'
                    + f'- ...expanded to: {filePatterns}'
                    )
            if emptyList:
                L.error('(!) EMPTY LIST was returned for these query parameters!')
            strAux = '- Available packages and files:\n'
            for pkg in project.packages.list():
                strAux += f'    - {pkg.id} {pkg.name} {pkg.version}\n'
                for pf in pkg.package_files.list():
                    strAux += f'      * {pf.file_name} {pf.size}\n'
            L.info(strAux)
            raise RuntimeError('No files found to fetch for query parameters.')

        # strip old files from download if timestamp is not specified
        filesToFetch = {}
        for fileDefName, thisFiles in selectedFiles.items():
            sortedByCreation \
                = sorted(thisFiles, key=lambda f: datetime.fromisoformat(f[0].created_at))
            if publishedAtTimeInterval[0]:
                sortedByCreation = filter(lambda f: f[0].created_at > publishedAtTimeInterval[0], sortedByCreation)
            if publishedAtTimeInterval[1]:
                sortedByCreation = filter(lambda f: f[0].created_at < publishedAtTimeInterval[1], sortedByCreation)
            if not sortedByCreation:
                raise RuntimeError('No files matching required creation time'
                        + f' interval for {fileDefName}')
            filesToFetch[fileDefName] = list(sortedByCreation)[-1]  # most recent
        # Print available package files and their creation dates, mark the files
        # selected for download
        infoStr = ''
        for k, v in selectedFiles.items():
            infoStr += f'{k}:\n'
            for fdef in v:
                ln = f'{fdef[0].created_at} {fdef[0].file_name}'
                if k in filesToFetch and fdef[0].id == filesToFetch[k][0].id:
                    ln = '-> \033[1m' + ln + '\033[0m'
                else:
                    ln = '   ' + ln
                infoStr += '  ' + ln + '\n'
        L.info(infoStr)
        self._pkgDir = tempfile.mkdtemp(prefix=gSettings.get('tmp-dir-prefix', None))
        def _em_rm_pkg_dir(emergency):
            if os.path.isdir(self._pkgDir):
                if not emergency:
                    L.info(f' + deleting {self._pkgDir}')
                    shutil.rmtree(self._pkgDir)
                else:
                    L.warning(f' - {self._pkgDir} is kept for inspection')
        if not keepFiles:
            self._onExit.append(_em_rm_pkg_dir) # install on-exit handler to delete tmp dir
        for fileDefName, (glFile, _) in filesToFetch.items():  # , glPackage
            # download file by ID
            fileURL = f'{server}/{project.path_with_namespace}/-/package_files/{glFile.id}/download'
            outFPath = os.path.join(self._pkgDir, glFile.file_name)
            L.debug(f'Downloading:\n    {fileURL} -> {outFPath}')
            download_file_http(fileURL, outFPath)
            self._packageFiles[fileDefName] = outFPath
            #with open(outFPath, 'wb') as f:
            #    for data in tqdm(response.iter_content()):
            #        f.write(data)
            # #1: works, but has argument for particular file ID (in case of
            # duplicating names) -- no use for datetime sort...
            #fileURL = f'{project.generic_packages.path}/{glPackage.name}/{glPackage.version}/{glFile.file_name}'
            #outFPath = os.path.join(tmpDir, glFile.file_name)
            #with open(outFPath, 'wb') as f:
            #    sys.stdout.write(f'{fileURL} -> {outFPath}\n')  # XXX
            #    gl.http_get(fileURL
            #            , streamed=True
            #            , action=f.write )
            # #2: works, but has argument for particular file ID (in case of
            # duplicating names) -- no use for datetime sort...
            #with open(os.path.join(tmpDir, glFile.file_name), 'wb') as f:
            #    project.generic_packages.download(
            #            package_name=glPackage.name,
            #            package_version=glPackage.version,
            #            file_name=glFile.file_name,
            #            streamed=True,
            #            action=f.write
            #        )
        return self._packageFiles

    def open_cvmfs_transaction(self, pkgName, pkgVer
                , cvmfsServer=None
                , timeoutSec=60  # can be None
                ):
        """
        Tries to open transaction on given CVMFS share.
        Sets up on-exit handler, publishing or aborting the transaction
        at exit.
        """
        L = logging.getLogger(__name__)
        # TODO ...
        #"cvmfs-server": "na64.cern.ch",
        #"sft-root-path": "/cvmfs/na64.cern.ch/sft"
        cmds = ["cvmfs_server", "transaction", cvmfsServer]
        if timeoutSec:
            cmds += ['-t', f'{timeoutSec}']
        _, _, rc = execute_command(cmd=cmds, joinStreams=True, cwd='/')
        def _em_finalize_cvmfs_transaction(emergency):
            if not emergency:
                L.info(f' + publishing {cvmfsServer}')
                cmds = ["cvmfs_server", "publish", cvmfsServer]
                execute_command(cmd=cmds, joinStreams=True, cwd='/')
            else:
                L.warning(f' - aborting {cvmfsServer}')
                cmds = ["cvmfs_server", "abort", '-f', cvmfsServer]
                execute_command(cmd=cmds, joinStreams=True, cwd='/')
        if 0 == rc:
            self._onExit.append(_em_finalize_cvmfs_transaction)
        else:
            L.warning('Note: on-exit handler is not installed'
                    + f' for cvmfs transaction due to return code {rc}.')

    def unpack_dist_archive(self, pkgName, pkgVer, prefix=None):
        """
        Unpacks distribution archive.
        """
        if 'dist-archive' not in self._packageFiles:
            raise RuntimeError('No "dist-archive" in package files provided'
                    ' by previous stage(s).')
        if not prefix:
            raise RuntimeError('Invalid prefix argument; can\'t install cpack archive.')
        fmtDct = copy.copy(pkgVer)
        fmtDct.update(gSettings['definitions'])
        prefix = prefix.format(**fmtDct)
        pathlib.Path(prefix).mkdir(parents=True, exist_ok=True)
        # installation of cpack archive is rather simple:
        #   tar xf ${pkg_dist} -C ${INSTALL_PATH} --strip-components=1
        cmd = ['tar', 'xvf', self._packageFiles['dist-archive'], '-C', prefix, '--strip-components=1']

        outs, _, _ = execute_command(cmd)
        # collect files list (for uninstall)
        for l in outs.decode().splitlines():
            pp = pathlib.Path(*pathlib.Path(l).parts[1:])
            pp = os.path.join(prefix, pp)
            self._installedFSEntries.append(pp)


    def install_cpack_pkg(self, pkgName, pkgVer, prefix=None):
        """
        Very similar to ``unpack_dist_archive()``, but with slightly different
        naming. In principle should benefit from cpack's special features,
        but so far is unclaimed...
        """
        if 'cpack-archive' not in self._packageFiles:
            raise RuntimeError('No "cpack-archive" in package files provided'
                    ' by previous stage(s).')
        if not prefix:
            raise RuntimeError('Invalid prefix argument; can\'t install cpack archive.')
        fmtDct = copy.copy(pkgVer)
        fmtDct.update(gSettings['definitions'])
        prefix = prefix.format(**fmtDct)
        pathlib.Path(prefix).mkdir(parents=True, exist_ok=True)
        # installation of cpack archive is rather simple:
        #   tar xf ${pkg_dist} -C ${INSTALL_PATH} --strip-components=1
        cmd = ['tar', 'xvf', self._packageFiles['cpack-archive'], '-C', prefix, '--strip-components=1']

        outs, _, _ = execute_command(cmd)
        # collect files list (for uninstall)
        for l in outs.decode().splitlines():
            pp = pathlib.Path(*pathlib.Path(l).parts[1:])
            pp = os.path.join(prefix, pp)
            self._installedFSEntries.append(pp)

    def install_modulefile(self, pkgName, pkgVer, parseDependencies=False):
        L = logging.getLogger(__name__)
        if 'modulefile' not in self._packageFiles:
            raise RuntimeError('No "modulefile" in package files provided by'
                    ' previous stage(s)')
        fmtDct = {'pkgVer': pkgVer}
        fmtDct.update(gSettings['definitions'])
        mfPath = os.path.join(gSettings['modulepath'], pkgName, pkgVer['fullVersion'])
        #mfPath = os.path.realpath(os.path.expandvars(moduleFileTemplate.format(**fmtDct)))
        mfPathDir = os.path.dirname(mfPath)
        if not os.path.isdir(mfPathDir):
            pathlib.Path(mfPathDir).mkdir(parents=True, exist_ok=True)
            #os.mkdir(mfPathDir, mode=0o775)
        # check prereq-all/prereq/etc
        if parseDependencies:
            with open(self._packageFiles['modulefile'], 'r') as f:
                # For details see: https://modules.readthedocs.io/en/latest/modulefile.html#dependencies-between-modulefiles
                # Quoting: `` ...re-requirement could be expressed with
                # prereq, prereq-any, prereq-all, depends-on, always-load,
                # module load, module switch, module try-load or module
                # load-any... ``
                for line_ in f.readlines():
                    line = line_.strip()
                    if not line: continue
                    tok = line.split(None, 1)[0]  # take 1st part of whitespace split
                    if tok in ('prereq-all', 'depends-on'):
                        # take 2nd part of the line and interpret it as a list of
                        # dependencies
                        for tok in line.split()[1:]:
                            if tok in ('--optional', '--modulepath'):
                                L.warning(f'Unsupported module dependency option: "{tok}", ignored')
                                continue
                            if tok.count('/') != 1:
                                L.warning(f'Unsupported modulefile reference: "{tok}", ignored')
                                continue
                            depPkgName, depPkgVer = tok.split('/')
                            pkgData = self.depends(depPkgName, depPkgVer)
                            if not pkgData:
                                #L.error(f'Failed to resolve dependency "{tok}" with available modules.')
                                raise RuntimeError(f'Failed to resolve dependency "{tok}" with available modules.')
                            else:
                                assert type(pkgData) is dict
                                L.info(f'Depends on {tok} (saved).')
                        continue
                    if tok in ('prereq', 'prereq-any', 'depends-on', 'always-load'):
                        L.warning(f'Unsupport module dependency command "{tok}" -- can'
                                + ' verify dependency is tracked by lpkgm.')
                        continue
                    # otherwise, just ignore the line
        # copy module file
        shutil.copyfile(self._packageFiles['modulefile'], mfPath)
        self._installedFSEntries.append(mfPath)
        L.info(f'Modulefile {mfPath} installed.')


    def shell_cmd(self, pkgName, pkgVer, cmd, files=None, cwd=None, assetFiles=None):
        L = logging.getLogger(__name__)
        fmtDct = copy.copy(pkgVer)
        fmtDct.update(gSettings['definitions'])
        if files is None: files = {}
        if not assetFiles: assetFiles = []
        cmd_ = []
        for tok in cmd:
            tok_ = tok.format(**fmtDct)
            tok_ = os.path.expandvars(tok_)
            cmd_.append(tok_)
        removeCwd = False
        if cwd is None:
            removeCwd = True
            # current working dir is not provided -- create temp
            cwd = tempfile.mkdtemp(prefix=gSettings.get('tmp-dir-prefix', None))
        if not os.path.isdir(cwd):
            os.mkdir(cwd)

        # append execution environment with dependencies list
        env = dict(os.environ)
        env['_LPKGM_DEPENDENCIES'] = ':'.join('/'.join([d['package'], d['version']['fullVersion']]) \
                for d in self._dependencies)
        env['_LPKGM_TOKENS_DIR'] = gSettings['gitlab-tokens-dir']
        env['_LPKGM_PLATFORM'] = fmtDct.get('platform', 'x86_64-linux-unknown')
        env['MODULEPATH'] = gSettings['modulepath']
        if self._modulescript:
            if not os.path.isfile(self._modulescript):
                raise RuntimeError(f'Module script is not a file ("{self._modulescript}")')
            env['_LPKGM_MODULESCRIPT'] = self._modulescript
        else:
            L.warning('Note/warning: shell script is running without _LPKGM_MODULESCRIPT')

        if cwd:
            if os.path.isfile(cmd_[0]):
                # TODO: check that file is really "local" (i.e. not, say, /bin/bash)
                # this is a local script; we copy it to a tmp dir
                shutil.copy(cmd_[0], cwd)  # copy() keeps permissions and dest can be a dir
                cmd_[0] = './' + os.path.basename(cmd_[0])
            for assetFilePath_ in assetFiles:
                assetFilePath = os.path.normpath(os.path.expandvars(assetFilePath_.format(**fmtDct)))
                if not os.path.isfile(assetFilePath):
                    raise RuntimeError(f'No such (asset) file: "{assetFilePath}"')
                shutil.copy(assetFilePath, cwd)
        try:
            execute_command(cmd_, cwd=cwd, env=env, joinStreams=True)
        except Exception as e:
            if cwd and removeCwd:
                L.warning(f'Directory {cwd} is kept for investigation.')
                removeCwd = False
            raise e from None

        selectedFiles = defaultdict(list)
        for fileDefName, filePatterns in files.items():
            for filePattern in filePatterns:
                #fg = glob.glob(filePattern.format(fmtDct), root_dir=cwd):
                # root_dir parameter appeared in Python>=3.10
                if filePattern.startswith('/'):
                    fg = glob.glob(filePattern.format(fmtDct))
                else:
                    fg = glob.glob(cwd + '/' + filePattern.format(fmtDct))
                for filePath in fg:
                    fullPath = filePath if cwd is None else os.path.join(cwd, filePath)
                    selectedFiles[fileDefName].append(fullPath)
            if not selectedFiles[fileDefName]:
                raise RuntimeError(f'Error: no file(s) for "{fileDefName}" have'
                        ' been provided after execution of shell command.')
        for fileDefName, files_ in selectedFiles.items():
            mostRecentFile = list(sorted(files_, key=lambda f: os.path.getmtime(f)))
            mostRecentFile = mostRecentFile[-1]
            if fileDefName == 'installed-files-list':  # a very special type
                with open(mostRecentFile) as f:
                    for l in f:
                        fsEntry = l.strip()
                        self._installedFSEntries.append(fsEntry)
                continue  # do not consider files list as a special package file
            L.info(f'{fileDefName} provided: {mostRecentFile}')
            self._packageFiles[fileDefName] = mostRecentFile
        # set clean-up handler
        def _em_rm_cwd(emergency):
            if os.path.isdir(cwd):
                if not emergency:
                    L.info(f' + deleting {cwd}')
                    shutil.rmtree(cwd)
                else:
                    L.warning(f' - {cwd} is kept for inspection')
        if removeCwd:
            self._onExit.append(_em_rm_cwd)
