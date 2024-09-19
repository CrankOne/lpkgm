#!/usr/bin/env python3

import os, sys, logging, json, copy, shutil, subprocess, re
import traceback, pathlib
from fnmatch import fnmatch
from datetime import datetime
import prettytable
import gitlab

from lpkgm.settings import read_settings_file, gSettings
from lpkgm.dependencies import PkgGraph
from lpkgm.utils import packages, pkg_manifest_file_path, stats_summary, \
        get_package_manifests, sizeof_fmt
from lpkgm.installer import Installer

#                                                                     ________
# __________________________________________________________________/ Actions
#
# Entry point forwards execution to one of this functions (install, remove,
# show).

def install_package(pkgName, pkgVerStr, pkgSettings, use=None, modulescript=None, depGraph=None):
    L = logging.getLogger(__name__)
    if not use: use=[]
    # check existing package file in registry
    pkgInstallManifestFilePath = pkg_manifest_file_path(pkgName, pkgVerStr)
    if os.path.isfile(pkgInstallManifestFilePath):
        raise RuntimeError(f"Package \"{pkgName}\" of version \"{pkgVerStr}\" installed"
                f" (file {pkgInstallManifestFilePath} exists).")
    # try to parse version expression, if specified
    pkgVer = None
    for rxs in pkgSettings['version-regex']:
        rx = re.compile(rxs)
        m = rx.match(pkgVerStr)
        if not m: continue
        pkgVer = pkgSettings.get('default-version-values', {})
        pkgVer.update(dict((k, v) for k, v in m.groupdict().items() if v is not None))
        pkgVer['fullVersion'] = pkgVerStr
    if not pkgVer:
        errStr =f'Failed to parse version expression "{pkgVerStr}"' \
                + ' with any of version parsing expression(s) specified for' \
                + f' package \"{pkgName}\":\n' 
        for rxs in pkgSettings['version-regex']:
            errStr += f'    {rxs}\n'
        errStr += f'Please, check the version expression or correct the' \
                + ' settings file.'
        L.error(errStr)
        return False

    # Instantiate installer pipeline (with respect to specified stages)
    installer = Installer( pkgSettings['install-stages']
            , modulescript=modulescript
            , pkgDefs=pkgSettings['definitions']
            )

    # Resolve dependencies
    usedDeps = set()
    if 'depends' in pkgSettings.keys() and pkgSettings['depends']:
        for providedDep in use:
            if providedDep[0] not in set(d['name'] for d in pkgSettings['depends']):
                L.warning('"use" argument'
                        + f' {providedDep[0]}/{providedDep[1]} is not in demand'
                        + f' of "{pkgName}".')
                continue
            installer.resolve_dependency(*providedDep)
            usedDeps.add(providedDep[0])
    # Check that use/depends are consistent
    expectedDeps = set((dep['name'], dep.get('required', True)) for dep in pkgSettings.get('depends', []))
    for expectedDep in expectedDeps:
        if expectedDep[0] in usedDeps: continue
        if expectedDep[1]:
            raise RuntimeError(f'Missing required package {expectedDep[0]} (of {pkgName}).')
        else:
            L.info('Missing optional package {expectedDep[0]} (of {pkgName})')

    # Perform installation
    if not installer(pkgName, pkgVer):
        L.critical(f'Failed to install {pkgName}-{pkgVerStr}.')
        installer.on_exit(emergency=True)
        return False
    # update package file in registry
    pkgDir = os.path.dirname(pkgInstallManifestFilePath)
    if not os.path.isdir(pkgDir):
        pathlib.Path(pkgDir).mkdir(parents=True, exist_ok=True)
    stats = installer.stats
    pkgInfo = {
        "package": pkgName,
        "version": pkgVer or pkgVerStr,
        "installedAt": datetime.utcnow().isoformat(),
        # these objects depend on the package details
        "fsEntries": installer.installedFiles,
        "stats": stats,
        "dependencies": installer.dependenciesList,
        # ...
    }
    with open(pkgInstallManifestFilePath, "w") as f:
        json.dump(pkgInfo, f, indent=2, sort_keys=True)
    # append dep graph if need
    if depGraph:
        if installer.dependenciesList:
            for dep in installer.dependenciesList:
                depGraph.add((pkgName, pkgVerStr), tuple(dep))
        else:
            depGraph.add_pkg(pkgName, pkgVerStr)
    # run clean-up procedures
    installer.on_exit(emergency=False)
    L.info(f'Package "{pkgName}" of version "{pkgVerStr}"'
            + f' installed ({stats_summary(stats)})')
    return True

