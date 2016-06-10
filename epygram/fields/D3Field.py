#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Météo France (2014-)
# This software is governed by the CeCILL-C license under French law.
# http://www.cecill.info
"""
Contains the class that handle a Horizontal 2D field.
"""

import copy
import numpy
import sys

import footprints
from footprints import FPDict, FPList, proxy as fpx
from epygram import config, epygramError
from epygram.util import write_formatted, stretch_array
from epygram.base import Field, FieldSet, FieldValidity, FieldValidityList, Resource
from epygram.geometries import D3Geometry, SpectralGeometry



class D3CommonField(Field):
    """
    3-Dimensions common field class.
    """

    _collector = ('field',)
    _abstract = True
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['3D']),
                info="Type of Field geometry.")
        )
    )

    @property
    def spectral(self):
        """Returns True if the field is spectral."""
        return self.spectral_geometry is not None


##############
# ABOUT DATA #
##############

    def getvalue_ll(self, lon=None, lat=None, level=None, validity=None,
                    interpolation='nearest',
                    neighborinfo=False,
                    one=True,
                    external_distance=None):
        """
        Returns the value of the field on point of coordinates (*lon, lat, level*): \n
        - if *interpolation == 'nearest'* (default), returns the value of the
          nearest neighboring gridpoint;
        - if *interpolation == 'linear'*, computes and returns the field value
          with linear spline interpolation;
        - if *interpolation == 'cubic'*, computes and returns the field value
          with cubic spline interpolation.
        *level* is the True level not the index of the level. Depending on the
        vertical coordinate, it could be expressed in Pa, m.
        *validity* is a FieldValidity or a FieldValidityList instance

        If *neighborinfo* is set to **True**, returns a tuple
        *(value, (lon, lat))*, with *(lon, lat)* being the actual coordinates
        of the neighboring gridpoint (only for *interpolation == 'nearest'*).

        *lon* and *lat* may be longer than 1.
        If *one* is False and len(lon) is 1, returns [value] instead of value.  
        
        *external_distance* can be a dict containing the target point value
        and an external field on the same grid as self, to which the distance
        is computed within the 4 horizontally nearest points; e.g. 
        {'target_value':4810, 'external_field':an_H2DField_with_same_geometry}.
        If so, the nearest point is selected with
        distance = |target_value - external_field.data|
        
        Warning: for interpolation on Gauss geometries, requires the
        :mod:`pyproj` module.
        """

        if isinstance(validity, FieldValidity):
            myvalidity = FieldValidityList(validity)
        else:
            myvalidity = validity
        if self.spectral:
            raise epygramError("field must be gridpoint to get value of a" + \
                               " lon/lat point.")
        if len(self.validity) > 1 and myvalidity is None:
            raise epygramError("*validity* is mandatory when there are several validities")
        if self.geometry.datashape['k'] and level is None:
            raise epygramError("*level* is mandatory when field has a vertical coordinate")
        if (self.geometry.datashape['j'] or self.geometry.datashape['i']) and \
           (lon is None or lat is None):
            raise epygramError("*lon* and *lat* are mandatory when field has an horizontal extension")

        maxsize = numpy.array([numpy.array(dim).size for dim in [lon, lat, level] if dim is not None]).max()
        if myvalidity is not None:
            maxsize = max(maxsize, len(myvalidity))

        #We look for indexes for vertical and time coordinates (no interpolation)
        if myvalidity is None:
            my_t = numpy.zeros(maxsize, dtype=int)
        else:
            my_t = []
            for v in myvalidity:
                for t in range(len(self.validity)):
                    if v == self.validity[t]:
                        my_t.append(t)
                        break
            my_t = numpy.array(my_t)
            if my_t.size != maxsize:
                if my_t.size != 1:
                    raise epygramError("validity must be uniq or must have the same length as other indexes")
                my_t = numpy.array([my_t.item()] * maxsize)
        if len(self.geometry.vcoordinate.levels) != len(set(self.geometry.vcoordinate.levels)):
            raise epygramError('Some levels are represented twice in levels list.')
        if level is None:
            my_k = numpy.zeros(maxsize, dtype=int)
        else:
            my_level = numpy.array(level)
            if my_level.size == 1:
                my_level = numpy.array([my_level.item()])
            my_k = []
            for l in my_level:
                my_k.append(self.geometry.vcoordinate.levels.index(l))
            my_k = numpy.array(my_k)
            if my_k.size != maxsize:
                if my_k.size != 1:
                    raise epygramError("k must be scalar or must have the same length as other indexes")
                my_k = numpy.array([my_k.item()] * maxsize)
        my_lon = numpy.array(lon)
        if my_lon.size == 1:
            my_lon = numpy.array([my_lon.item()])
        my_lat = numpy.array(lat)
        if my_lat.size == 1:
            my_lat = numpy.array([my_lat.item()])
        if my_lon.size != maxsize or my_lat.size != maxsize:
            raise epygramError("lon and lat must have the same length and the same length as level and validity")

        if interpolation == 'nearest':
            (ri, rj) = self.geometry.nearest_points(lon, lat, 'nearest',
                                                    external_distance=external_distance)
            value = self.getvalue_ij(ri, rj, my_k, my_t, one=one)
            if neighborinfo:
                (lon, lat) = self.geometry.ij2ll(ri, rj)
                if numpy.shape(lon) in ((1,), ()):
                    lon = float(lon)
                    lat = float(lat)
                value = (value, (lon, lat))
        elif interpolation in ('linear', 'cubic'):
            from scipy.interpolate import interp1d, interp2d
            nvalue = numpy.zeros(maxsize)
            interp_points = []
            for n in range(maxsize):
                if maxsize > 1:
                    lonn = lon[n]
                    latn = lat[n]
                    my_kn = my_k[n]
                    my_tn = my_t[n]
                else:
                    lonn = my_lon.item()
                    latn = my_lat.item()
                    my_kn = my_k.item()
                    my_tn = my_t.item()
                interp_points.append(self.geometry.nearest_points(lonn, latn, interpolation))
            # depack
            all_i = []
            all_j = []
            for points in interp_points:
                for p in points:
                    all_i.append(p[0])
                    all_j.append(p[1])
            # get values and lons/lats
            flat_values_at_interp_points = list(self.getvalue_ij(all_i, all_j, my_kn, my_tn))
            all_lonslats = self.geometry.ij2ll(all_i, all_j)
            all_lonslats = (list(all_lonslats[0]), list(all_lonslats[1]))
            # repack and interpolate
            for n in range(maxsize):
                loc_values = [flat_values_at_interp_points.pop(0) for _ in range(len(interp_points[n]))]
                loc_lons = [all_lonslats[0].pop(0) for _ in range(len(interp_points[n]))]
                loc_lats = [all_lonslats[1].pop(0) for _ in range(len(interp_points[n]))]
                if self.geometry.name == 'academic' and \
                   (self.geometry.dimensions['X'] == 1 or \
                    self.geometry.dimensions['Y'] == 1):
                    if self.geometry.dimensions['X'] == 1:
                        f = interp1d(loc_lats, loc_values, kind=interpolation)
                        value = f(latn)
                    else:
                        f = interp1d(loc_lons, loc_values, kind=interpolation)
                        value = f(lonn)
                else:
                    f = interp2d(loc_lons, loc_lats, loc_values, kind=interpolation)
                    value = f(lonn, latn)
                nvalue[n] = value
            value = nvalue
        if one:
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass

        return copy.copy(value)

    def as_lists(self, order='C', subzone=None):
        """
        Export values as a dict of lists (in fact numpy arrays).
        - *order*: whether to flatten arrays in 'C' (row-major) or
                   'F' (Fortran, column-major) order.
        - *subzone*: defines the LAM subzone to be included, in LAM case,
                     among: 'C', 'CI'.
        """

        if self.spectral:
            raise epygramError("as_lists method needs a grid-point field, not a spectral one.")

        lons4d, lats4d = self.geometry.get_lonlat_grid(d4=True, nb_validities=len(self.validity), subzone=subzone)
        levels4d = self.geometry.get_levels(d4=True, nb_validities=len(self.validity), subzone=subzone)
        data4d = self.getdata(d4=True, subzone=subzone)

        dates4d = []
        times4d = []
        for i, t in enumerate(self.validity):
            dates4d += [t.get().year * 10000 + t.get().month * 100 + t.get().day] * levels4d[i].size
            times4d += [t.get().hour * 100 + t.get().minute] * levels4d[i].size
        dates4d = numpy.array(dates4d).reshape(data4d.shape).flatten(order=order)
        times4d = numpy.array(times4d).reshape(data4d.shape).flatten(order=order)
        result = dict(values=data4d.flatten(order=order),
                    latitudes=lats4d.flatten(order=order),
                    longitudes=lons4d.flatten(order=order),
                    levels=levels4d.flatten(order=order),
                    dates=dates4d.flatten(order=order),
                    times=times4d.flatten(order=order))
        return result

    def as_dicts(self, subzone=None):
        """
        Export values as a list of dicts.
        - *subzone*: defines the LAM subzone to be included, in LAM case,
                     among: 'C', 'CI'.
        """

        if self.spectral:
            raise epygramError("as_dicts method needs a grid-point field, not a spectral one.")

        lons, lats = self.geometry.get_lonlat_grid(subzone=subzone)
        data4d = self.getdata(d4=True, subzone=subzone)
        levels4d = self.geometry.get_levels(d4=True, nb_validities=len(self.validity), subzone=subzone)

        result = []
        for t in range(data4d.shape[0]):
            validity = self.validity[t]
            date = validity.get().year * 10000 + validity.get().month * 100 + validity.get().day
            time = validity.get().hour * 100 + validity.get().minute
            for k in range(data4d.shape[1]):
                for j in range(data4d.shape[2]):
                    for i in range(data4d.shape[3]):
                        result.append(dict(value=data4d[t, k, j, i],
                                           date=date,
                                           time=time,
                                           latitude=lats[j, i],
                                           longitude=lons[j, i],
                                           level=levels4d[t, k, j, i]))
        return result

    def as_points(self, subzone=None):
        """
        Export values as a fieldset of points.
        - *subzone*: defines the LAM subzone to be included, in LAM case,
                     among: 'C', 'CI'.
        """

        if self.spectral:
            raise epygramError("as_points method needs a grid-point field, not a spectral one.")

        field_builder = fpx.field
        geom_builder = fpx.geometry
        vcoord_builer = fpx.geometry

        lons, lats = self.geometry.get_lonlat_grid(subzone=subzone)
        data4d = self.getdata(d4=True, subzone=subzone)
        levels4d = self.geometry.get_levels(d4=True, nb_validities=len(self.validity), subzone=subzone)

        result = FieldSet()
        kwargs_vcoord = copy.deepcopy(self.geometry.vcoordinate.footprint_as_dict())
        for t in range(data4d.shape[0]):
            validity = self.validity[t]
            for k in range(data4d.shape[1]):
                for j in range(data4d.shape[2]):
                    for i in range(data4d.shape[3]):
                        kwargs_vcoord['levels'] = [levels4d[t, k, j, i]]
                        vcoordinate = vcoord_builer(**copy.deepcopy(kwargs_vcoord))
                        geometry = geom_builder(structure='Point',
                                                dimensions={'X':1, 'Y':1},
                                                vcoordinate=vcoordinate,
                                                grid={'longitudes':[lons[j, i]],
                                                      'latitudes':[lats[j, i]],
                                                      'LAMzone':None},
                                                position_on_horizontal_grid='center'
                                                )
                        pointfield = field_builder(structure='Point',
                                                   fid=dict(copy.deepcopy(self.fid)),
                                                   geometry=geometry,
                                                   validity=validity.copy())
                        pointfield.setdata(data4d[t, k, j, i])
                        result.append(pointfield)
        return result

    def as_profiles(self, subzone=None):
        """
        Export values as a fieldset of profiles.
        - *subzone*: defines the LAM subzone to be included, in LAM case,
                     among: 'C', 'CI'.
        """

        if self.spectral:
            raise epygramError("as_profiles method needs a grid-point field, not a spectral one.")

        field_builder = fpx.field
        geom_builder = fpx.geometry
        vcoord_builer = fpx.geometry

        lons, lats = self.geometry.get_lonlat_grid(subzone=subzone)
        data4d = self.getdata(d4=True, subzone=subzone)
        levels4d = self.geometry.get_levels(d4=True, nb_validities=len(self.validity), subzone=subzone)

        result = FieldSet()
        kwargs_vcoord = copy.deepcopy(self.geometry.vcoordinate.footprint_as_dict())
        for t in range(data4d.shape[0]):
            validity = self.validity[t]
            for j in range(data4d.shape[2]):
                for i in range(data4d.shape[3]):
                    kwargs_vcoord['levels'] = [levels4d[t, :, j, i]]
                    vcoordinate = vcoord_builer(**copy.deepcopy(kwargs_vcoord))
                    geometry = geom_builder(structure='V1D',
                                            dimensions={'X':1, 'Y':1},
                                            vcoordinate=vcoordinate,
                                            grid={'longitudes':[lons[j, i]],
                                                  'latitudes':[lats[j, i]],
                                                  'LAMzone':None},
                                            position_on_horizontal_grid='center'
                                            )
                    profilefield = field_builder(structure='V1D',
                                                 fid=dict(copy.deepcopy(self.fid)),
                                                 geometry=geometry,
                                                 validity=validity.copy())
                    profilefield.setdata(data4d[t, :, j, i])
                    result.append(profilefield)
        return result

    def extract_subdomain(self, geometry, interpolation='nearest',
                          external_distance=None,
                          exclude_extralevels=True):
        """
        Extracts a subdomain from a field, given a new geometry.
    
        Args: \n
        - *geometry* defines the geometry on which extract data
        - *interpolation* defines the interpolation function used to compute
          the profile at requested lon/lat from the fields grid:
          - if 'nearest' (default), extracts profile at the horizontal nearest
            neighboring gridpoint;
          - if 'linear', computes profile with horizontal linear interpolation;
          - if 'cubic', computes profile with horizontal cubic interpolation.
        - *external_distance* can be a dict containing the target point value
          and an external field on the same grid as self, to which the distance
          is computed within the 4 horizontally nearest points; e.g. 
          {'target_value':4810, 'external_field':an_H2DField_with_same_geometry}.
          If so, the nearest point is selected with
          distance = |target_value - external_field.data|
        - *exclude_extralevels* if True levels with no physical meaning are
          suppressed.
        """

        # build subdomain fid
        subdomainfid = {key:(FPDict(value) if type(value) == type(dict()) else value) for (key, value) in self.fid.iteritems()}

        # build vertical geometry
        kwargs_vcoord = {'structure':'V',
                         'typeoffirstfixedsurface': self.geometry.vcoordinate.typeoffirstfixedsurface,
                         'position_on_grid': self.geometry.vcoordinate.position_on_grid,
                        }
        if self.geometry.vcoordinate.typeoffirstfixedsurface == 119:
            kwargs_vcoord['grid'] = copy.copy(self.geometry.vcoordinate.grid)
            kwargs_vcoord['levels'] = copy.copy(self.geometry.vcoordinate.levels)
        elif self.geometry.vcoordinate.typeoffirstfixedsurface == 118:
            kwargs_vcoord['grid'] = copy.copy(self.geometry.vcoordinate.grid)
            kwargs_vcoord['levels'] = copy.copy(self.geometry.vcoordinate.levels)
            #Suppression of levels above or under physical domain
            if exclude_extralevels:
                for level in kwargs_vcoord['levels']:
                    if level < 1 or level > len(self.geometry.vcoordinate.grid['gridlevels']) - 1:
                        kwargs_vcoord['levels'].remove(level)
        elif self.geometry.vcoordinate.typeoffirstfixedsurface in [100, 103, 109, 1, 106, 255]:
            kwargs_vcoord['levels'] = copy.copy(self.geometry.vcoordinate.levels)
        else:
            raise NotImplementedError("type of first surface level: " + str(self.geometry.vcoordinate.typeoffirstfixedsurface))
        if geometry.vcoordinate.typeoffirstfixedsurface not in [255, kwargs_vcoord['typeoffirstfixedsurface']]:
            raise epygramError("extract_subdomain cannot change vertical coordinate.")
        if geometry.vcoordinate.position_on_grid not in ['__unknown__', kwargs_vcoord['position_on_grid']]:
            raise epygramError("extract_subdomain cannot change position on vertical grid.")
        if geometry.vcoordinate.grid != {} and geometry.vcoordinate.grid != kwargs_vcoord['grid']:
            #One could check if requested grid is a subsample of field grid
            raise epygramError("extract_subdomain cannot change vertical grid")
        if geometry.vcoordinate.levels != []:
            for level in geometry.vcoordinate.levels:
                if level not in kwargs_vcoord['levels']:
                    raise epygramError("extract_subdomain cannot do vertical interpolations.")
            kwargs_vcoord['levels'] = geometry.vcoordinate.levels
        vcoordinate = fpx.geometry(**kwargs_vcoord)
        # build geometry
        kwargs_geom = {'structure': geometry.structure,
                       'name': geometry.name,
                       'grid': dict(geometry.grid),  #do not remove dict(), it is usefull for unstructured grid
                       'dimensions': copy.copy(geometry.dimensions),
                       'vcoordinate': vcoordinate,
                       'position_on_horizontal_grid': 'center'
                      }
        if geometry.projected_geometry:
            kwargs_geom['projection'] = copy.copy(geometry.projection)
            kwargs_geom['projtool'] = geometry.projtool
            kwargs_geom['geoid'] = geometry.geoid
        if geometry.position_on_horizontal_grid not in [None, '__unknown__', kwargs_geom['position_on_horizontal_grid']]:
            raise epygramError("extract_subdomain cannot deal with position_on_horizontal_grid other than 'center'")
        newgeometry = fpx.geometry(**kwargs_geom)

        # location & interpolation
        lons, lats = newgeometry.get_lonlat_grid()
        if len(lons.shape) > 1:
            lons = stretch_array(lons)
            lats = stretch_array(lats)
        for (lon, lat) in numpy.nditer([lons, lats]):
            if not self.geometry.point_is_inside_domain_ll(lon, lat):
                raise ValueError("point (" + str(lon) + ", " + \
                                 str(lat) + ") is out of field domain.")
        comment = None
        if interpolation == 'nearest':
            if lons.size == 1:
                true_loc = self.geometry.ij2ll(*self.geometry.nearest_points(lons, lats,
                                                                             'nearest',
                                                                             external_distance=external_distance))
                distance = self.geometry.distance((float(lons), float(lats)),
                                                   (float(true_loc[0]),
                                                    float(true_loc[1])))
                az = self.geometry.azimuth((float(lons), float(lats)),
                                           (float(true_loc[0]),
                                            float(true_loc[1])))
                if -22.5 < az <= 22.5:
                    direction = 'N'
                elif -77.5 < az <= -22.5:
                    direction = 'NW'
                elif -112.5 < az <= -77.5:
                    direction = 'W'
                elif -157.5 < az <= -112.5:
                    direction = 'SW'
                elif -180.5 <= az <= -157.5 or 157.5 < az <= 180.:
                    direction = 'S'
                elif 22.5 < az <= 77.5:
                    direction = 'NE'
                elif 77.5 < az <= 112.5:
                    direction = 'E'
                elif 112.5 < az <= 157.5:
                    direction = 'SE'
                gridpointstr = "(" + \
                               '{:.{precision}{type}}'.format(float(true_loc[0]),
                                                              type='F',
                                                              precision=4) + \
                               ", " + \
                               '{:.{precision}{type}}'.format(float(true_loc[1]),
                                                              type='F',
                                                              precision=4) + \
                               ")"
                comment = "Profile @ " + str(int(distance)) + "m " + \
                          direction + " from " + str((float(lons), float(lats))) + \
                          "\n" + "( = nearest gridpoint: " + gridpointstr + ")"
        elif interpolation in ('linear', 'cubic'):
            if interpolation == 'linear':
                interpstr = 'linearly'
            elif interpolation == 'cubic':
                interpstr = 'cubically'
            if lons.size == 1:
                comment = "Profile " + interpstr + " interpolated @ " + \
                          str((float(lons), float(lats)))
        else:
            raise NotImplementedError(interpolation + "interpolation.")


        # Values
        shape = [] if len(self.validity) == 1 else [len(self.validity)]
        shape += [len(newgeometry.vcoordinate.levels)] + list(lons.shape)
        data = numpy.ndarray(tuple(shape))
        for t in range(len(self.validity)):
            for k in range(len(newgeometry.vcoordinate.levels)):
                level = newgeometry.vcoordinate.levels[k]
                pos = (k) if len(self.validity) == 1 else (t, k)
                data[pos] = self.getvalue_ll(lons, lats, level, self.validity[t],
                                            interpolation=interpolation,
                                            external_distance=external_distance)

        # Field
        newfield = fpx.field(fid=FPDict(subdomainfid),
                             structure=newgeometry.structure,
                             geometry=newgeometry,
                             validity=self.validity,
                             processtype=self.processtype,
                             comment=comment)
        newfield.setdata(newgeometry.reshape_data(data, len(self.validity)))

        return newfield

