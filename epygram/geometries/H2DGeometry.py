#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Météo France (2014-)
# This software is governed by the CeCILL-C license under French law.
# http://www.cecill.info
"""
Contains the classes for Horizontal 2D geometries of fields.
"""

from __future__ import print_function, absolute_import, unicode_literals, division

from epygram import epygramError
from .D3Geometry import (D3Geometry, D3RectangularGridGeometry,
                         D3AcademicGeometry, D3RegLLGeometry,
                         D3ProjectedGeometry, D3GaussGeometry,
                         D3UnstructuredGeometry)


class H2DGeometry(D3Geometry):
    """
    Handles the geometry for a Horizontal 2-Dimensions Field.
    Abstract mother class.
    """

    _abstract = True
    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),
        )
    )

    def _consistency_check(self):
        """Check that the geometry is consistent."""
        if len(self.vcoordinate.levels) > 1:
            raise epygramError("H2DGeometry must have only one level.")
        super(H2DGeometry, self)._consistency_check()


class H2DRectangularGridGeometry(H2DGeometry, D3RectangularGridGeometry):
    """
    Handles the geometry for a rectangular Horizontal 2-Dimensions Field.
    Abstract.
    """

    _abstract = True
    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),  # inheritance priority problem
            name=dict(
                values=set(['lambert', 'mercator', 'polar_stereographic',
                              'regular_lonlat', 'academic', 'unstructured']))
        )
    )


class H2DUnstructuredGeometry(H2DRectangularGridGeometry, D3UnstructuredGeometry):
    """Handles the geometry for an unstructured Horizontal 2-Dimensions Field."""

    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),
            name=dict(
                values=set(['unstructured']))
        )
    )


class H2DAcademicGeometry(H2DRectangularGridGeometry, D3AcademicGeometry):
    """Handles the geometry for an academic Horizontal 2-Dimensions Field."""

    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),  # inheritance priority problem
            name=dict(
                values=set(['academic']))
        )
    )


class H2DRegLLGeometry(H2DRectangularGridGeometry, D3RegLLGeometry):
    """
    Handles the geometry for a Regular Lon/Lat Horizontal 2-Dimensions Field.
    """

    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),  # inheritance priority problem
            name=dict(
                values=set(['regular_lonlat']))
        )
    )


class H2DProjectedGeometry(H2DRectangularGridGeometry, D3ProjectedGeometry):
    """
    Handles the geometry for a Projected Horizontal 2-Dimensions Field.
    """

    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),  # inheritance priority problem
            name=dict(
                values=set(['lambert', 'mercator', 'polar_stereographic', 'space_view'])),
        )
    )


class H2DGaussGeometry(H2DGeometry, D3GaussGeometry):
    """
    Handles the geometry for a Global Gauss grid Horizontal 2-Dimensions Field.
    """

    _collector = ('geometry',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['H2D'])),  # inheritance priority problem
            name=dict(
                values=set(['rotated_reduced_gauss', 'reduced_gauss', 'regular_gauss'])),
        )
    )