def uninstall_package(pkgName, pkgData, depGraph=None):
    L = logging.getLogger(__name__)
    pkgVerStr = pkgData['version']['fullVersion']
    L.info(f'Removing package "{pkgName}" of version "{pkgVerStr}"'
            + f' ({stats_summary(pkgData["stats"])}), installed'
            + f' at {pkgData["installedAt"]}')
    assert pkgData
    # recursively remove files and directories from install manifest
    try:
        dirs = set()
        for fsEntry in pkgData['fsEntries']:
            if os.path.isfile(fsEntry) or os.path.islink(fsEntry):
                dirs.add(os.path.dirname(fsEntry))
            if os.path.isdir(fsEntry):
                dirs.add(fsEntry)
                continue
            if os.path.islink(fsEntry):
                L.debug(f'Un-linking {fsEntry}')
                os.unlink(fsEntry)
                continue
            if os.path.isfile(fsEntry):
                L.debug(f'Deleting file {fsEntry}')
                os.remove(fsEntry)
                continue
            L.warning(f'Unknown type of filesystem entry: {fsEntry}')
        while dirs:
            longestPath = list(sorted(dirs, key=lambda de: len(de)))[-1]
            if os.path.isdir(longestPath):
                L.debug(f'Removing empty dirs starting from {longestPath}')
                try:
                    os.removedirs(longestPath)
                except OSError as e:
                    if not str(e).startswith('[Errno 39] Directory not empty'):
                        L.error(f'{str(e)}')
                        raise
            dirs.remove(longestPath)
    except Exception as e:
        L.error('Error occured during removing FS entrie(s):')
        #traceback.print_exc()
        L.exception(e)
        L.error(f'Package manifest file {pkg_manifest_file_path(pkgName, pkgVerStr)}'
                + ' kept for further investigation. Log:')
        return False
    # Delete manifest file
    L.info(f'Deleting package manifest {pkg_manifest_file_path(pkgName, pkgVerStr)}')
    os.remove(pkg_manifest_file_path(pkgName, pkgVerStr))
    if depGraph:
        try:
            for dep in pkgData['dependencies']:
                depGraph.remove((pkgName, pkgVerStr), dep)
            depGraph.remove_pkg(pkgName, pkgVerStr)
        except Exception as e:
            L.error('Failed to update dependency graph. Run lpkgm next time with --dep-recache'
                    ' to fix broken graph.')
            L.exception(e)
    L.info(f'"{pkgName}" of version "{pkgVerStr}" removed.')
    return True