###################
# PRE-APPLICATIVE #
###################
# (but useful and rather standard) !
# [so that, subject to continuation through updated versions,
#  including suggestions/developments by users...]

    def plotfield(self):
        raise NotImplementedError("plot of 3D field is not implemented")

    def stats(self, subzone=None):
        """
        Computes some basic statistics on the field, as a dict containing:
        {'min', 'max', 'mean', 'std', 'quadmean', 'nonzero'}.

        See each of these methods for details.

        - *subzone*: optional, among ('C', 'CI'), for LAM fields only, plots
          the data resp. on the C or C+I zone. \n
          Default is no subzone, i.e. the whole field.
        """

        return {'min':self.min(subzone=subzone),
                'max':self.max(subzone=subzone),
                'mean':self.mean(subzone=subzone),
                'std':self.std(subzone=subzone),
                'quadmean':self.quadmean(subzone=subzone),
                'nonzero':self.nonzero(subzone=subzone)}

    def min(self, subzone=None):
        """Returns the minimum value of data."""
        data = self.getdata(subzone=subzone)
        return numpy.ma.masked_outside(data,
                                       - config.mask_outside,
                                       config.mask_outside).min()

    def max(self, subzone=None):
        """Returns the maximum value of data."""
        data = self.getdata(subzone=subzone)
        return numpy.ma.masked_outside(data,
                                       - config.mask_outside,
                                       config.mask_outside).max()

    def mean(self, subzone=None):
        """Returns the mean value of data."""
        data = self.getdata(subzone=subzone)
        return numpy.ma.masked_outside(data,
                                       - config.mask_outside,
                                       config.mask_outside).mean()

    def std(self, subzone=None):
        """Returns the standard deviation of data."""
        data = self.getdata(subzone=subzone)
        return numpy.ma.masked_outside(data,
                                       - config.mask_outside,
                                       config.mask_outside).std()

    def quadmean(self, subzone=None):
        """Returns the quadratic mean of data."""
        data = self.getdata(subzone=subzone)
        return numpy.sqrt(numpy.ma.masked_greater(data**2,
                                                  config.mask_outside**2).mean())

    def nonzero(self, subzone=None):
        """
        Returns the number of non-zero values (whose absolute
        value > config.epsilon).
        """
        data = self.getdata(subzone=subzone)
        return numpy.count_nonzero(abs(numpy.ma.masked_outside(data,
                                                               - config.mask_outside,
                                                               config.mask_outside)) > config.epsilon)

    def dctspectrum(self, k=None, subzone=None):
        """
        Returns the DCT spectrum of the field, as a
        :class:`epygram.spectra.Spectrum` instance.
        *k* is the level index to use to compute de DCT
        """
        import epygram.spectra as esp

        if k == None and self.geometry.datashape['k']:
            raise epygramError("One must choose the level for a 3D field.")
        if (not self.geometry.datashape['k']) and k not in [None, 0]:
            raise epygramError("k must be None or 0 for a 2D field.")
        if k == None:
            my_k = 0
        else:
            my_k = k

        if len(self.validity) > 1:
            #One must add a validity argument to enable feature
            raise NotImplementedError("dctspectrum not yet implemented for multi validities fields.")

        field2d = self.getlevel(k=my_k)
        variances = esp.dctspectrum(field2d.getdata(subzone=subzone, d4=True)[0, 0])
        spectrum = esp.Spectrum(variances[1:],
                                name=str(self.fid),
                                resolution=self.geometry.grid['X_resolution'] / 1000.,
                                mean2=variances[0])

        return spectrum

    def global_shift_center(self, longitude_shift):
        """
        For global RegLLGeometry grids only !
        Shifts the center of the geometry (and the data accordingly) by
        *longitude_shift* (in degrees). *longitude_shift* has to be a multiple
        of the grid's resolution in longitude.
        """

        if self.geometry.name != 'regular_lonlat':
            raise epygramError("only for regular lonlat geometries.")
        self.geometry.global_shift_center(longitude_shift)
        n = longitude_shift / self.geometry.grid['X_resolution'].get('degrees')
        data4d = self.getdata(d4=True)
        data4d[:, :, :, :] = numpy.concatenate((data4d[:, :, :, n:], data4d[:, :, :, 0:n]),
                                               axis=3)
        #for t in range(len(self.validity)):
        #    for k in range(len(self.data)):
        #        data4d[t, k, :, :] = numpy.concatenate((data4d[t, k, :, n:], data4d[t, k, :, 0:n]),
        #                                         axis=1)
        self.setdata(self.geometry.reshape_data(data4d, len(self.validity)))

    def what(self, out=sys.stdout,
             validity=True,
             vertical_geometry=True,
             cumulativeduration=True,
             arpifs_var_names=False,
             fid=True):
        """
        Writes in file a summary of the field.

        Args: \n
        - *out*: the output open file-like object (duck-typing: *out*.write()
          only is needed).
        - *vertical_geometry*: if True, writes the validity of the
          field.
        - *vertical_geometry*: if True, writes the vertical geometry of the
          field.
        - *cumulativeduration*: if False, not written.
        - *arpifs_var_names*: if True, prints the equivalent 'arpifs' variable
          names.
        - *fid*: if True, prints the fid.
        """

        if self.spectral:
            spectral_geometry = self.spectral_geometry.truncation
        else:
            spectral_geometry = None
        write_formatted(out, "Kind of producting process", self.processtype)
        if validity:
            self.validity.what(out, cumulativeduration=cumulativeduration)
        self.geometry.what(out,
                           vertical_geometry=vertical_geometry,
                           arpifs_var_names=arpifs_var_names,
                           spectral_geometry=spectral_geometry)
        if fid:
            for key in self.fid:
                write_formatted(out, "fid " + key, self.fid[key])



