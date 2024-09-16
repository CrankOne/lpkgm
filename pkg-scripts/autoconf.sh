#!/bin/bash

set -e

VERSION=$1  # e.g. 2.72, see: https://ftp.gnu.org/gnu/autoconf/
PREFIX=$2

# Override environment
if [ -f $PREFIX/../../this-env.sh ] ; then
    source $PREFIX/../../this-env.sh 
fi

wget https://ftp.gnu.org/gnu/autoconf/autoconf-${VERSION}.tar.gz
rm -rf autoconf.src/
mkdir autoconf.src/
tar xf autoconf-$VERSION.tar.gz -C autoconf.src/ --strip-components=1

pushd autoconf.src

# we first configure it to install on the directory which we're going
# to remove, just to check the files...
XXXDIR=/tmp/autoconf.${VERSION}.xxx/
rm -rf $XXXDIR
./configure --prefix=${XXXDIR}
make -j4 install
#
# get list of installed files, omitting the XXXDIR prefix
find $XXXDIR -type f -exec realpath -s --relative-to="${XXXDIR}" {} \; > installed-files_.txt
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
done <installed-files_.txt

# now we re-configure the package with proper prefix and re-install
./configure --prefix=${PREFIX}
make -j4 install

# make sure installed files are really installed
while read relPath ; do
    absPath=$(readlink -f "${PREFIX}/${relPath}")
    if [ ! -f "${absPath}" ] ; then
        >&2 echo "Error: file $absPath does not exist or is not a file (assumed to be installed)."
	exit 1
    fi
    echo "${absPath}" >> installed-files.txt
done <installed-files_.txt
popd