def uninstall_packages(pkgNamePat, pkgVerStrPat, pkgs, autoConfirm=False, depGraph=None, keep=None):
    L = logging.getLogger(__name__)
    rmQueue = []
    if keep is None: keep=[]
    for pkgName, pkgSettings in pkgs:
        pkgData = get_package_manifests(pkgName, pkgVerStrPat, exclude=list(k.split('/') for k in keep))
        if not pkgData:
            if pkgNamePat == pkgName:
                raise RuntimeError(f'Package is not installed: {pkgName} of'
                    + f' version "{pkgVerStrPat}" (no install manifest file exist)')
            else:
                raise RuntimeError(f'Package is not installed: {pkgName} (matching "{pkgNamePat}") of'
                    + f' version "{pkgVerStrPat}" (no install manifest file exist)')
        for pkgDatum in pkgData:
            # TODO: check if package is in the dependencies list of something
            #       and prevent user from breaking dependencies.
            rmQueue.append((pkgName, pkgDatum))
    assert rmQueue
    rmInfoMsg = f'Packages selected for deletion ({len(rmQueue)}):'
    pTable = prettytable.PrettyTable()
    pTable.field_names = ['Package', 'Version', 'Stats']  # TODO: dependency of?
    pTable.align['Package'] = 'r'
    pTable.align['Version'] = 'l'
    blocks = []
    for pkgName, pkgDatum in rmQueue:
        #rmInfoMsg += f'\n    {pkgName}/{pkgDatum["version"]["fullVersion"]}\t' \
        #          +'{stats_summary(pkgDatum["stats"])}\t{pkgDatum["installedAt"]}'
        pkgVerStr = pkgDatum['version']['fullVersion']
        pTable.add_row([pkgName, pkgVerStr, stats_summary(pkgDatum["stats"])])
        if depGraph:
            # check we really can delete the package not breaking any dependant packages
            provides = depGraph.dependency_of(pkgName, pkgVerStr)
            if provides:
                providesStr = ', '.join(f'{depName}/{depVer}' for depName, depVer in provides)
                blocks.append(f'    {pkgName}/{pkgVerStr} is needed by {providesStr}')
    rmInfoMsg += '\n' + str(pTable)
    L.info(rmInfoMsg)
    if blocks:
        L.critical('Following issues found for deletion request:\n' + '\n'.join(blocks))
        raise RuntimeError('Installed packages depends on packages queued for removal.')
    if not autoConfirm:
        if sys.stdin.isatty():
            answer = ''
            while answer.lower() not in ('yes', 'no'):
                answer = input('\033[1mConfirm deletion of selected packages?\033[0m (please, type "yes" or "no"): ')
                if 'no' == answer.lower():
                    return False
                elif 'yes' == answer.lower():
                    break
        else:
            # no autoconfirm option given, not a prompt -- apparently, a batch
            # run, we abort deletion as a precaution
            L.warning('Automatic confirmation is not set, terminal is not a TTY,'
                    + f' refusing delete {len(rmQueue)} package(s).')
            return False
    L.info('Deleting package(s)...') 
    for pkgName, pkgDatum in rmQueue:
        pkgVerStr = pkgDatum['version']['fullVersion']
        uninstall_package(pkgName, pkgDatum, depGraph=depGraph)
    return True

def show_tree(outStream, pkgName, pkgVerStr, depGraph):
    # TODO: if pkgName and/or pkgVer is given, retrieve subtree
    nx.write_network_text(depGraph.g)
    #print(dg.in_edges(('xz', '5.6.2-opt')))  # input edges means that this package is a dep for smt other
    pass