#############
# OPERATORS #
#############

    def _check_operands(self, other):
        """
        Internal method to check compatibility of terms in operations on fields.
        """

        if isinstance(other, self.__class__):
            if self.spectral != other.spectral:
                raise epygramError("cannot operate a spectral field with a" + \
                                   " non-spectral field.")
            if self.geometry.dimensions != other.geometry.dimensions:
                raise epygramError("operations on fields cannot be done if" + \
                                   " fields do not share their gridpoint" + \
                                   " dimensions.")
            if self.spectral_geometry != other.spectral_geometry:
                raise epygramError("operations on fields cannot be done if" + \
                                   " fields do not share their spectral" + \
                                   " geometry.")
        else:
            super(D3CommonField, self)._check_operands(other)

    def __add__(self, other):
        """
        Definition of addition, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'+'} and null validity.
        """

        newfield = self._add(other,
                             structure=self.structure,
                             geometry=self.geometry,
                             spectral_geometry=self.spectral_geometry)
        return newfield

    def __mul__(self, other):
        """
        Definition of multiplication, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'*'} and null validity.
        """

        newfield = self._mul(other,
                             structure=self.structure,
                             geometry=self.geometry,
                             spectral_geometry=self.spectral_geometry)
        return newfield

    def __sub__(self, other):
        """
        Definition of substraction, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'-'} and null validity.
        """

        newfield = self._sub(other,
                             structure=self.structure,
                             geometry=self.geometry,
                             spectral_geometry=self.spectral_geometry)
        return newfield

    def __div__(self, other):
        """
        Definition of division, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'/'} and null validity.
        """

        newfield = self._div(other,
                             structure=self.structure,
                             geometry=self.geometry,
                             spectral_geometry=self.spectral_geometry)
        return newfield

