#!/bin/bash

# tclsh is used by Linux Environment modules and is not provided by
# default Alma9 build typically used in CERN (this is why we build here
# a custom one). Produced package does not have build config
set -e

VERSION=$1  # e.g. 8.6.14, see: https://www.tcl.tk/software/tcltk/download.html
PREFIX=$2
# ...or http://prdownloads.sourceforge.net/tcl/tcl8.6.14-src.tar.gz

# Override environment
if [ -f $PREFIX/../../this-env.sh ] ; then
    source $PREFIX/../../this-env.sh 
fi

wget http://prdownloads.sourceforge.net/tcl/tcl${VERSION}-src.tar.gz
rm -rf tcl.src/
mkdir tcl.src/
tar xf tcl$VERSION-src.tar.gz -C tcl.src/ --strip-components=1

pushd tcl.src/unix
# we first configure it to install on the directory which we're going
# to remove, just to check the files...
set +e
XXXDIR=/tmp/tcl.${VERSION}.xxx/
rm -rf $XXXDIR
./configure --prefix=${XXXDIR}
make -j4 install

# get list of installed files, omitting the XXXDIR prefix
find $XXXDIR -type f -exec realpath -s --relative-to="${XXXDIR}" {} \; > installed-files_.txt
# wipe the fake prefix
rm -rf "${XXXDIR}"

# verify, that there is no file overwrite
while read relPath ; do
    absPath=$(readlink -f "${PREFIX}/${relPath}")
    if [ -f "${absPath}" ] ; then
        &> echo "Error: file $absPath already exists (refusing overwrite)."
	exit 1
    fi
done <installed-files_.txt

# now we re-configure the package with proper prefix and re-install
./configure --prefix=${PREFIX}
set -e
make -j4 install

# make sure installed files are really installed
while read relPath ; do
    absPath=$(readlink -f "${PREFIX}/${relPath}")
    if [ ! -f "${absPath}" ] ; then
        &> echo "Error: file $absPath does not exist or is not a file (assumed to be installed)."
	exit 1
    fi
    echo "${absPath}" >> installed-files.txt
done <installed-files_.txt
popd

