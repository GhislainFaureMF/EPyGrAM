#!/bin/bash

# Script de deploiement d'EPyGrAM sur /home/common/epygram (CNRM) et autres machines

# Parse args
if [ "$1" == "-h" ]; then
    echo "Usage: deploy.sh [VERSION]"
    echo "<VERSION> being the distant label, e.g. 'dev'"
    echo "If no VERSION is provided, the numbered version found in epygram/__init__.py is used."
	echo "The distant installation is labelled EPyGrAM-<VERSION>"
    exit
fi
VERSION=$1
if [ "$VERSION" == "" ]; then
    VERSION=`grep __version__ epygram/__init__.py | awk '{print $3}' | awk -F "'" '{print $2}'`
fi
EPYGRAM_DIR="public/EPyGrAM-$VERSION"


# Platforms to push onto
sxcoope1=1  # from which are synchronised all CNRM workstations
vxdev64=0  # vxdev64: development server @ CNRM (OS updates)
pagre=1  # COMPAS server, from which it is replicated onto the others
beaufix=1
prolix=1
epona=1
belenos=1
taranis=0


# Filters
to_exclude4all=''
for elem in playground tests VERSIONing.txt deploy.sh mktar.sh apptools/*.pyc site/arpifs4py/libs4py_*.so epygram/doc_sphinx/source/gallery/inputs *.ipynb_checkpoints*
do
  to_exclude4all="$to_exclude4all --exclude $elem"
done
no_source_doc=''
for elem in epygram/doc_sphinx/source/* epygram/doc_sphinx/build/* epygram/doc_sphinx/Makefile epygram/doc_sphinx/mk_html_doc.sh
do
  no_source_doc="$no_source_doc --exclude $elem"
done
no_pyc='--exclude *.pyc --exclude *__pycache__*'
no_doc='--exclude epygram/doc_sphinx/*'
no_libs4py='--exclude site/arpifs4py/libs4py.so'
no_arpifs4py='--exclude site/arpifs4py'
no_epyweb='--exclude site/epyweb'

# Filters specific to platforms
to_exclude4sxcoope1="$to_exclude4all"
to_exclude4vxdev64="$to_exclude4all $no_pyc $no_source_doc"
to_exclude4pagre="$to_exclude4all $no_pyc $no_arpifs4py"
to_exclude4bull="$to_exclude4all $no_pyc $no_source_doc $no_libs4py $no_epyweb"


# Rsync
logger="EPyGrAM-$VERSION deployed on:\n"
echo "------------------------------------------------------"
if [ "$sxcoope1" == 1 ]; then
  echo "...sxcoope1..."
  rsync -avL * sxcoope1:$EPYGRAM_DIR $to_exclude4sxcoope1
  logger="$logger - sxcoope1\n"
fi
echo "------------------------------------------------------"
if [ "$vxdev64" == 1 ]; then
  echo "...vxdev64..."
  rsync -avL * vxdev64:$EPYGRAM_DIR $to_exclude4vxdev64
  logger="$logger - vxdev64\n"
fi
echo "------------------------------------------------------"
if [ "$pagre" == 1 ]; then
  echo "...pagre..."
  rsync -avL * pagre:$EPYGRAM_DIR $to_exclude4pagre
  logger="$logger - pagre\n"
fi
echo "------------------------------------------------------"
if [ "$beaufix" == 1 ]; then
  echo "...beaufix..."
  rsync -avL * beaufix:$EPYGRAM_DIR $to_exclude4bull
  logger="$logger - beaufix\n"
fi
echo "------------------------------------------------------"
if [ "$prolix" == 1 ]; then
  echo "...prolix..."
  rsync -avL * prolix:$EPYGRAM_DIR $to_exclude4bull
  logger="$logger - prolix\n"
fi
echo "------------------------------------------------------"
if [ "$epona" == 1 ]; then
  echo "...epona..."
  rsync -avL * epona:$EPYGRAM_DIR $to_exclude4bull
  logger="$logger - epona\n"
fi
echo "------------------------------------------------------"
if [ "$belenos" == 1 ]; then
  echo "...belenos..."
  rsync -avL * belenos:$EPYGRAM_DIR $to_exclude4bull
  logger="$logger - belenos\n"
fi
echo "------------------------------------------------------"
if [ "$taranis" == 1 ]; then
  echo "...taranis..."
  rsync -avL * taranis:$EPYGRAM_DIR $to_exclude4bull
  logger="$logger - taranis\n"
fi


# Log final
echo "------------------------------------------------------"
echo -e $logger
echo "Don't forget to link *libs4py.so* on necessary machines (supercomputers) !"