class D3Field(D3CommonField):
    """
    3-Dimensions field class.
    A field is defined by its identifier 'fid',
    its data, its geometry (gridpoint and optionally spectral),
    and its validity.

    The natural being of a field is gridpoint, so that:
    a field always has a gridpoint geometry, but it has a spectral geometry only
    in case it is spectral. 
    """

    _collector = ('field',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['3D'])),
            geometry=dict(
                type=D3Geometry,
                info="Geometry defining the position of the field gridpoints."),
            validity=dict(
                type=FieldValidityList,
                info="Validity of the field.",
                optional=True,
                access='rwx',
                default=FieldValidityList()),
            spectral_geometry=dict(
                info="For a spectral field, its spectral geometry handles \
                      spectral transforms and dimensions.",
                type=SpectralGeometry,
                optional=True),
            processtype=dict(
                optional=True,
                info="Generating process.")
        )
    )


##############
# ABOUT DATA #
##############

    def sp2gp(self):
        """
        Transforms the spectral field into gridpoint, according to its spectral
        geometry. Replaces data in place.

        The spectral transform subroutine is actually included in the spectral
        geometry's *sp2gp()* method.
        """

        if self.spectral:
            if len(self.validity) == 1:
                expected = 2 if self.geometry.datashape['k'] else 1
            else:
                expected = 3  #vertical dimension mandatory for multivalidities fields
            if len(self.data.shape) != expected:
                raise epygramError("spectral data must be 2D for a 3D field and 1D for a 2D field")
            if self.geometry.rectangular_grid:
                # LAM
                gpdims = {}
                for dim in ['X', 'Y', 'X_CIzone', 'Y_CIzone']:
                    gpdims[dim] = self.geometry.dimensions[dim]
                for item in ['X_resolution', 'Y_resolution']:
                    gpdims[item] = self.geometry.grid[item]
            else:
                # global
                gpdims = {}
                for dim in ['lat_number', 'lon_number_by_lat']:
                    gpdims[dim] = self.geometry.dimensions[dim]
            if len(self.validity) == 1:
                if self.geometry.datashape['k']:
                    #one validity, several levels
                    dataList = []
                    for k in range(len(self.data)):
                        data2d = self.geometry.reshape_data(self.spectral_geometry.sp2gp(self.data[k], gpdims), 1)
                        dataList.append(data2d)
                    result = numpy.array(dataList)
                else:
                    #one validity, one level
                    result = self.geometry.reshape_data(self.spectral_geometry.sp2gp(self.data, gpdims), 1)
            else:
                #several validities (implies to have an array dimension for the vertical dimension)
                result = []
                for t in range(len(self.data)):
                    dataList = []
                    for k in range(len(self.data[t])):
                        data2d = self.geometry.reshape_data(self.spectral_geometry.sp2gp(self.data[t][k], gpdims), 1)
                        dataList.append(data2d)
                    result.append(numpy.array(dataList))
                result = numpy.array(result)

            self._attributes['spectral_geometry'] = None
            self.setdata(result)

    def gp2sp(self, spectral_geometry):
        """
        Transforms the gridpoint field into spectral space, according to the
        *spectral geometry* mandatorily passed as argument. Replaces data in
        place.

        The spectral transform subroutine is actually included in the spectral
        geometry's *gp2sp()* method.
        """

        if not self.spectral:
            if len(self.validity) == 1:
                expected = 3 if self.geometry.datashape['k'] else 2
            else:
                expected = 4  #vertical dimension mandatory for multivalidities fields
            if len(self.data.shape) != expected:
                raise epygramError("spectral data must be 3D for a 3D field and 2D for a 2D field")
            if not isinstance(spectral_geometry, SpectralGeometry):
                raise epygramError("a spectral geometry (SpectralGeometry" + \
                                   " instance) must be passed as argument" + \
                                   " to gp2sp()")

            if self.geometry.rectangular_grid:
                # LAM
                if self.geometry.grid['LAMzone'] != 'CIE':
                    raise epygramError("this field is not bi-periodicized:" + \
                                       " it cannot be transformed into" + \
                                       " spectral space.")
                gpdims = {}
                for dim in ['X', 'Y', 'X_CIzone', 'Y_CIzone']:
                    gpdims[dim] = self.geometry.dimensions[dim]
                for item in ['X_resolution', 'Y_resolution']:
                    gpdims[item] = self.geometry.grid[item]
            else:
                # global
                gpdims = {}
                for dim in ['lat_number', 'lon_number_by_lat']:
                    gpdims[dim] = self.geometry.dimensions[dim]

            if len(self.validity) == 1:
                if self.geometry.datashape['k']:
                    #one validity, several levels
                    dataList = []
                    for k in range(len(self.data)):
                        if self.geometry.rectangular_grid:
                            data1d = self.data[k].flatten()
                        else:
                            data1d = self.data[k].compressed()
                        dataList.append(spectral_geometry.gp2sp(data1d, gpdims))
                    result = numpy.array(dataList)
                else:
                    #one validity, one level
                    if self.geometry.rectangular_grid:
                        data1d = self.data.flatten()
                    else:
                        data1d = self.data.compressed()
                    result = spectral_geometry.gp2sp(data1d, gpdims)
            else:
                #several validities (implies to have an array dimension for the vertical dimension)
                result = []
                for t in range(len(self.data)):
                    dataList = []
                    for k in range(len(self.data[t])):
                        if self.geometry.rectangular_grid:
                            data1d = self.data[t][k].flatten()
                        else:
                            data1d = self.data[t][k].compressed()
                        dataList.append(spectral_geometry.gp2sp(data1d, gpdims))
                    result.append(numpy.array(dataList))
                result = numpy.array(result)

            self._attributes['spectral_geometry'] = spectral_geometry
            self.setdata(result)

    def compute_xy_spderivatives(self):
        """
        Compute the derivatives of field in spectral space, then come back in 
        gridpoint space
        Returns the two derivative fields.

        The spectral transform and derivatives subroutines are actually included
        in the spectral geometry's *compute_xy_spderivatives()* method.
        """

        if self.spectral:
            if len(self.validity) == 1:
                expected = 2 if self.geometry.datashape['k'] else 1
            else:
                expected = 3  #vertical dimension mandatory for multivalidities fields
            if len(self.data.shape) != expected:
                raise epygramError("spectral data must be 2D for a 3D field and 1D for a 2D field")
            if self.geometry.rectangular_grid:
                # LAM
                gpdims = {}
                for dim in ['X', 'Y', 'X_CIzone', 'Y_CIzone']:
                    gpdims[dim] = self.geometry.dimensions[dim]
                for item in ['X_resolution', 'Y_resolution']:
                    gpdims[item] = self.geometry.grid[item]
            else:
                # global
                gpdims = {}
                for dim in ['lat_number', 'lon_number_by_lat']:
                    gpdims[dim] = self.geometry.dimensions[dim]
            if len(self.validity) == 1:
                if self.geometry.datashape['k']:
                    #one validity, several levels
                    dataListX = []
                    dataListY = []
                    for k in range(len(self.data)):
                        (dx, dy) = self.spectral_geometry.compute_xy_spderivatives(self.data[k], gpdims)
                        dataListX.append(self.geometry.reshape_data(dx, 1))
                        dataListX.append(self.geometry.reshape_data(dy, 1))
                    resultX = copy.deepcopy(self)
                    resultX._attributes['spectral_geometry'] = None
                    resultX.fid = {'derivative':'x'}
                    resultX.setdata(numpy.array(dataListX))  #TOBECHECKED:
                    resultY = copy.deepcopy(self)
                    resultY._attributes['spectral_geometry'] = None
                    resultY.fid = {'derivative':'y'}
                    resultY.setdata(numpy.array(dataListY))  #TOBECHECKED:
                else:
                    #one validity, one level
                    (dx, dy) = self.spectral_geometry.compute_xy_spderivatives(self.data, gpdims)
                    resultX = copy.deepcopy(self)
                    resultX._attributes['spectral_geometry'] = None
                    resultX.fid = {'derivative':'x'}
                    resultX.setdata(numpy.array(self.geometry.reshape_data(dx, 1)))
                    resultY = copy.deepcopy(self)
                    resultY._attributes['spectral_geometry'] = None
                    resultY.fid = {'derivative':'y'}
                    resultY.setdata(numpy.array(self.geometry.reshape_data(dy, 1)))
            else:
                #several validities (implies to have an array dimension for the vertical dimension)
                D4arrayX = []
                D4arrayY = []
                for t in range(len(self.data)):
                    dataListX = []
                    dataListY = []
                    for k in range(len(self.data[t])):
                        (dx, dy) = self.spectral_geometry.compute_xy_spderivatives(self.data[t][k], gpdims)
                        dataListX.append(self.geometry.reshape_data(dx, 1))
                        dataListY.append(self.geometry.reshape_data(dy, 1))
                    D4arrayX.append(numpy.array(dataListX))
                    D4arrayY.append(numpy.array(dataListY))
                resultX = copy.deepcopy(self)
                resultX._attributes['spectral_geometry'] = None
                resultX.fid = {'derivative':'x'}
                resultX.setdata(numpy.array(D4arrayX))  #TOBECHECKED:
                resultY = copy.deepcopy(self)
                resultY._attributes['spectral_geometry'] = None
                resultY.fid = {'derivative':'y'}
                resultY.setdata(numpy.array(D4arrayY))  #TOBECHECKED:
        else:
            raise epygramError('field must be spectral to compute its spectral derivatives.')

        return (resultX, resultY)

    def getdata(self, subzone=None, d4=False):
        """
        Returns the field data, with 3D shape if the field is not spectral,
        2D if spectral.

        - *subzone*: optional, among ('C', 'CI'), for LAM fields only, returns
          the data resp. on the C or C+I zone.
          Default is no subzone, i.e. the whole field.
        - *d4*: if True,  returned values are shaped in a 4 dimensions array
                if False, shape of returned values is determined with respect to geometry

        Shape of 3D data: \n
        - Rectangular grids:\n
          grid[k,0,0] is SW, grid[k,-1,-1] is NE \n
          grid[k,0,-1] is SE, grid[k,-1,0] is NW \n
          with k the level
        - Gauss grids:\n
          grid[k,0,:Nj] is first (Northern) band of latitude, masked after
          Nj = number of longitudes for latitude j \n
          grid[k,-1,:Nj] is last (Southern) band of latitude (idem). \n
          with k the level
        """

        if not self.spectral and subzone and \
           self.geometry.grid.get('LAMzone') is not None:
            data = self.geometry.extract_subzone(self.data, len(self.validity), subzone)
            if d4:
                data = self.geometry.reshape_data(data, len(self.validity), d4=True, subzone=subzone)
        else:
            if subzone:
                raise epygramError("subzone cannot be provided for this field.")
            if d4:
                data = self.geometry.reshape_data(self.data, len(self.validity), d4=True)
            else:
                data = self.data

        return data

    def setdata(self, data):
        """
        Sets field data, checking *data* to have the good shape according to geometry.
        """

        dimensions = 0
        if len(self.validity) > 1:
            dimensions += 1
        if self.geometry.datashape['k'] or len(self.validity) > 1:
            dimensions += 1
        if self.spectral:
            dimensions += 1
            dataType = "spectral"
        else:
            if self.geometry.datashape['j']:
                dimensions += 1
            if self.geometry.datashape['i']:
                dimensions += 1
            dataType = "gridpoint"
        if len(numpy.shape(data)) != dimensions:
            raise epygramError(dataType + " data must be " + str(dimensions) + "D array.")
        super(D3Field, self).setdata(data)

    def select_subzone(self, subzone):
        """
        If a LAMzone defines the field, select only the *subzone* from it.
        *subzone* among ('C', 'CI').
        Warning: modifies the field and its geometry in place !
        """

        if self.geometry.grid.get('LAMzone') is not None:
            data = self.getdata(subzone=subzone)
            self._attributes['geometry'] = self.geometry.select_subzone(subzone)
            self.setdata(data)

    def getvalue_ij(self, i=None, j=None, k=None, t=None,
                    one=True):
        """
        Returns the value of the field on point of indices (*i, j, k, t*).
        Take care (*i, j, k, t*) is python-indexing, ranging from 0 to dimension - 1.
        *k* is the index of the level (not a value in Pa or m...)
        *t* is the index of the temporal dimension (not a validity object)
        *k* and *t* can be scalar even if *i* and *j* are arrays.
        
        If *one* is False, returns [value] instead of value.
        """

        if len(self.validity) > 1 and t is None:
            raise epygramError("*t* is mandatory when there are several validities")
        if self.geometry.datashape['k'] and k is None:
            raise epygramError("*k* is mandatory when field has a vertical coordinate")
        if self.geometry.datashape['j'] and j is None:
            raise epygramError("*j* is mandatory when field has a two horizontal dimensions")
        if self.geometry.datashape['i'] and j is None:
            raise epygramError("*i* is mandatory when field has one horizontal dimension")

        if not self.geometry.point_is_inside_domain_ij(i, j):
            raise ValueError("point is out of field domain.")

        maxsize = numpy.array([numpy.array(dim).size for dim in [i, j, k, t] if dim is not None]).max()
        if t is None:
            my_t = numpy.zeros(maxsize, dtype=int)
        else:
            my_t = numpy.array(t)
            if my_t.size != maxsize:
                if my_t.size != 1:
                    raise epygramError("t must be scalar or must have the same length as other indexes")
                my_t = numpy.array([my_t.item()] * maxsize)
        if k is None:
            my_k = numpy.zeros(maxsize, dtype=int)
        else:
            my_k = numpy.array(k)
            if my_k.size != maxsize:
                if my_k.size != 1:
                    raise epygramError("k must be scalar or must have the same length as other indexes")
                my_k = numpy.array([my_k.item()] * maxsize)
        if j is None:
            my_j = numpy.zeros(maxsize, dtype=int)
        else:
            my_j = numpy.array(j)
            if my_j.size != maxsize:
                raise epygramError("j must have the same length as other indexes")
        if i is None:
            my_i = numpy.zeros(maxsize, dtype=int)
        else:
            my_i = numpy.array(i)
            if my_i.size != maxsize:
                raise epygramError("i must have the same length as other indexes")

        value = numpy.copy(self.getdata(d4=True)[my_t, my_k, my_j, my_i])
        if value.size == 1 and one:
            value = value.item()
        return value


    def getlevel(self, level=None, k=None):
        """
        Returns a level of the field as a new field.
        *level* is the requested level expressed in coordinate value (Pa, m...)
        *k* is the index of the requested level
        """

        if k == None and level == None:
            raise epygramError("You must give k or level.")
        if k != None and level != None:
            raise epygramError("You cannot give, at the same time, k and level")
        if level != None:
            if level not in self.geometry.vcoordinate.levels:
                raise epygramError("The requested level does not exist.")
            my_k = self.geometry.vcoordinate.levels.index(level)
        else:
            my_k = k

        if self.structure == '3D':
            newstructure = 'H2D'
        elif self.structure == 'V2D':
            newstructure = 'H2D'
        elif self.structure == 'V1D':
            newstructure = 'Point'
        else:
            raise epygramError("It's not possible to extract a level from a " + self.structure + " field.")

        kwargs_vcoord = {'structure': 'V',
                         'typeoffirstfixedsurface': self.geometry.vcoordinate.typeoffirstfixedsurface,
                         'position_on_grid': self.geometry.vcoordinate.position_on_grid,
                         'levels':[level]
                        }
        if self.geometry.vcoordinate.typeoffirstfixedsurface in (118, 119):
            kwargs_vcoord['grid'] = copy.copy(self.geometry.vcoordinate.grid)
        newvcoordinate = fpx.geometry(**kwargs_vcoord)
        kwargs_geom = {'structure':newstructure,
                       'name': self.geometry.name,
                       'grid': dict(self.geometry.grid),
                       'dimensions': copy.copy(self.geometry.dimensions),
                       'vcoordinate': newvcoordinate,
                       'position_on_horizontal_grid': self.geometry.position_on_horizontal_grid
                      }
        if self.geometry.projected_geometry:
            kwargs_geom['projection'] = copy.copy(self.geometry.projection)
            kwargs_geom['projtool'] = self.geometry.projtool
            kwargs_geom['geoid'] = self.geometry.geoid
        newgeometry = fpx.geometry(**kwargs_geom)
        generic_fid = self.fid['generic']
        generic_fid['level'] = level
        kwargs_field = {'structure':newstructure,
                        'validity':self.validity.copy(),
                        'processtype':self.processtype,
                        'geometry':newgeometry,
                        'fid':{'generic':generic_fid}}
        if self.spectral_geometry is not None:
            kwargs_field['spectral_geometry'] = self.spectral_geometry.copy()
        newfield = fpx.field(**kwargs_field)
        newfield.setdata(self.data[my_k, :, :])

        return newfield

