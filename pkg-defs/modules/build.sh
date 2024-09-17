#!/bin/bash

# tclsh is used by Linux Environment modules and is not provided by
# default Alma9 build typically used in CERN (this is why we build here
# a custom one). Produced package does not have build config

VERSION=$1  # e.g. v5.4.0, see: https://github.com/cea-hpc/modules/releases/
PREFIX=$(readlink -f $2)

set -e

# Override environment
if [ -f $PREFIX/../../this-env.sh ] ; then
    source $PREFIX/../../this-env.sh 
fi

wget https://github.com/cea-hpc/modules/archive/refs/tags/${VERSION}.tar.gz
rm -rf modules.src/
mkdir modules.src/
tar xf $VERSION.tar.gz -C modules.src/ --strip-components=1

pushd modules.src

#>&2 echo "_LPKGM_DEPENDENCIES=\"$_LPKGM_DEPENDENCIES\""  # XXX
# ^^^ we need autotools and tclsh here.
#for dep in "${_LPKGM_DEPENDENCIES[@]}" ; do
#    if [[ $dep == tcl* ]] ; then
#        TCL_VERSION=${dep##*/}
#	TCL_MJ_MN=${TCL_VERSION#*.}
#    fi
#done
if [ ! -f $PREFIX/lib/tclConfig.sh ] ; then
    >&2 echo "Error: no TCL config (no file $PREFIX/lib/tclConfig.sh)"
fi
source $PREFIX/lib/tclConfig.sh

# we first configure it to install on the directory which we're going
# to remove, just to check the files...
XXXDIR=/tmp/modules.${VERSION}.xxx/
rm -rf $XXXDIR

# NOTE: autoreconf and tclsh provided by autotools must be taken from PREFIX
# NOTE: for some reason, ./configure does NOT re-set --prefix for some files
#	that are generated at second time. 
PATH=$PATH:$PREFIX/bin
./configure \
	--prefix=${XXXDIR} \
	--with-tcl=${PREFIX}/lib/ \
	--with-tclsh=${PREFIX}/bin/tclsh${TCL_VERSION}
make -j4 install

#
# get list of installed files, omitting the XXXDIR prefix
find $XXXDIR -type f -exec realpath -s --relative-to="${XXXDIR}" {} \; > ../installed-files_.txt
# wipe the fake prefix
rm -rf "${XXXDIR}"

# verify, that there is no file overwrite
while read relPath ; do
    set +e
    absPath=$(readlink -f "${PREFIX}/${relPath}")
    set -e
    if [ -f "${absPath}" ] ; then
        >&2 echo "Error: file $absPath already exists (refusing overwrite)."
	exit 1
    fi
done <../installed-files_.txt

popd

# delete old src dir to reconfigure
rm -rf modules.src
mkdir modules.src/
tar xf $VERSION.tar.gz -C modules.src/ --strip-components=1
pushd modules.src

# now we re-configure the package with proper prefix and re-install
./configure \
        --prefix=${PREFIX} \
	--with-tcl=${PREFIX}/lib/ \
	--with-tclsh=${PREFIX}/bin/tclsh${TCL_VERSION}
make -j4 install

# make sure installed files are really installed
while read relPath ; do
    absPath=$(readlink -f "${PREFIX}/${relPath}")
    if [ ! -f "${absPath}" ] ; then
        >&2 echo "Error: file $absPath does not exist or is not a file (assumed to be installed)."
	exit 1
    fi
    echo "${absPath}" >> installed-files.txt
done <../installed-files_.txt
popd