def show(outStream, pkgName, pkgVer, format_='ascii', depGraph=None):
    L = logging.getLogger(__name__)
    pTable = None
    if not pkgVer:
        # in this mode we list all installed packages in a table:
        #   <name> <version> <size> <installed-at> <dependencies-list>
        # To do so, retrieve all `.json` files from registry dir, which
        # content has at least "package" and "version" attributes
        overallSize = 0
        pTable = None
        #for pkgFilePath in glob.glob(gSettings['packages-registry-dir'] + '/*/*.json'):
        #    with open(pkgFilePath, 'r') as pkgFile:
        #        pkgData = json.load(pkgFile)
        #    if not ('package' in pkgData and 'version' in pkgData):
        #        L.warning(f'Warning: file "{pkgFilePath}" does not'
        #                + ' seem to be a package file (ignored).')
        #        continue  # omit .json as it is not the package file
        #    if pkgName and pkgName.lower() not in pkgData['package'].lower(): continue
        for pkgData, pkgFilePath in packages(pkgName, pkgVer):
            if not pTable:
                pTable = prettytable.PrettyTable()
                #pTable.border = False
                pTable.field_names = ['Package', 'Version', 'Size', 'Time', 'Depends']
                pTable.align['Package'] = 'r'
                pTable.align['Version'] = 'l'
                pTable.align['Depends'] = 'l'
            depStr = 'N/A'
            if 'dependencies' in pkgData.keys() and pkgData['dependencies']:
                depStr = '\n'.join('/'.join(d) for d in pkgData['dependencies'])
            pTable.add_row([pkgData['package']
                , pkgData['version'] if type(pkgData['version']) is str else pkgData['version']['fullVersion']
                , sizeof_fmt(pkgData['stats']['size'])
                , datetime.fromisoformat(pkgData['installedAt']).strftime( '%d/%m/%y, %H:%M' )
                , depStr
                ])
            overallSize += pkgData['stats']['size']
        if not pTable:
            if format_ == 'ascii':
                outStream.write(" (no packages installed"
                        + f" -- \"{gSettings['packages-registry-dir']}\" is empty).\n")
            elif format_ == 'html':
                outStream.write("<span class=\"error\">No packages installed"
                        + f" -- \"{gSettings['packages-registry-dir']}\" is empty</span>\n")
            elif format_ == 'json':
                outStream.write('{"error":"no packages installed'
                        + f' -- \\\"{gSettings["packages-registry-dir"]}\\\" is empty\"'+'}\n')
            else:
                assert False
            return True
        else:
            if format_ == 'ascii':
                outStream.write(str(pTable) + '\n')
                outStream.write(f"{sizeof_fmt(overallSize)} overall\n")
            elif format_ == 'html':
                outStream.write(pTable.get_html_string() + '\n')
            elif format_ == 'json':
                outStream.write(pTable.get_json_string() + '\n')
            else:
                assert False
            return True
    else:
        # both name and version specified -- print details on package
        assert pkgName and pkgVer
        pkgData = get_package_manifests(pkgName, pkgVer)
        # TODO: ascii pretty print
        outStream.write(json.dumps(pkgData, sort_keys=True, indent=2) + '\n')
        return True

#                                                                  ___________
# _______________________________________________________________/ Entry point