class D3VirtualField(D3CommonField):
    """
    3-Dimensions Virtual field class.
    
    Data is taken from other fields, either:
    - a given *fieldset*
    - a *resource* in which are stored fields defined by *resource_fids*.
    """

    _collector = ('field',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                values=set(['3D'])),
            fieldset=dict(
                info="Set of real fields that can compose the Virtual Field.",
                type=FieldSet,
                optional=True,
                default=FieldSet()),
            resource=dict(
                info="Resource in which is stored the fields defined by \
                      resource_fids.",
                type=Resource,
                optional=True),
            resource_fids=dict(
                info="Definition of the fields in resource that compose the \
                      virtual field.",
                type=FPList,
                optional=True,
                default=FPList()),
        )
    )

    def __init__(self, *args, **kwargs):
        """
        Constructor. See its footprint for arguments.
        """

        super(D3VirtualField, self).__init__(*args, **kwargs)

        if self.fieldset != FieldSet():
            if self.resource is not None or self.resource_fids != FPList():
                raise epygramError("You cannot set fieldset and (resource or resource_fids) at the same time.")
            raise NotImplementedError("D3VirtualField from a fieldset is not yet implemented")
        else:
            if self.resource is None or self.resource_fids == FPList():
                raise epygramError("If you do not set fieldset, you need to provide resource and resource_fids.")
            fidlist = self.resource.find_fields_in_resource(seed=self.resource_fids,
                                                            fieldtype=['H2D', '3D'])
            if len(fidlist) == 0:
                raise epygramError("There is no field in resource matching with resource_fids")
            first = True
            self._fidList = []
            levelList = []
            for fid in fidlist:
                field = self.resource.readfield(fid, getdata=False)
                if field.structure != 'H2D':
                    raise epygramError("3D virtual fields must be build from H2D fields only")
                if first:
                    self._geometry = field.geometry.copy()
                    self._validity = field.validity.copy()
                    if field.spectral_geometry is not None:
                        self._spectral_geometry = field.spectral_geometry.copy()
                    else:
                        self._spectral_geometry = None
                    self._processtype = field.processtype
                else:
                    if self._geometry.structure != field.geometry.structure or \
                       self._geometry.name != field.geometry.name or \
                       self._geometry.grid != field.geometry.grid or \
                       self._geometry.dimensions != field.geometry.dimensions or \
                       self._geometry.position_on_horizontal_grid != field.geometry.position_on_horizontal_grid:
                        raise epygramError("All H2D fields must share the horizontal geometry")
                    if self._geometry.projected_geometry or field.geometry.projected_geometry:
                        if self._geometry.projection != field.geometry.projection or \
                           self._geometry.geoid != field.geometry.geoid:
                            raise epygramError("All H2D fields must share the geometry projection")
                    if self._geometry.vcoordinate.typeoffirstfixedsurface != field.geometry.vcoordinate.typeoffirstfixedsurface or \
                       self._geometry.vcoordinate.position_on_grid != field.geometry.vcoordinate.position_on_grid:
                        raise epygramError("All H2D fields must share the vertical geometry")
                    if self._geometry.vcoordinate.grid is not None or field.geometry.vcoordinate.grid is not None:
                        if self._geometry.vcoordinate.grid != field.geometry.vcoordinate.grid:
                            raise epygramError("All H2D fields must share the vertical grid")
                    if self._validity != field.validity:
                        raise epygramError("All H2D fields must share the validity")
                    if self._spectral_geometry != field.spectral_geometry:
                        raise epygramError("All H2D fields must share the spectral geometry")
                    if self._processtype != field.processtype:
                        raise epygramError("All H2D fields must share the sprocesstype")
                if len(field.geometry.vcoordinate.levels) != 1:
                    raise epygramError("H2D fields must have only one level")
                if field.geometry.vcoordinate.levels[0] in levelList:
                    raise epygramError("This level have already been found")
                levelList.append(field.geometry.vcoordinate.levels[0])
                self._fidList.append(fid)
            kwargs_vcoord = dict(structure='V',
                                 typeoffirstfixedsurface=self._geometry.vcoordinate.typeoffirstfixedsurface,
                                 position_on_grid=self._geometry.vcoordinate.position_on_grid)
            if self._geometry.vcoordinate.grid is not None:
                kwargs_vcoord['grid'] = self._geometry.vcoordinate.grid
            kwargs_vcoord['levels'], self._fidList = (list(t) for t in zip(*sorted(zip(levelList, self._fidList))))  #TOBECHECKED
            self._geometry.vcoordinate = fpx.geometry(**kwargs_vcoord)
            self._spgpOpList = []

    @property
    def geometry(self):
        return self._geometry

    @property
    def validity(self):
        return self._validity

    @property
    def spectral_geometry(self):
        return self._spectral_geometry

    @property
    def processtype(self):
        return self._processtype



