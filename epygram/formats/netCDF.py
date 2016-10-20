#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Météo France (2014-)
# This software is governed by the CeCILL-C license under French law.
# http://www.cecill.info
"""
Contains classes for netCDF4 resource.
"""

__all__ = ['netCDF']

import copy
import json
import sys
import numpy
from collections import OrderedDict
import datetime
from dateutil import parser as dt_parser

import netCDF4

import footprints
from footprints import proxy as fpx, FPDict, FPList

from epygram import config, epygramError, util
from epygram.base import FieldValidity, FieldValidityList
from epygram.resources import FileResource
from epygram.util import stretch_array, Angle, nearlyEqual

epylog = footprints.loggers.getLogger(__name__)


_typeoffirstfixedsurface_dict = {'altitude':102,
                                 'height':103,
                                 'hybrid-pressure':119,
                                 'hybrid-height':118,
                                 'pressure':100}
_typeoffirstfixedsurface_dict_inv = {v:k for k, v in _typeoffirstfixedsurface_dict.items()}

_proj_dict = {'lambert':'lambert_conformal_conic',
              'mercator':'mercator',
              'polar_stereographic':'polar_stereographic'}
_proj_dict_inv = {v:k for k, v in _proj_dict.items()}



class netCDF(FileResource):
    """Class implementing all specificities for netCDF (4) resource format."""

    _footprint = dict(
        attr=dict(
            format=dict(
                values=set(['netCDF']),
                default='netCDF'),
            behaviour=dict(
                info="Describes how fields are defined in resource.",
                type=FPDict,
                optional=True,
                default=config.netCDF_default_behaviour)
        )
    )

    def __init__(self, *args, **kwargs):
        """Constructor. See its footprint for arguments."""

        self.isopen = False
        super(netCDF, self).__init__(*args, **kwargs)

        if self.openmode in ('r', 'a'):
            try:
                guess = netCDF4.Dataset(self.container.abspath, self.openmode)
            except RuntimeError:
                raise IOError("this resource is not a netCDF one.")
            else:
                guess.close()
        behaviour = copy.copy(config.netCDF_default_behaviour)
        behaviour.update(self.behaviour)
        self._attributes['behaviour'] = behaviour
        if not self.fmtdelayedopen:
            self.open()

    def open(self, openmode=None):
        """
        Opens a netCDF and initializes some attributes.

        - *openmode*: optional, to open with a specific openmode, eventually
          different from the one specified at initialization.
        """

        super(netCDF, self).open(openmode=openmode)
        self._nc = netCDF4.Dataset(self.container.abspath, self.openmode)
        self.isopen = True

    def close(self):
        """
        Closes a netCDF.
        """

        if hasattr(self, '_nc') and self._nc._isopen:
            self._nc.close()
        self.isopen = False

    def variables_number(self):
        """Return the number of variables in resource."""
        return len(self._variables)

    def find_fields_in_resource(self, seed=None, generic=False, **kwargs):
        """
        Returns a list of the fields from resource whose name match the given
        seed.

        Args: \n
        - *seed*: might be a regular expression, a list of regular expressions
          or *None*. If *None* (default), returns the list of all fields in
          resource.
        - *fieldtype*: optional, among ('H2D', 'Misc') or a list of these strings.
          If provided, filters out the fields not of the given types.
        - *generic*: if True, returns complete fid's,
          union of {'FORMATname':fieldname} and the according generic fid of
          the fields.
        """

        if seed == None:
            fieldslist = self.listfields()
        elif isinstance(seed, str):
            fieldslist = util.find_re_in_list(seed, self.listfields())
        elif isinstance(seed, list):
            fieldslist = []
            for s in seed:
                fieldslist += util.find_re_in_list(s, self.listfields())
        if fieldslist == []:
            raise epygramError("no field matching '" + seed + \
                               "' was found in resource " + \
                               self.container.abspath)
        if generic:
            raise NotImplementedError("not yet.")

        return fieldslist

    def _listfields(self):
        """Returns the fid list of the fields inside the resource."""
        return self._variables.keys()

    @FileResource._openbeforedelayed
    def ncinfo_field(self, fid):
        """
        Get info about the field (dimensions and meta-data of the netCDF variable).
        
        Args: \n
        - *fid*: netCDF field identifier
        """

        assert fid in self.listfields(), 'field: ' + fid + ' not in resource.'
        dimensions = OrderedDict()
        for d in self._variables[fid].dimensions:
            dimensions[d] = len(self._dimensions[d])
        metadata = {a:getattr(self._variables[fid], a) for a in self._variables[fid].ncattrs()}

        return {'dimensions':dimensions,
                'metadata':metadata}


    @FileResource._openbeforedelayed
    def readfield(self, fid,
                  getdata=True,
                  only=None,
                  adhoc_behaviour=None):
        """
        Reads one field, given its netCDF name, and returns a Field instance.
        
        Args: \n
        - *fid*: netCDF field identifier
        - *getdata*: if *False*, only metadata are read, the field do not
          contain data.
        - *only*: to specify indexes [0 ... n-1] of specific dimensions,
          e.g. {'time':5,} to select only the 6th term of time dimension.
        - *adhoc_behaviour*: to specify "on the fly" a behaviour (usual
          dimensions or grids, ...).
        """

        # 0. initialization
        assert self.openmode != 'w', \
               "cannot read fields in resource if with openmode == 'w'."
        assert fid in self.listfields(), \
               ' '.join(["field", fid, "not found in resource."])
        only = util.ifNone_emptydict(only)
        adhoc_behaviour = util.ifNone_emptydict(adhoc_behaviour)
        field_kwargs = {'fid':{'netCDF':fid}}
        variable = self._variables[fid]
        behaviour = self.behaviour.copy()
        behaviour.update(adhoc_behaviour)

        # 1.1 identify usual dimensions
        all_dimensions_e2n = {}
        for d in self._dimensions.keys():
            for sd in config.netCDF_standard_dimensions:
                if d in config.netCDF_usualnames_for_standard_dimensions[sd]:
                    all_dimensions_e2n[sd] = d
        variable_dimensions = {d:len(self._dimensions[d]) for d in variable.dimensions}
        for d in variable_dimensions.keys():
            for sd in config.netCDF_standard_dimensions:
                # if behaviour is not explicitly given,
                # try to find out who is "d" among the standard dimensions
                if not sd in behaviour.keys() and d in config.netCDF_usualnames_for_standard_dimensions[sd]:
                    behaviour[sd] = d
        dims_dict_n2e = {}
        for d in variable_dimensions.keys():
            for k in config.netCDF_standard_dimensions:
                if d == behaviour.get(k):
                    dims_dict_n2e[d] = k
        dims_dict_e2n = {v:k for k, v in dims_dict_n2e.items()}

        # 1.2 try to identify grids
        for f in self.listfields():
            for sd in config.netCDF_standard_dimensions:
                sg = sd.replace('dimension', 'grid')
                # if behaviour is not explicitly given,
                # try to find out who is "f" among the standard grids
                if not sg in behaviour.keys() and f in config.netCDF_usualnames_for_standard_dimensions[sd] \
                or f == behaviour.get(sd):
                    behaviour[sg] = f

        # 2. time
        validity = FieldValidity()
        def get_validity(T_varname):
            if not T_varname in self._variables.keys():
                raise epygramError('unable to find T_grid in variables.')
            T = self._variables[T_varname][:]
            time_unit = self._variables[T_varname].units
            T = netCDF4.num2date(T, time_unit)
            validity = FieldValidityList()
            validity.pop()
            basis = netCDF4.num2date(0, time_unit)
            if not isinstance(basis, datetime.datetime):
                basis = '{:0>19}'.format(str(basis).strip())
                basis = dt_parser.parse(basis, yearfirst=True)  #FIXME: years < 1000 become > 2000
            for v in T:
                if isinstance(v, datetime.datetime):
                    fv = FieldValidity(date_time=v, basis=basis)
                else:
                    if v is None:
                        epylog.info('time information not available.')
                        fv = FieldValidity()
                    else:
                        v = '{:0>19}'.format(str(v).strip())
                        v = dt_parser.parse(v, yearfirst=True)  #FIXME: years < 1000 become > 2000
                        fv = FieldValidity(date_time=v, basis=basis)
                validity.append(fv)
            return validity
        if 'T_dimension' in dims_dict_e2n.keys():
            # field has a time dimension
            var_corresponding_to_T_grid = behaviour.get('T_grid', False)
            validity = get_validity(var_corresponding_to_T_grid)
            if dims_dict_e2n['T_dimension'] in only.keys():
                validity = validity[only[dims_dict_e2n['T_dimension']]]
        elif any([t in self._variables.keys() for t in config.netCDF_usualnames_for_standard_dimensions['T_dimension']]):
            # look for a time variable
            T_varnames = [t for t in config.netCDF_usualnames_for_standard_dimensions['T_dimension'] if t in self._variables.keys()]
            if len(T_varnames) == 1:
                _v = get_validity(T_varnames[0])
                if len(_v) == 1:
                    validity = _v
        field_kwargs['validity'] = validity

        # 3. GEOMETRY
        # ===========
        kwargs_geom = {}
        kwargs_geom['position_on_horizontal_grid'] = 'center'
        # 3.1 identify the structure
        keys = copy.copy(variable_dimensions.keys())
        for k in only.keys():
            if k in keys:
                keys.remove(k)
            else:
                raise ValueError("dimension: " + k + " from 'only' not in field variable.")
        if 'T_dimension' in dims_dict_e2n.keys() and dims_dict_e2n['T_dimension'] not in only.keys():
            keys.remove(dims_dict_e2n['T_dimension'])
        squeezed_variables = [dims_dict_n2e.get(k)
                              for k in keys
                              if variable_dimensions[k] != 1]
        H2D = set(squeezed_variables) == set(['X_dimension',
                                              'Y_dimension']) \
              or (set(squeezed_variables) == set(['N_dimension']) \
                  and all([d in all_dimensions_e2n for d in ['X_dimension',  # flattened grids
                                                             'Y_dimension']])) \
              or (set(squeezed_variables) == set(['N_dimension']) \
                  and behaviour.get('H1D_is_H2D_unstructured', False))  # or 2D unstructured grids
        D3 = set(squeezed_variables) == set(['X_dimension',
                                             'Y_dimension',
                                             'Z_dimension']) \
             or (set(squeezed_variables) == set(['N_dimension',
                                                 'Z_dimension']) \
                 and all([d in all_dimensions_e2n for d in ['X_dimension',  # flattened grids
                                                            'Y_dimension']])) \
             or (set(squeezed_variables) == set(['N_dimension',
                                                 'Z_dimension']) \
                 and behaviour.get('H1D_is_H2D_unstructured', False))  # or 2D unstructured grids
        V2D = set(squeezed_variables) == set(['N_dimension',
                                              'Z_dimension']) and not D3
        H1D = set(squeezed_variables) == set(['N_dimension']) and not H2D
        V1D = set(squeezed_variables) == set(['Z_dimension'])
        points = set(squeezed_variables) == set([])
        if not any([D3, H2D, V2D, H1D, V1D, points]):
            for d in set(variable_dimensions.keys()) - set(dims_dict_n2e.keys()):
                epylog.error(" ".join(["dimension:",
                                       d,
                                       "has not been identified as a usual",
                                       "(T,Z,Y,X) dimension. Please specify",
                                       "with readfield() argument",
                                       "adhoc_behaviour={'T_dimension':'" + d + "'}",
                                       "for instance or",
                                       "my_resource.behave(T_dimension=" + d + ")",
                                       "or complete",
                                       "config.netCDF_usualnames_for_standard_dimensions",
                                       "in $HOME/.epygram/userconfig.py"]))
            raise epygramError(" ".join(["unable to guess structure of field:",
                                         str(variable_dimensions.keys()),
                                         "=> refine behaviour dimensions or",
                                         "filter dimensions with 'only'."]))
        else:
            if D3:
                structure = '3D'
            elif H2D:
                structure = 'H2D'
            elif V2D:
                structure = 'V2D'
            elif H1D:
                structure = 'H1D'
                raise NotImplementedError('H1D: not yet.')  #TODO:
            elif V1D:
                structure = 'V1D'
            elif points:
                structure = 'Point'
            kwargs_geom['structure'] = structure

        # 3.2 vertical geometry (default)
        default_kwargs_vcoord = {'structure':'V',
                                 'typeoffirstfixedsurface':255,
                                 'position_on_grid':'mass',
                                 'grid':{'gridlevels': []},
                                 'levels':[0]}
        # TODO: complete with field dict when we have one
        # + fid generic ?
        kwargs_vcoord = default_kwargs_vcoord

        # 3.3 Specific parts
        # 3.3.1 dimensions
        dimensions = {}
        kwargs_geom['name'] = 'unstructured'
        if V2D or H1D:
            dimensions['X'] = variable_dimensions[dims_dict_e2n['N_dimension']]
            dimensions['Y'] = 1
        if V1D or points:
            dimensions['X'] = 1
            dimensions['Y'] = 1
        if D3 or H2D:
            if set(['X_dimension', 'Y_dimension']).issubset(set(dims_dict_e2n.keys())):
                flattened = False
            elif 'N_dimension' in dims_dict_e2n.keys():
                flattened = True
            else:
                raise epygramError('unable to find grid dimensions.')
            if not flattened:
                dimensions['X'] = variable_dimensions[dims_dict_e2n['X_dimension']]
                dimensions['Y'] = variable_dimensions[dims_dict_e2n['Y_dimension']]
            else:  # flattened
                if behaviour.get('H1D_is_H2D_unstructured', False):
                    dimensions['X'] = variable_dimensions[dims_dict_e2n['N_dimension']]
                    dimensions['Y'] = 1
                else:
                    assert 'X_dimension' in all_dimensions_e2n.keys(), \
                           ' '.join(["unable to find X_dimension of field:",
                                     "please specify with readfield() argument",
                                     "adhoc_behaviour={'X_dimension':'" + d + "'}",
                                     "for instance or",
                                     "my_resource.behave(X_dimension=" + d + ")",
                                     "or complete",
                                     "config.netCDF_usualnames_for_standard_dimensions",
                                     "in $HOME/.epygram/userconfig.py"])
                    assert 'Y_dimension' in all_dimensions_e2n.keys(), \
                           ' '.join(["unable to find Y_dimension of field:",
                                     "please specify with readfield() argument",
                                     "adhoc_behaviour={'Y_dimension':'" + d + "'}",
                                     "for instance or",
                                     "my_resource.behave(Y_dimension=" + d + ")",
                                     "or complete",
                                     "config.netCDF_usualnames_for_standard_dimensions",
                                     "in $HOME/.epygram/userconfig.py"])
                    dimensions['X'] = len(self._dimensions[all_dimensions_e2n['X_dimension']])
                    dimensions['Y'] = len(self._dimensions[all_dimensions_e2n['Y_dimension']])
        # 3.3.2 vertical part
        if D3 or V1D or V2D:
            var_corresponding_to_Z_grid = behaviour.get('Z_grid', False)
            #assert var_corresponding_to_Z_grid in self._variables.keys(), \
            #       'unable to find Z_grid in variables.'
            levels = None
            if var_corresponding_to_Z_grid in self._variables.keys():
                if hasattr(self._variables[var_corresponding_to_Z_grid], 'standard_name') \
                   and self._variables[var_corresponding_to_Z_grid].standard_name in ('atmosphere_hybrid_sigma_pressure_coordinate',
                                                                                      'atmosphere_hybrid_height_coordinate'):
                    formula_terms = self._variables[var_corresponding_to_Z_grid].formula_terms.split(' ')
                    if 'a:' in formula_terms and 'p0:' in formula_terms:
                        a_name = formula_terms[formula_terms.index('a:') + 1]
                        p0_name = formula_terms[formula_terms.index('p0:') + 1]
                        a = self._variables[a_name][:] * self._variables[p0_name][:]
                    elif 'ap:' in formula_terms:
                        a_name = formula_terms[formula_terms.index('ap:') + 1]
                        a = self._variables[a_name][:]
                    b_name = formula_terms[formula_terms.index('b:') + 1]
                    b = self._variables[b_name][:]
                    gridlevels = [(i + 1, {'Ai':a[i], 'Bi':b[i]}) for i in range(len(a))]
                    levels = [i + 1 for i in range(len(a))]
                else:
                    gridlevels = self._variables[var_corresponding_to_Z_grid][:]
                if hasattr(self._variables[behaviour['Z_grid']], 'standard_name'):
                    kwargs_vcoord['typeoffirstfixedsurface'] = _typeoffirstfixedsurface_dict.get(self._variables[behaviour['Z_grid']].standard_name, 255)
                # TODO: complete the reading of variable units to convert
                if hasattr(self._variables[behaviour['Z_grid']], 'units'):
                    if self._variables[behaviour['Z_grid']].units == 'km':
                        gridlevels = gridlevels * 1000.  # get back to metres
            else:
                gridlevels = range(1, variable_dimensions[dims_dict_e2n['Z_dimension']] + 1)
                kwargs_vcoord['typeoffirstfixedsurface'] = 255
            kwargs_vcoord['grid']['gridlevels'] = [p for p in gridlevels]  # footprints purpose
            if levels is None:
                kwargs_vcoord['levels'] = kwargs_vcoord['grid']['gridlevels']  # could it be else ?
            else:
                kwargs_vcoord['levels'] = levels

        # 3.3.3 horizontal part
        # find grid in variables
        if H2D or D3:
            def find_grid_in_variables():
                var_corresponding_to_X_grid = behaviour.get('X_grid', False)
                if not var_corresponding_to_X_grid in self._variables.keys():
                    epylog.error(" ".join(["unable to find X_grid in variables.",
                                           "Please specify with readfield()",
                                           "argument",
                                           "adhoc_behaviour={'X_grid':'name_of_the_variable'}",
                                           "for instance or",
                                           "my_resource.behave(X_grid='name_of_the_variable')"]))
                    raise epygramError('unable to find X_grid in variables.')
                var_corresponding_to_Y_grid = behaviour.get('Y_grid', False)
                if not var_corresponding_to_Y_grid in self._variables.keys():
                    epylog.error(" ".join(["unable to find Y_grid in variables.",
                                           "Please specify with readfield()",
                                           "argument",
                                           "adhoc_behaviour={'Y_grid':'name_of_the_variable'}",
                                           "for instance or",
                                           "my_resource.behave(Y_grid='name_of_the_variable')"]))
                    raise epygramError('unable to find Y_grid in variables.')
                else:
                    if hasattr(self._variables[var_corresponding_to_Y_grid], 'standard_name') \
                    and self._variables[var_corresponding_to_Y_grid].standard_name == 'projection_y_coordinate' \
                    and self._variables[var_corresponding_to_X_grid].standard_name == 'projection_x_coordinate':
                        behaviour['grid_is_lonlat'] = False
                    elif 'lat' in var_corresponding_to_Y_grid.lower() \
                    and 'lon' in var_corresponding_to_X_grid.lower() \
                    and 'grid_is_lonlat' not in behaviour.keys():
                        behaviour['grid_is_lonlat'] = True
                if len(self._variables[var_corresponding_to_X_grid].dimensions) == 1 \
                and len(self._variables[var_corresponding_to_Y_grid].dimensions) == 1:
                    # case of a flat grid
                    if not flattened:
                        # case of a regular grid where X is constant on a column
                        # and Y constant on a row: reconstruct 2D
                        X = self._variables[var_corresponding_to_X_grid][:]
                        Y = self._variables[var_corresponding_to_Y_grid][:]
                        Xgrid = numpy.ones((Y.size, X.size)) * X
                        Ygrid = (numpy.ones((Y.size, X.size)).transpose() * Y).transpose()
                    elif behaviour.get('H1D_is_H2D_unstructured', False):
                        # case of a H2D unstructured field
                        X = self._variables[var_corresponding_to_X_grid][:]
                        Y = self._variables[var_corresponding_to_Y_grid][:]
                        Xgrid = X.reshape((1, len(X)))
                        Ygrid = Y.reshape((1, len(Y)))
                    else:
                        # case of a H2D field with flattened grid
                        if len(X) == dimensions['X'] * dimensions['Y']:
                            Xgrid = X.reshape((dimensions['Y'], dimensions['X']))
                            Ygrid = Y.reshape((dimensions['Y'], dimensions['X']))
                        else:
                            raise epygramError('unable to reconstruct 2D grid.')
                elif len(self._variables[var_corresponding_to_X_grid].dimensions) == 2 \
                and len(self._variables[var_corresponding_to_Y_grid].dimensions) == 2:
                    Xgrid = self._variables[var_corresponding_to_X_grid][:, :]
                    Ygrid = self._variables[var_corresponding_to_Y_grid][:, :]
                if Ygrid[0, 0] > Ygrid[-1, 0] and not behaviour.get('reverse_Ygrid'):
                    epylog.warning("Ygrid seems to be reversed; shouldn't behaviour['reverse_Yaxis'] be True ?")
                elif behaviour.get('reverse_Yaxis'):
                    Ygrid = Ygrid[::-1, :]

                return Xgrid, Ygrid

            # projection or grid
            if hasattr(variable, 'grid_mapping') and \
               (self._variables[variable.grid_mapping].grid_mapping_name in ('lambert_conformal_conic',
                                                                             'mercator',
                                                                             'polar_stereographic',
                                                                             'latitude_longitude') \
                or 'gauss' in self._variables[variable.grid_mapping].grid_mapping_name.lower()):
                # geometry described as "grid_mapping" meta-data
                gm = variable.grid_mapping
                grid_mapping = self._variables[gm]
                if hasattr(grid_mapping, 'ellipsoid'):
                    kwargs_geom['geoid'] = {'ellps':grid_mapping.ellipsoid}
                elif hasattr(grid_mapping, 'earth_radius'):
                    kwargs_geom['geoid'] = {'a':grid_mapping.earth_radius,
                                            'b':grid_mapping.earth_radius}
                elif hasattr(grid_mapping, 'semi_major_axis') and hasattr(grid_mapping, 'semi_minor_axis'):
                    kwargs_geom['geoid'] = {'a':grid_mapping.semi_major_axis,
                                            'b':grid_mapping.semi_minor_axis}
                elif hasattr(grid_mapping, 'semi_major_axis') and hasattr(grid_mapping, 'inverse_flattening'):
                    kwargs_geom['geoid'] = {'a':grid_mapping.semi_major_axis,
                                            'rf':grid_mapping.inverse_flattening}
                else:
                    kwargs_geom['geoid'] = config.default_geoid
                if hasattr(grid_mapping, 'position_on_horizontal_grid'):
                    kwargs_geom['position_on_horizontal_grid'] = grid_mapping.position_on_horizontal_grid
                if grid_mapping.grid_mapping_name in ('lambert_conformal_conic', 'mercator', 'polar_stereographic'):
                    if (hasattr(self._variables[variable.grid_mapping], 'x_resolution') \
                    or not behaviour.get('grid_is_lonlat', False)):
                        # if resolution is either in grid_mapping attributes or in the grid itself
                        kwargs_geom['name'] = _proj_dict_inv[grid_mapping.grid_mapping_name]
                        if hasattr(grid_mapping, 'x_resolution'):
                            Xresolution = grid_mapping.x_resolution
                            Yresolution = grid_mapping.y_resolution
                        else:
                            Xgrid, Ygrid = find_grid_in_variables()
                            if behaviour.get('H1D_is_H2D_unstructured', False):
                                raise epygramError('unable to retrieve both X_resolution and Y_resolution from a 1D list of points.')
                            else:
                                Xresolution = abs(Xgrid[0, 0] - Xgrid[0, 1])
                                Yresolution = abs(Ygrid[0, 0] - Ygrid[1, 0])
                        grid = {
                                'X_resolution':Xresolution,
                                'Y_resolution':Yresolution,
                                'LAMzone':None}
                        import pyproj
                        if kwargs_geom['name'] == 'lambert':
                            kwargs_geom['projection'] = {'reference_lon':Angle(grid_mapping.longitude_of_central_meridian, 'degrees'),
                                                         'rotation':Angle(0., 'degrees')}
                            if hasattr(grid_mapping, 'rotation'):
                                kwargs_geom['projection']['rotation'] = Angle(grid_mapping.rotation, 'degrees')
                            if isinstance(grid_mapping.standard_parallel, numpy.ndarray):
                                s1, s2 = grid_mapping.standard_parallel
                                kwargs_geom['projection']['secant_lat1'] = Angle(s1, 'degrees')
                                kwargs_geom['projection']['secant_lat2'] = Angle(s2, 'degrees')
                            else:
                                r = grid_mapping.standard_parallel
                                kwargs_geom['projection']['reference_lat'] = Angle(r, 'degrees')
                                s1 = s2 = r
                            fe = grid_mapping.false_easting
                            fn = grid_mapping.false_northing
                            reference_lat = grid_mapping.latitude_of_projection_origin

                            # compute x_0, y_0...
                            p = pyproj.Proj(proj='lcc',
                                            lon_0=kwargs_geom['projection']['reference_lon'].get('degrees'),
                                            lat_1=s1, lat_2=s2,
                                            **kwargs_geom['geoid'])
                            dx, dy = p(kwargs_geom['projection']['reference_lon'].get('degrees'),
                                       reference_lat)
                            # ... for getting center coords from false_easting, false_northing
                            p = pyproj.Proj(proj='lcc',
                                            lon_0=kwargs_geom['projection']['reference_lon'].get('degrees'),
                                            lat_1=s1, lat_2=s2,
                                            x_0=-dx, y_0=-dy,
                                            **kwargs_geom['geoid'])
                            llc = p(-fe, -fn, inverse=True)
                            del p
                            grid['input_lon'] = Angle(llc[0], 'degrees')
                            grid['input_lat'] = Angle(llc[1], 'degrees')
                            grid['input_position'] = (float(dimensions['X'] - 1) / 2.,
                                                      float(dimensions['Y'] - 1) / 2.)
                        elif kwargs_geom['name'] == 'mercator':
                            kwargs_geom['projection'] = {'reference_lon':Angle(grid_mapping.longitude_of_central_meridian, 'degrees'),
                                                         'rotation':Angle(0., 'degrees')}
                            if hasattr(grid_mapping, 'rotation'):
                                kwargs_geom['projection']['rotation'] = Angle(grid_mapping.rotation, 'degrees')
                            kwargs_geom['projection']['reference_lat'] = Angle(0., 'degrees')
                            if grid_mapping.standard_parallel != 0.:
                                lat_ts = grid_mapping.standard_parallel
                                kwargs_geom['projection']['secant_lat'] = Angle(lat_ts, 'degrees')
                            else:
                                lat_ts = 0.
                            fe = grid_mapping.false_easting
                            fn = grid_mapping.false_northing
                            # compute x_0, y_0...
                            p = pyproj.Proj(proj='merc',
                                            lon_0=kwargs_geom['projection']['reference_lon'].get('degrees'),
                                            lat_ts=lat_ts,
                                            **kwargs_geom['geoid'])
                            dx, dy = p(kwargs_geom['projection']['reference_lon'].get('degrees'),
                                       0.)
                            # ... for getting center coords from false_easting, false_northing
                            p = pyproj.Proj(proj='merc',
                                            lon_0=kwargs_geom['projection']['reference_lon'].get('degrees'),
                                            lat_ts=lat_ts,
                                            x_0=-dx, y_0=-dy,
                                            **kwargs_geom['geoid'])
                            llc = p(-fe, -fn, inverse=True)
                            del p
                            grid['input_lon'] = Angle(llc[0], 'degrees')
                            grid['input_lat'] = Angle(llc[1], 'degrees')
                            grid['input_position'] = (float(dimensions['X'] - 1) / 2., float(dimensions['Y'] - 1) / 2.)
                        elif kwargs_geom['name'] == 'polar_stereographic':
                            kwargs_geom['projection'] = {'reference_lon':Angle(grid_mapping.straight_vertical_longitude_from_pole, 'degrees'),
                                                         'rotation':Angle(0., 'degrees')}
                            if hasattr(grid_mapping, 'rotation'):
                                kwargs_geom['projection']['rotation'] = Angle(grid_mapping.rotation, 'degrees')
                            kwargs_geom['projection']['reference_lat'] = Angle(grid_mapping.latitude_of_projection_origin, 'degrees')
                            lat_ts = grid_mapping.standard_parallel
                            if grid_mapping.standard_parallel != grid_mapping.latitude_of_projection_origin:
                                kwargs_geom['projection']['secant_lat'] = Angle(lat_ts, 'degrees')
                            fe = grid_mapping.false_easting
                            fn = grid_mapping.false_northing
                            # compute x_0, y_0...
                            p = pyproj.Proj(proj='stere',
                                            lon_0=kwargs_geom['projection']['reference_lon'].get('degrees'),
                                            lat_0=kwargs_geom['projection']['reference_lat'].get('degrees'),
                                            lat_ts=lat_ts,
                                            **kwargs_geom['geoid'])
                            dx, dy = p(kwargs_geom['projection']['reference_lon'].get('degrees'),
                                       kwargs_geom['projection']['reference_lat'].get('degrees'),)
                            # ... for getting center coords from false_easting, false_northing
                            p = pyproj.Proj(proj='stere',
                                            lon_0=kwargs_geom['projection']['reference_lon'].get('degrees'),
                                            lat_0=kwargs_geom['projection']['reference_lat'].get('degrees'),
                                            lat_ts=lat_ts,
                                            x_0=-dx, y_0=-dy,
                                            **kwargs_geom['geoid'])
                            llc = p(-fe, -fn, inverse=True)
                            del p
                            grid['input_lon'] = Angle(llc[0], 'degrees')
                            grid['input_lat'] = Angle(llc[1], 'degrees')
                            grid['input_position'] = (float(dimensions['X'] - 1) / 2., float(dimensions['Y'] - 1) / 2.)
                    else:
                        # no resolution available: grid mapping is useless
                        gm = None
                elif 'gauss' in grid_mapping.grid_mapping_name.lower():
                    if hasattr(grid_mapping, 'latitudes'):
                        latitudes = self._variables[grid_mapping.latitudes.split(' ')[1]][:]
                    else:
                        # NOTE: this is a (good) approximation actually, the true latitudes are the roots of Legendre polynoms
                        raise NotImplementedError('(re-)computation of Gauss latitudes (not in file metadata).')
                    grid = {'latitudes':FPList([Angle(l, 'degrees') for l in latitudes]),
                            'dilatation_coef':1.}
                    if hasattr(grid_mapping, 'lon_number_by_lat'):
                        if isinstance(grid_mapping.lon_number_by_lat, unicode):
                            lon_number_by_lat = self._variables[grid_mapping.lon_number_by_lat.split(' ')[1]][:]
                        else:
                            kwargs_geom['name'] = 'regular_gauss'
                            lon_number_by_lat = [dimensions['X'] for _ in range(dimensions['Y'])]
                        if hasattr(grid_mapping, 'pole_lon'):
                            kwargs_geom['name'] = 'rotated_reduced_gauss'
                            grid['pole_lon'] = Angle(grid_mapping.pole_lon, 'degrees')
                            grid['pole_lat'] = Angle(grid_mapping.pole_lat, 'degrees')
                            if hasattr(grid_mapping, 'dilatation_coef'):
                                grid['dilatation_coef'] = grid_mapping.dilatation_coef
                        else:
                            kwargs_geom['name'] = 'reduced_gauss'
                    dimensions = {'max_lon_number':int(max(lon_number_by_lat)),
                                  'lat_number':len(latitudes),
                                  'lon_number_by_lat':FPList([int(n) for n in
                                                      lon_number_by_lat])}
                elif grid_mapping.grid_mapping_name == 'latitude_longitude':
                    # try to find out longitude, latitude arrays
                    for f in config.netCDF_usualnames_for_lonlat_grids['X']:
                        if f in self.listfields():
                            behaviour['X_grid'] = f
                            break
                    for f in config.netCDF_usualnames_for_lonlat_grids['Y']:
                        if f in self.listfields():
                            behaviour['Y_grid'] = f
                            break
                    Xgrid, Ygrid = find_grid_in_variables()
                    grid = {'longitudes':Xgrid,
                            'latitudes':Ygrid}
                else:
                    raise NotImplementedError('grid_mapping.grid_mapping_name == ' + grid_mapping.grid_mapping_name)
            else:
                if hasattr(variable, 'grid_mapping'):
                    epylog.info('grid_mapping ignored: unknown case')
                # grid only in variables
                Xgrid, Ygrid = find_grid_in_variables()
                if behaviour.get('grid_is_lonlat', False):
                    grid = {'longitudes':Xgrid,
                            'latitudes':Ygrid}
                else:
                    # grid is not lon/lat and no other metadata available : Academic
                    if flattened:
                        raise NotImplementedError("flattened academic grid.")
                    kwargs_geom['name'] = 'academic'
                    grid = {'LAMzone':None,
                            'X_resolution':abs(Xgrid[0, 1] - Xgrid[0, 0]),
                            'Y_resolution':abs(Ygrid[1, 0] - Ygrid[0, 0])}
        elif V1D or V2D or points:
            var_corresponding_to_X_grid = behaviour.get('X_grid', False)
            if not var_corresponding_to_X_grid in self._variables.keys():
                if points or V1D:
                    lon = ['_']
                else:
                    raise epygramError('unable to find X_grid in variables.')
            else:
                lon = self._variables[var_corresponding_to_X_grid][:]
            var_corresponding_to_Y_grid = behaviour.get('Y_grid', False)
            if not var_corresponding_to_Y_grid in self._variables.keys():
                if points or V1D:
                    lat = ['_']
                else:
                    raise epygramError('unable to find Y_grid in variables.')
            else:
                lat = self._variables[var_corresponding_to_Y_grid][:]
            grid = {'longitudes':lon,
                    'latitudes':lat,
                    'LAMzone':None}

        # 3.4 build geometry
        vcoordinate = fpx.geometry(**kwargs_vcoord)
        kwargs_geom['grid'] = grid
        kwargs_geom['dimensions'] = dimensions
        kwargs_geom['vcoordinate'] = vcoordinate
        geometry = fpx.geometry(**kwargs_geom)

        # 4. build field
        field_kwargs['geometry'] = geometry
        field_kwargs['structure'] = kwargs_geom['structure']
        comment = {}
        for a in variable.ncattrs():
            if a != 'validity':
                if isinstance(variable.getncattr(a), numpy.float32):  # pb with json and float32
                    comment.update({a:numpy.float64(variable.getncattr(a))})
                else:
                    comment.update({a:variable.getncattr(a)})
        comment = json.dumps(comment)
        if comment != '{}':
            field_kwargs['comment'] = comment
        field = fpx.field(**field_kwargs)
        if getdata:
            if only:
                n = len(variable.dimensions)
                buffdata = variable
                for k, i in only.items():
                    d = variable.dimensions.index(k)
                    buffdata = util.restrain_to_index_i_of_dim_d(buffdata, i, d, n=n)
            else:
                buffdata = variable[...]
            # check there is no leftover unknown dimension
            field_dim_num = 1 if len(field.validity) > 1 else 0
            if field.structure != 'Point':
                field_dim_num += [int(c) for c in field.structure if c.isdigit()][0]
                if (H2D or D3) and flattened:
                    field_dim_num -= 1
            assert field_dim_num == len(buffdata.squeeze().shape), \
                   ' '.join(['shape of field and identified usual dimensions',
                             'do not match: use *only* to filter or',
                             '*adhoc_behaviour* to identify dimensions'])
            # re-shuffle to have data indexes in order (t,z,y,x)
            positions = []
            shp4D = [1, 1, 1, 1]
            if 'T_dimension' in dims_dict_e2n.keys():
                idx = variable.dimensions.index(dims_dict_e2n['T_dimension'])
                positions.append(idx)
                shp4D[0] = buffdata.shape[idx]
            if 'Z_dimension' in dims_dict_e2n.keys():
                idx = variable.dimensions.index(dims_dict_e2n['Z_dimension'])
                positions.append(idx)
                shp4D[1] = buffdata.shape[idx]
            if 'Y_dimension' in dims_dict_e2n.keys():
                idx = variable.dimensions.index(dims_dict_e2n['Y_dimension'])
                positions.append(idx)
                shp4D[2] = buffdata.shape[idx]
            if 'X_dimension' in dims_dict_e2n.keys():
                idx = variable.dimensions.index(dims_dict_e2n['X_dimension'])
                positions.append(idx)
                shp4D[3] = buffdata.shape[idx]
            elif 'N_dimension' in dims_dict_e2n.keys():
                idx = variable.dimensions.index(dims_dict_e2n['N_dimension'])
                positions.append(idx)
                shp4D[3] = buffdata.shape[idx]
            for d in variable.dimensions:
                # whatever the order of these, they must have been filtered and dimension 1 (only)
                if d not in dims_dict_e2n.values():
                    positions.append(variable.dimensions.index(d))
            shp4D = tuple(shp4D)
            buffdata = buffdata.transpose(*positions).squeeze()
            if isinstance(buffdata, numpy.ma.masked_array):
                data = numpy.ma.zeros(shp4D)
            else:
                data = numpy.empty(shp4D)
            if (H2D or D3) and flattened:
                if len(buffdata.shape) == 2:
                    if D3:
                        first_dimension = 'Z'
                    else:
                        first_dimension = 'T'
                else:
                    first_dimension = None
                data = geometry.reshape_data(buffdata, first_dimension=first_dimension, d4=True)
            else:
                data[...] = buffdata.reshape(data.shape)
            if behaviour.get('reverse_Yaxis'):
                data[...] = data[:, :, ::-1, :]
            field.setdata(data)

        return field

    def writefield(self, field, compression=4, metadata=None):
        """
        Write a field in resource.
        Args:\n
        - *compression* ranges from 1 (low compression, fast writing)
          to 9 (high compression, slow writing). 0 is no compression.
        - *metadata*: dict, can be filled by any meta-data, that will be stored
          as attribute of the netCDF variable.
        """

        metadata = util.ifNone_emptydict(metadata)
        vartype = 'f8'
        fill_value = -999999.9
        def check_or_add_dim(d, d_in_field=None, size=None):
            if size is None:
                if d_in_field is None:
                    d_in_field = d
                size = field.geometry.dimensions[d_in_field]
            if d not in self._dimensions:
                self._nc.createDimension(d, size=size)
            else:
                assert len(self._dimensions[d]) == size, \
                       "dimensions mismatch: " + d + ": " + \
                       str(self._dimensions[d]) + " != " + str(size)
        def check_or_add_variable(varname, vartype,
                                  dimensions=(),
                                  **kwargs):
            if unicode(varname) not in self._variables.keys():
                var = self._nc.createVariable(varname, vartype,
                                              dimensions=dimensions,
                                              **kwargs)
                status = 'created'
            else:
                assert self._variables[varname].dtype == vartype, \
                       ' '.join(['variable', varname,
                                 'already exist with other type:',
                                 self._variables[varname].dtype])
                if isinstance(dimensions, str):
                    dimensions = (dimensions,)
                assert self._variables[varname].dimensions == tuple(dimensions), \
                       ' '.join(['variable', varname,
                                 'already exist with other dimensions:',
                                 str(self._variables[varname].dimensions)])
                var = self._variables[varname]
                status = 'match'
            return var, status

        assert field.fid.has_key('netCDF')
        assert not field.spectral

        # 1. dimensions
        T = Y = X = G = N = None
        dims = []
        # time
        if len(field.validity) > 1:
            # default
            T = config.netCDF_usualnames_for_standard_dimensions['T_dimension'][0]
            # or any existing identified time dimension
            T = {'found':v for v in self._dimensions
                 if (v in config.netCDF_usualnames_for_standard_dimensions['T_dimension']
                     and len(self._dimensions[v]) == len(field.validity))}.get('found', T)
            # or specified behaviour
            T = self.behaviour.get('T_dimension', T)
            check_or_add_dim(T, size=len(field.validity))
        # vertical part
        # default
        Z = config.netCDF_usualnames_for_standard_dimensions['Z_dimension'][0]
        # or any existing identified time dimension
        Z = {'found':v for v in self._dimensions
                 if (v in config.netCDF_usualnames_for_standard_dimensions['Z_dimension']
                     and len(self._dimensions[v]) == len(field.geometry.vcoordinate.levels))}.get('found', Z)
        # or specified behaviour
        Z = self.behaviour.get('Z_dimension', Z)
        if 'gridlevels' in field.geometry.vcoordinate.grid.keys():
            Z_gridsize = max(len(field.geometry.vcoordinate.grid['gridlevels']), 1)
            if field.geometry.vcoordinate.typeoffirstfixedsurface in (118, 119):
                Z_gridsize -= 1
        else:
            Z_gridsize = 1
        if Z_gridsize > 1:
            check_or_add_dim(Z, size=Z_gridsize)
        # horizontal
        if self.behaviour.get('flatten_horizontal_grids', False):
            _gpn = field.geometry.gridpoints_number
            G = 'gridpoints_number'
            check_or_add_dim(G, size=_gpn)
        if field.geometry.rectangular_grid:
            if field.geometry.dimensions['Y'] > 1 and field.geometry.dimensions['X'] > 1:
                Y = self.behaviour.get('Y_dimension',
                                       config.netCDF_usualnames_for_standard_dimensions['Y_dimension'][0])
                check_or_add_dim(Y, d_in_field='Y')
                X = self.behaviour.get('X_dimension',
                                       config.netCDF_usualnames_for_standard_dimensions['X_dimension'][0])
                check_or_add_dim(X, d_in_field='X')
            elif field.geometry.dimensions['X'] > 1:
                N = self.behaviour.get('N_dimension',
                                       config.netCDF_usualnames_for_standard_dimensions['N_dimension'][0])
                check_or_add_dim(N, d_in_field='X')
        elif 'gauss' in field.geometry.name:
            Y = self.behaviour.get('Y_dimension', 'latitude')
            check_or_add_dim(Y, d_in_field='lat_number')
            X = self.behaviour.get('X_dimension', 'longitude')
            check_or_add_dim(X, d_in_field='max_lon_number')
        else:
            raise NotImplementedError("grid not rectangular nor a gauss one.")

        # 2. validity
        #TODO: deal with unlimited time dimension ?
        if field.validity[0] != FieldValidity():
            tgrid = config.netCDF_usualnames_for_standard_dimensions['T_dimension'][0]
            tgrid = {'found':v for v in self._variables
                     if v in config.netCDF_usualnames_for_standard_dimensions['T_dimension']}.get('found', tgrid)
            tgrid = self.behaviour.get('T_grid', tgrid)
            if len(field.validity) == 1:
                _, _status = check_or_add_variable(tgrid, float)
            else:
                _, _status = check_or_add_variable(tgrid, float, T)
                dims.append(tgrid)
            datetime0 = field.validity[0].getbasis().isoformat(sep=' ')
            datetimes = [int((dt.get() - field.validity[0].getbasis()).total_seconds()) for dt in field.validity]
            if _status == 'created':
                self._variables[tgrid][:] = datetimes
                self._variables[tgrid].units = ' '.join(['seconds', 'since', datetime0])
            else:
                assert (self._variables[tgrid][:] == datetimes).all(), \
                       ' '.join(['variable', tgrid, 'mismatch.'])

        # 3. geometry
        # 3.1 vertical part
        if len(field.geometry.vcoordinate.levels) > 1:
            dims.append(Z)
        if Z_gridsize > 1:
            zgridname = config.netCDF_usualnames_for_standard_dimensions['Z_dimension'][0]
            zgridname = {'found':v for v in self._variables
                         if v in config.netCDF_usualnames_for_standard_dimensions['Z_dimension']}.get('found', zgridname)
            zgridname = self.behaviour.get('Z_grid', zgridname)
            if field.geometry.vcoordinate.typeoffirstfixedsurface in (118, 119):
                ZP1 = Z + '+1'
                check_or_add_dim(ZP1, size=Z_gridsize + 1)
                zgrid, _status = check_or_add_variable(zgridname, int)
                if _status == 'created':
                    if field.geometry.vcoordinate.typeoffirstfixedsurface == 119:
                        zgrid.standard_name = "atmosphere_hybrid_sigma_pressure_coordinate"
                        zgrid.positive = "down"
                        zgrid.formula_terms = "ap: hybrid_coef_A b: hybrid_coef_B ps: surface_air_pressure"
                        check_or_add_variable('hybrid_coef_A', vartype, ZP1)
                        self._variables['hybrid_coef_A'][:] = [iab[1]['Ai'] for iab in field.geometry.vcoordinate.grid['gridlevels']]
                        check_or_add_variable('hybrid_coef_B', vartype, ZP1)
                        self._variables['hybrid_coef_B'][:] = [iab[1]['Bi'] for iab in field.geometry.vcoordinate.grid['gridlevels']]
                    elif field.geometry.vcoordinate.typeoffirstfixedsurface == 118:
                        # TOBECHECKED:
                        zgrid.standard_name = "atmosphere_hybrid_height_coordinate"
                        zgrid.positive = "up"
                        zgrid.formula_terms = "a: hybrid_coef_A b: hybrid_coef_B orog: orography"
                        check_or_add_variable('hybrid_coef_A', vartype, ZP1)
                        self._variables['hybrid_coef_A'][:] = [iab[1]['Ai'] for iab in field.geometry.vcoordinate.grid['gridlevels']]
                        check_or_add_variable('hybrid_coef_B', vartype, ZP1)
                        self._variables['hybrid_coef_B'][:] = [iab[1]['Bi'] for iab in field.geometry.vcoordinate.grid['gridlevels']]
                else:
                    epylog.info('assume 118/119 type vertical grid matches.')
            else:
                if len(numpy.shape(field.geometry.vcoordinate.grid['gridlevels'])) > 1:
                    dims_Z = [d for d in [Z, Y, X, G, N] if d is not None]
                else:
                    dims_Z = Z
                zgrid, _status = check_or_add_variable(zgridname, vartype, dims_Z)
                u = {102:'m', 103:'m', 100:'hPa'}.get(field.geometry.vcoordinate.typeoffirstfixedsurface, None)
                if u is not None:
                    zgrid.units = u
                if _status == 'created':
                    zgrid[:] = field.geometry.vcoordinate.grid['gridlevels']
                else:
                    assert zgrid[:].all() == numpy.array(field.geometry.vcoordinate.grid['gridlevels']).all(), \
                           ' '.join(['variable', zgrid, 'mismatch.'])
            if _typeoffirstfixedsurface_dict_inv.get(field.geometry.vcoordinate.typeoffirstfixedsurface, False):
                zgrid.short_name = _typeoffirstfixedsurface_dict_inv[field.geometry.vcoordinate.typeoffirstfixedsurface]
        # 3.2 grid (lonlat)
        dims_lonlat = []
        (lons, lats) = field.geometry.get_lonlat_grid()
        if self.behaviour.get('flatten_horizontal_grids'):
            dims_lonlat.append(G)
            dims.append(G)
            lons = stretch_array(lons)
            lats = stretch_array(lats)
        elif field.geometry.dimensions.get('Y', field.geometry.dimensions.get('lat_number', 0)) > 1:  # both Y and X dimensions
            dims_lonlat.extend([Y, X])
            dims.extend([Y, X])
        elif field.geometry.dimensions['X'] > 1:  # only X ==> N
            dims_lonlat.append(N)
            dims.append(N)
        # else: pass (single point or profile)
        if isinstance(lons, numpy.ma.masked_array):
            lons = lons.filled(fill_value)
            lats = lats.filled(fill_value)
        else:
            fill_value = None
        try:
            _ = float(stretch_array(lons)[0])
        except ValueError:
            write_lonlat_grid = False
        else:
            write_lonlat_grid = self.behaviour.get('write_lonlat_grid', True)
        if write_lonlat_grid:
            lons_var, _status = check_or_add_variable('longitude', vartype, dims_lonlat, fill_value=fill_value)
            lats_var, _status = check_or_add_variable('latitude', vartype, dims_lonlat, fill_value=fill_value)
            if _status == 'match':
                epylog.info('assume lons/lats match.')
            else:
                lons_var[...] = lons[...]
                lats_var[...] = lats[...]
        # 3.3 meta-data
        def set_ellipsoid(meta):
            if 'ellps' in field.geometry.geoid:
                self._variables[meta].ellipsoid = field.geometry.geoid['ellps']
            elif field.geometry.geoid.get('a', False) == field.geometry.geoid.get('b', True):
                self._variables[meta].earth_radius = field.geometry.geoid['a']
            elif field.geometry.geoid.get('a', False) and field.geometry.geoid.get('b', False):
                self._variables[meta].semi_major_axis = field.geometry.geoid['a']
                self._variables[meta].semi_minor_axis = field.geometry.geoid['b']
            elif field.geometry.geoid.get('a', False) and field.geometry.geoid.get('rf', False):
                self._variables[meta].semi_major_axis = field.geometry.geoid['a']
                self._variables[meta].inverse_flattening = field.geometry.geoid['rf']
            else:
                raise NotImplementedError('this kind of geoid:' + str(field.geometry.geoid))
        if field.geometry.dimensions.get('Y', field.geometry.dimensions.get('lat_number', 0)) > 1:
            if 'gauss' in field.geometry.name:
                # reduced Gauss case
                meta = 'Gauss_grid'
                _, _status = check_or_add_variable(meta, int)
                if _status == 'created':
                    self._variables[meta].grid_mapping_name = field.geometry.name + "_grid"
                    set_ellipsoid(meta)
                    if 'reduced' in field.geometry.name:
                        self._variables[meta].lon_number_by_lat = 'var: lon_number_by_lat'
                        check_or_add_variable('lon_number_by_lat', int, Y)
                        self._variables['lon_number_by_lat'][:] = field.geometry.dimensions['lon_number_by_lat']
                    self._variables[meta].latitudes = 'var: gauss_latitudes'
                    check_or_add_variable('gauss_latitudes', float, Y)
                    self._variables['gauss_latitudes'][:] = [l.get('degrees') for l in field.geometry.grid['latitudes']]
                    if 'pole_lon' in field.geometry.grid.keys():
                        self._variables[meta].pole_lon = field.geometry.grid['pole_lon'].get('degrees')
                        self._variables[meta].pole_lat = field.geometry.grid['pole_lat'].get('degrees')
                    if 'dilatation_coef' in field.geometry.grid.keys():
                        self._variables[meta].dilatation_coef = field.geometry.grid['dilatation_coef']
                else:
                    epylog.info('assume Gauss grid parameters match.')
            elif field.geometry.projected_geometry:
                # projections
                if field.geometry.name in ('lambert', 'mercator', 'polar_stereographic'):
                    meta = 'Projection_parameters'
                    _, _status = check_or_add_variable(meta, int)
                    if _status == 'created':
                        self._variables[meta].grid_mapping_name = _proj_dict[field.geometry.name]
                        set_ellipsoid(meta)
                        if field.geometry.position_on_horizontal_grid != 'center':
                            self._variables[meta].position_on_horizontal_grid = field.geometry.position_on_horizontal_grid
                        self._variables[meta].x_resolution = field.geometry.grid['X_resolution']
                        self._variables[meta].y_resolution = field.geometry.grid['Y_resolution']
                        if field.geometry.grid.get('LAMzone'):
                            _lon_cen, _lat_cen = field.geometry.ij2ll(float(field.geometry.dimensions['X'] - 1.) / 2.,
                                                                      float(field.geometry.dimensions['Y'] - 1.) / 2.)
                        else:
                            _lon_cen = field.geometry._center_lon.get('degrees')
                            _lat_cen = field.geometry._center_lat.get('degrees')
                        if field.geometry.name == 'lambert':
                            if field.geometry.secant_projection:
                                std_parallel = [field.geometry.projection['secant_lat1'].get('degrees'),
                                                field.geometry.projection['secant_lat2'].get('degrees')]
                                latitude_of_projection_origin = (std_parallel[0] + std_parallel[1]) / 2.
                            else:
                                std_parallel = field.geometry.projection['reference_lat'].get('degrees')
                                latitude_of_projection_origin = std_parallel
                            xc, yc = field.geometry.ll2xy(_lon_cen, _lat_cen)
                            x0, y0 = field.geometry.ll2xy(field.geometry.projection['reference_lon'].get('degrees'),
                                                          latitude_of_projection_origin)
                            (dx, dy) = (xc - x0, yc - y0)
                            if not nearlyEqual(_lon_cen,
                                               field.geometry.projection['reference_lon'].get('degrees')):
                                epylog.warning('center_lon != reference_lon (tilting) is not "on the cards" in CF convention 1.6')
                            if not nearlyEqual(_lat_cen,
                                               field.geometry.projection['reference_lat'].get('degrees')):
                                epylog.warning('center_lat != reference_lat is not "on the cards" in CF convention 1.6')
                            self._variables[meta].longitude_of_central_meridian = field.geometry.projection['reference_lon'].get('degrees')
                            self._variables[meta].latitude_of_projection_origin = latitude_of_projection_origin
                            self._variables[meta].standard_parallel = std_parallel
                            self._variables[meta].false_easting = -dx
                            self._variables[meta].false_northing = -dy
                        elif field.geometry.name == 'mercator':
                            if field.geometry.secant_projection:
                                std_parallel = field.geometry.projection['secant_lat'].get('degrees')
                            else:
                                std_parallel = field.geometry.projection['reference_lat'].get('degrees')
                            xc, yc = field.geometry.ll2xy(_lon_cen, _lat_cen)
                            x0, y0 = field.geometry.ll2xy(field.geometry.projection['reference_lon'].get('degrees'), 0.)
                            (dx, dy) = (xc - x0, yc - y0)
                            self._variables[meta].longitude_of_central_meridian = field.geometry.projection['reference_lon'].get('degrees')
                            self._variables[meta].standard_parallel = std_parallel
                            self._variables[meta].false_easting = -dx
                            self._variables[meta].false_northing = -dy
                        elif field.geometry.name == 'polar_stereographic':
                            if field.geometry.secant_projection:
                                std_parallel = field.geometry.projection['secant_lat'].get('degrees')
                            else:
                                std_parallel = field.geometry.projection['reference_lat'].get('degrees')
                            xc, yc = field.geometry.ll2xy(_lon_cen, _lat_cen)
                            x0, y0 = field.geometry.ll2xy(field.geometry.projection['reference_lon'].get('degrees'),
                                                          field.geometry.projection['reference_lat'].get('degrees'))
                            (dx, dy) = (xc - x0, yc - y0)
                            self._variables[meta].straight_vertical_longitude_from_pole = field.geometry.projection['reference_lon'].get('degrees')
                            self._variables[meta].latitude_of_projection_origin = field.geometry.projection['reference_lat'].get('degrees')
                            self._variables[meta].standard_parallel = std_parallel
                            self._variables[meta].false_easting = -dx
                            self._variables[meta].false_northing = -dy
                    else:
                        epylog.info('assume projection parameters match.')
                else:
                    raise NotImplementedError('field.geometry.name == ' + field.geometry.name)
            else:
                meta = False
        else:
            meta = False

        # 4. Variable
        varname = field.fid['netCDF'].replace('.', config.netCDF_replace_dot_in_variable_names)
        _, _status = check_or_add_variable(varname, vartype, dims,
                                           zlib=bool(compression),
                                           complevel=compression,
                                           fill_value=fill_value)
        if meta:
            self._variables[varname].grid_mapping = meta
        if field.geometry.vcoordinate.typeoffirstfixedsurface in (118, 119):
            self._variables[varname].vertical_grid = zgridname
        data = field.getdata(d4=True)
        if isinstance(data, numpy.ma.masked_array):
            if 'gauss' in field.geometry.name:
                data = field.geometry.fill_maskedvalues(data)
            else:
                data = data.filled(fill_value)
        if self.behaviour.get('flatten_horizontal_grids'):
            data = field.geometry.horizontally_flattened(data)
        data = data.squeeze()
        if _status == 'match':
            epylog.info('overwrite data in variable ' + varname)
        self._variables[varname][...] = data

        # 5. metadata
        for k, v in metadata.items():
            self._nc.setncattr(k, v)

    def behave(self, **kwargs):
        """
        Set-up the given arguments in self.behaviour, for the purpose of
        building fields from netCDF.
        """

        self.behaviour.update(kwargs)

    def what(self, out=sys.stdout):
        """Writes in file a summary of the contents of the GRIB."""

        # adapted from http://schubert.atmos.colostate.edu/~cslocum/netcdf_example.html
        def ncdump(nc, out):
            '''
            ncdump outputs dimensions, variables and their attribute information.
            The information is similar to that of NCAR's ncdump utility.
            ncdump requires a valid instance of Dataset.
        
            Parameters
            ----------
            nc : netCDF4.Dataset
                A netCDF4 dateset object
            verb : Boolean
                whether or not nc_attrs, nc_dims, and nc_vars are printed
        
            Returns
            -------
            nc_attrs : list
                A Python list of the NetCDF file global attributes
            nc_dims : list
                A Python list of the NetCDF file dimensions
            nc_vars : list
                A Python list of the NetCDF file variables
            '''

            def outwrite(*items):
                items = list(items)
                stritem = items.pop(0)
                for i in items:
                    stritem += ' ' + str(i)
                out.write(stritem + '\n')

            def print_ncattr(key):
                """
                Prints the NetCDF file attributes for a given key
        
                Parameters
                ----------
                key : unicode
                    a valid netCDF4.Dataset.variables key
                """
                try:
                    outwrite("\t\ttype:", repr(nc.variables[key].dtype))
                    for ncattr in nc.variables[key].ncattrs():
                        outwrite('\t\t%s:' % ncattr, \
                                 repr(nc.variables[key].getncattr(ncattr)))
                except KeyError:
                    outwrite("\t\tWARNING: %s does not contain variable attributes" % key)

            # NetCDF global attributes
            nc_attrs = nc.ncattrs()
            outwrite("NetCDF Global Attributes:")
            for nc_attr in nc_attrs:
                outwrite('\t%s:' % nc_attr, repr(nc.getncattr(nc_attr)))
            nc_dims = [dim for dim in nc.dimensions]  # list of nc dimensions
            # Dimension shape information.
            outwrite("NetCDF dimension information:")
            for dim in nc_dims:
                outwrite("\tName:", dim)
                outwrite("\t\tsize:", len(nc.dimensions[dim]))
                # print_ncattr(dim)
            # Variable information.
            nc_vars = [var for var in nc.variables]  # list of nc variables
            outwrite("NetCDF variable information:")
            for var in nc_vars:
                outwrite('\tName:', var)
                outwrite("\t\tdimensions:", nc.variables[var].dimensions)
                outwrite("\t\tsize:", nc.variables[var].size)
                print_ncattr(var)
            return nc_attrs, nc_dims, nc_vars

        out.write("### FORMAT: " + self.format + "\n")
        out.write("\n")
        ncdump(self._nc, out)

    @property
    @FileResource._openbeforedelayed
    def _dimensions(self):
        return self._nc.dimensions

    @property
    @FileResource._openbeforedelayed
    def _variables(self):
        return self._nc.variables