def lpkgm_run_from_cmd_args(argv):
    import argparse
    p = argparse.ArgumentParser(prog='lpkgm')
    # common options
    p.add_argument('-c', '--settings', help='Settings file providing package'
            ' definitions', default=os.getenv('LPKGM_SETTINGS', "./lpkgm-settings.json"))
    #p.add_argument('-R', '--root-prefix', help='Root prefix for FS tree')
    p.add_argument('-D', '--define', help='Define common string formatting'
            ' definition.', action='append')
    p.add_argument('--dep-recache', help='Forces re-build of dependency graph cache.'
            , action='store_true')
    # sub-parsers (subcommands)
    subparsers = p.add_subparsers(help='Action options', dest='mode')
    installP = subparsers.add_parser('install', help='Install package'
            , aliases=['add'])
    installP.add_argument('pkgName', help='Name of package to install')
    installP.add_argument('pkgVersion', help='Version of package to install')
    installP.add_argument('-u', '--use', help='Resolve package dependency to'
            ' another package. Expected format is <pkgName>/<pkgVersion>'
            , action='append', type=lambda item: item.split('/') )
    installP.add_argument('--module-script', help='Modules environment script. May be required'
            ' by some packages.')
    # ... other args for install mode
    removeP = subparsers.add_parser('remove', help='Removes package'
            , aliases=['delete', 'uninstall', 'rm'])
    removeP.add_argument('pkgName', help='Name of package to remove')
    removeP.add_argument('pkgVersion', help='Version of package to remove')
    removeP.add_argument('-y', help='Do not prompt for deletion.', dest='autoConfirm'
            , action='store_true')
    removeP.add_argument('-k', '--keep', help='Exclude certain wildcard match from selection'
            , action='append')
    # ... other args for remove mode
    showP = subparsers.add_parser('show', help='Prints details of defined or installed items'
            , aliases=['inspect', 'list'])
    showP.add_argument('pkgName', help='Name of package to show', default=None, nargs='?')
    showP.add_argument('pkgVersion', help='Version of package to show', default=None, nargs='?')
    showP.add_argument('-t', '--tree', help='Dependencies tree view (instead of table).'
            , action='store_true')
    #showP.add_argument('--depends')
    #showP.add_argument('--format', help='Changes output format for summary'
    #        ' shown.', choices=('ascii', 'html', 'json'), default='ascii'
    #        , dest='format_')
    # ... other args for show mode

    args = p.parse_args(argv[1:])
    L = logging.getLogger(__name__)
    # read settings file and update globals
    # NOTE: returned object is the original JSON, while gSettings is updated with
    # expanded vars, normalized paths, etc, as a side effect of `read_settings_file()`
    # function.
    origSettingsObj = read_settings_file(args.settings, definitions=args.define)
    # get package config, if pkgName specified
    pkgSettings = []
    if args.mode in ('install', 'add',  'remove', 'uninstall', 'delete', 'rm') and args.pkgName:
        # consider pkgName as as shell-style wildcard (use fnmatch)
        for k in gSettings['packages'].keys():
            if not fnmatch(k, args.pkgName): continue
            pkgSettings.append((k, gSettings['packages'][k]))
        if not pkgSettings:
            L.critical(f'Package "{args.pkgName}" is not known.')
            return False
    # check access to packages dir
    gSettings['packages-registry-dir'] = os.path.normpath(gSettings['packages-registry-dir'])
    if args.mode in ('install', 'remove') \
            and not os.path.isdir(gSettings['packages-registry-dir']):
        #or not os.access(gSettings['packages-registry-dir'], os.W_OK)):
        registryDir = gSettings['packages-registry-dir']
        if registryDir != origSettingsObj['packages-registry-dir']:
            # (expanded not identically)
            L.critical(f'Directory "{gSettings["packages-registry-dir"]}"'
                    + f' (resolved to "{registryDir}") does not exist.')# or is not'
                    #+ ' writable.\n')
        else:
            L.critical(f'Directory "{registryDir}" does not exist.') # or is not'
                    #+ ' writable.\n')
        return False
    # run specific procedure
    try:
        with PkgGraph( forceRebuild=args.dep_recache
                , filePath=os.path.join(gSettings['packages-registry-dir'], 'deps.nx.gpickle')) as depGraph:
            if args.mode in ('install', 'add'):
                if not pkgSettings:
                    L.critical('No package matching "{args.pkgName}".')
                    return False
                if len(pkgSettings) > 1:
                    L.critical('Multiple packages match "{args.pkgName}": '
                            + ', '.join(p[0] for p in pkgSettings))
                    return False
                return install_package(args.pkgName, args.pkgVersion, pkgSettings[0][1]
                        , use=args.use
                        , modulescript=args.module_script
                        , depGraph=depGraph
                        )
            elif args.mode in ('remove', 'delete', 'uninstall', 'rm'):
                if not pkgSettings:
                    L.critical('No package matching "{args.pkgName}".')
                    return False
                assert pkgSettings
                return uninstall_packages( args.pkgName, args.pkgVersion, pkgSettings
                        , depGraph=depGraph
                        , autoConfirm=args.autoConfirm
                        , keep=args.keep
                        )
            elif args.mode in ('show', 'inspect', 'list'):
                if not args.tree:
                    return show(sys.stdout, args.pkgName, args.pkgVersion, format_='ascii'
                            , depGraph=depGraph )
                else:
                    return show_tree(sys.stdout, args.pkgName, args.pkgVersion, depGraph)
            else:
                L.critical(f'Error: unknown sub-command: "{args.mode}".')
                assert False
    except Exception as e:
        if logging.DEBUG >= logging.root.level:
            L.critical(f'Error occured during execution of {args.mode}:')
            traceback.print_exc()
        else:
            L.critical(f'Exit due to an error: {str(e)}')
        return False

# Logging config for "app mode" (when running as a script,
# configured from main())
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
            'level': 'NOTSET',
            'propagate': False
        },
    }
}

def main():
    import logging.config
    loglevel = os.getenv('LOGLEVEL', 'INFO')
    gLoggingConfig['handlers']['default']['level'] = loglevel
    gLoggingConfig['loggers']['']['level'] = loglevel
    logging.config.dictConfig(gLoggingConfig)
    sys.exit(0 if lpkgm_run_from_cmd_args(sys.argv) else 1)

if "__main__" == __name__:
    main()
