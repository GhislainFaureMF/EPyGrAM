#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Météo France (2014-)
# This software is governed by the CeCILL-C license under French law.
# http://www.cecill.info

from __future__ import print_function, absolute_import, division, unicode_literals

from unittest import main

from . import abstract_testclasses as abtc


class TestFA(abtc.TestFMT):
    basename = 'FA'
    len = 134


class TestGRIB(abtc.TestFMT):
    basename = 'GRIB'
    len = 3


class TestNetCDF(abtc.TestFMT):
    basename = 'netCDF'
    len = 9


class TestDDHLFA(abtc.TestFMT):
    basename = 'ddh.LFA'
    len = 160


if __name__ == '__main__':
    main(verbosity=2)