##############
# ABOUT DATA #
##############

    def sp2gp(self):
        """
        Transforms the spectral field into gridpoint, according to its spectral
        geometry. Replaces data in place.

        The spectral transform subroutine is actually included in the spectral
        geometry's *sp2gp()* method.
        """
        self._spgpOpList.append(('sp2gp', {}))
        self._spectral_geometry = None

    def gp2sp(self, spectral_geometry):
        """
        Transforms the gridpoint field into spectral space, according to the
        *spectral geometry* mandatorily passed as argument. Replaces data in
        place.

        The spectral transform subroutine is actually included in the spectral
        geometry's *gp2sp()* method.
        """
        self._spgpOpList.append(('gp2sp', {'spectral_geometry':spectral_geometry}))

    def getdata(self, subzone=None, d4=False):
        """
        Returns the field data, with 3D shape if the field is not spectral,
        2D if spectral.

        - *subzone*: optional, among ('C', 'CI'), for LAM fields only, returns
          the data resp. on the C or C+I zone.
          Default is no subzone, i.e. the whole field.
        - *d4*: if True,  returned values are shaped in a 4 dimensions array
                if False, shape of returned values is determined with respect to geometry

        Shape of 3D data: \n
        - Rectangular grids:\n
          grid[k,0,0] is SW, grid[k,-1,-1] is NE \n
          grid[k,0,-1] is SE, grid[k,-1,0] is NW \n
          with k the level
        - Gauss grids:\n
          grid[k,0,:Nj] is first (Northern) band of latitude, masked after
          Nj = number of longitudes for latitude j \n
          grid[k,-1,:Nj] is last (Southern) band of latitude (idem). \n
          with k the level
        """

        dataList = []
        for k in range(len(self.geometry.vcoordinate.levels)):
            dataList.append(self.getlevel(k).getdata(subzone=subzone, d4=d4))

        return numpy.array(dataList)

    def setdata(self, data):
        """
        Sets field data, checking *data* to have the good shape according to geometry.
        """
        raise epygramError("setdata cannot be implemented on virtual fields")

    def getvalue_ij(self, i=None, j=None, k=None, t=None,
                    one=True):
        """
        Returns the value of the field on point of indices (*i, j, k, t*).
        Take care (*i, j, k, t*) is python-indexing, ranging from 0 to dimension - 1.
        *k* is the index of the level (not a value in Pa or m...)
        *t* is the index of the temporal dimension (not a validity object)
        *k* and *t* can be scalar even if *i* and *j* are arrays.
        
        If *one* is False, returns [value] instead of value.
        """

        if len(self.validity) > 1 and t is None:
            raise epygramError("*t* is mandatory when there are several validities")
        if self.geometry.datashape['k'] and k is None:
            raise epygramError("*k* is mandatory when field has a vertical coordinate")
        if self.geometry.datashape['j'] and j is None:
            raise epygramError("*j* is mandatory when field has a two horizontal dimensions")
        if self.geometry.datashape['i'] and j is None:
            raise epygramError("*i* is mandatory when field has one horizontal dimension")

        if not self.geometry.point_is_inside_domain_ij(i, j):
            raise ValueError("point is out of field domain.")

        maxsize = numpy.array([numpy.array(dim).size for dim in [i, j, k, t] if dim is not None]).max()
        if t is None:
            my_t = numpy.zeros(maxsize, dtype=int)
        else:
            my_t = numpy.array(t)
            if my_t.size != maxsize:
                if my_t.size != 1:
                    raise epygramError("t must be scalar or must have the same length as other indexes")
                my_t = numpy.array([my_t.item()] * maxsize)
        if k is None:
            my_k = numpy.zeros(maxsize, dtype=int)
        else:
            my_k = numpy.array(k)
            if my_k.size != maxsize:
                if my_k.size != 1:
                    raise epygramError("k must be scalar or must have the same length as other indexes")
                my_k = numpy.array([my_k.item()] * maxsize)
        if j is None:
            my_j = numpy.zeros(maxsize, dtype=int)
        else:
            my_j = numpy.array(j)
            if my_j.size != maxsize:
                raise epygramError("j must have the same length as other indexes")
        if i is None:
            my_i = numpy.zeros(maxsize, dtype=int)
        else:
            my_i = numpy.array(i)
            if my_i.size != maxsize:
                raise epygramError("i must have the same length as other indexes")

        value = []
        oldk = None
        for x in range(my_k.size):
            thisk = my_k[x] if my_k.size > 1 else my_k.item()
            if thisk != oldk:
                field2d = self.getlevel(k=thisk)
                oldk = thisk
            if my_t.size == 1:
                pos = (my_t.item(), 0, my_j.item(), my_i.item())
            else:
                pos = (my_t[x], 0, my_j[x], my_i[x])
            value.append(field2d.getdata(d4=True)[pos])
        value = numpy.array(value)
        if value.size == 1 and one:
            value = value.item()
        return value

    def getlevel(self, level=None, k=None):
        """
        Returns a level of the field as a new field.
        *level* is the requested level expressed in coordinate value (Pa, m...)
        *k* is the index of the requested level
        """

        if k == None and level == None:
            raise epygramError("You must give k or level.")
        if k != None and level != None:
            raise epygramError("You cannot give, at the same time, k and level")
        if level != None:
            if level not in self.geometry.vcoordinate.levels:
                raise epygramError("The requested level does not exist.")
            my_k = self.geometry.vcoordinate.levels.index(level)
        else:
            my_k = k

        result = self.resource.readfield(self._fidList[my_k])

        for op, kwargs in self._spgpOpList:
            if op == 'sp2gp':
                result.sp2gp(**kwargs)
            elif op == 'gp2sp':
                result.gp2sp(**kwargs)
            else:
                raise epygramError("operation not known")

        return result



footprints.collectors.get(tag='fields').fasttrack = ('structure',)
