#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) Météo France (2014-)
# This software is governed by the CeCILL-C license under French law.
# http://www.cecill.info
"""
Contains the class for a Horizontal 2D field.

Plus a function to create a Vector field from 2 scalar fields.
"""

from __future__ import print_function, absolute_import, unicode_literals, division

import numpy
import sys

from footprints import proxy as fpx, FPList
from bronx.graphics.axes import set_figax
from bronx.syntax.arrays import stretch_array

from epygram import config, epygramError, util, epylog
from epygram.base import Field, FieldValidityList
from . import H2DField


def make_vector_field(fX, fY):
    """
    Creates a new :class:`epygram.H2DVectorField` from two
    :class:`epygram.H2DField` *fX, fY* representing resp.
    the X and Y components of the vector in the field geometry.
    """
    if not isinstance(fX, H2DField) or not isinstance(fY, H2DField):
        raise epygramError("'fX', 'fY' must be H2DField.")
    if fX.geometry.dimensions != fY.geometry.dimensions:
        raise epygramError("'fX', 'fY' must be share their gridpoint" +
                           " dimensions.")
    if fX.spectral_geometry != fY.spectral_geometry:
        raise epygramError("'fX', 'fY' must be share their spectral" +
                           " geometry.")
    if fX.structure != fY.structure:
        raise epygramError("'fX', 'fY' must share their structure.")

    f = fpx.field(fid={'op':'make_vector()'},
                  structure=fX.structure,
                  validity=fX.validity.copy(),
                  processtype=fX.processtype,
                  vector=True,
                  components=[fX, fY])
    return f


def psikhi2uv(psi, khi):
    """
    Compute wind (on the grid) as a H2DVectorField from streamfunction
    **psi** and velocity potential **khi**.
    """
    (dpsidx, dpsidy) = psi.compute_xy_spderivatives()
    (dkhidx, dkhidy) = khi.compute_xy_spderivatives()
    u = dkhidx - dpsidy
    v = dkhidy + dpsidx
    u.fid = {'derivative':'u-wind'}
    v.fid = {'derivative':'v-wind'}
    u.validity = psi.validity
    v.validity = psi.validity
    return make_vector_field(u, v)


class H2DVectorField(Field):
    """
    Horizontal 2-Dimensions Vector field class.

    This is a wrapper to a list of H2DField(s), representing the components
    of a vector projected on its geometry (the grid axes).
    """

    _collector = ('field',)
    _footprint = dict(
        attr=dict(
            structure=dict(
                info="Type of Field geometry.",
                values=set(['H2D'])),
            vector=dict(
                info="Intrinsic vectorial nature of the field.",
                type=bool,
                values=set([True])),
            validity=dict(
                info="Validity of the field.",
                type=FieldValidityList,
                optional=True,
                access='rwx',
                default=FieldValidityList()),
            components=dict(
                info="List of Fields that each compose a component of the vector.",
                type=FPList,
                optional=True,
                default=FPList([])),
            processtype=dict(
                optional=True,
                info="Generating process.")
        )
    )

##############
# ABOUT DATA #
##############

    @property
    def spectral_geometry(self):
        return self.components[0].spectral_geometry

    @property
    def spectral(self):
        """Returns True if the field is spectral."""
        return self.spectral_geometry is not None

    @property
    def geometry(self):
        return self.components[0].geometry

    def attach_components(self, *components):
        """
        Attach components of the vector to the VectorField.
        *components* must be a series of H2DField.
        """
        for f in components:
            if not isinstance(f, H2DField):
                raise epygramError("*components* must be H2DField(s).")
        for f in components:
            self.components.append(f)

    def sp2gp(self):
        """
        Transforms the spectral field into gridpoint, according to its spectral
        geometry. Replaces data in place.

        The spectral transform subroutine is actually included in the spectral
        geometry's *sp2gp()* method.
        """
        for f in self.components:
            f.sp2gp()

    def gp2sp(self, spectral_geometry=None):
        """
        Transforms the gridpoint field into spectral space, according to the
        *spectral_geometry* mandatorily passed as argument. Replaces data in
        place.

        :param spectral_geometry: instance of SpectralGeometry, actually
                                  containing spectral transform subroutine (in
                                  in its own *gp2sp()* method).
        """
        for f in self.components:
            f.gp2sp(spectral_geometry=spectral_geometry)

    def getdata(self, subzone=None, **kwargs):
        """
        Returns the field data, with 2D shape if the field is not spectral,
        1D if spectral, as a tuple with data for each component.

        :param subzone: optional, among ('C', 'CI'), for LAM fields only, returns
          the data resp. on the C or C+I zone.
          Default is no subzone, i.e. the whole field.

        Shape of 2D data: (x (0) being the X component, y (1) the Y one) \n
        - Rectangular grids:\n
          grid[0,0,x] is SW, grid[-1,-1,x] is NE \n
          grid[0,-1,x] is SE, grid[-1,0,x] is NW
        - Gauss grids:\n
          grid[0,:Nj,x] is first (Northern) band of latitude, masked
          after Nj = number of longitudes for latitude j \n
          grid[-1,:Nj,x] is last (Southern) band of latitude (idem).
        """
        return [f.getdata(subzone=subzone, **kwargs) for f in self.components]

    def setdata(self, data):
        """
        Sets data to its components.

        :param data: [data_i for i components]
        """
        if len(data) != len(self.components):
            raise epygramError("data must have as many components as VectorField.")
        for i in range(len(self.components)):
            self.components[i].setdata(data[i])

    def deldata(self):
        """Empties the data."""
        for i in range(len(self.components)):
            self.components[i].deldata()

    data = property(getdata, setdata, deldata, "Accessor to the field data.")

    def to_module(self):
        """
        Returns a :class:`epygram.H2DField` whose data is the module of the
        Vector field.
        """
        if self.spectral:
            fieldcopy = self.deepcopy()
            fieldcopy.sp2gp()
            datagp = fieldcopy.getdata(d4=True)
        else:
            datagp = self.getdata(d4=True)
        if isinstance(datagp[0], numpy.ma.MaskedArray):
            loc_sqrt = numpy.ma.sqrt
        else:
            loc_sqrt = numpy.sqrt
        module = loc_sqrt(datagp[0] ** 2 + datagp[1] ** 2)
        f = fpx.field(geometry=self.geometry.copy(),
                      structure=self.structure,
                      fid={'op':'H2DVectorField.to_module()'},
                      validity=self.validity.copy(),
                      processtype=self.processtype)
        f.setdata(module)
        if self.spectral:
            f.gp2sp(self.spectral_geometry)

        return f

    def compute_direction(self):
        """
        Returns a :class:`epygram.H2DField` whose data is the direction of the
        Vector field, in degrees.
        """
        if self.spectral:
            fieldcopy = self.deepcopy()
            fieldcopy.sp2gp()
            datagp = fieldcopy.getdata()
        else:
            datagp = self.getdata()
        if isinstance(datagp[0], numpy.ma.MaskedArray):
            loc_sqrt = numpy.ma.sqrt
            loc_arccos = numpy.ma.arccos
        else:
            loc_sqrt = numpy.sqrt
            loc_arccos = numpy.arccos
        module = loc_sqrt(datagp[0] ** 2 + datagp[1] ** 2)
        module_cal = numpy.where(module < 1.E-15, 1.E-15, module)
        u_norm = -datagp[0] / module_cal
        v_norm = -datagp[1] / module_cal
        numpy.clip(v_norm, -1, 1, out=v_norm)
        dd1 = loc_arccos(v_norm)
        dd2 = 2. * numpy.pi - dd1
        direction = numpy.degrees(numpy.where(u_norm >= 0., dd1, dd2))
        f = fpx.field(geometry=self.geometry.copy(),
                      structure=self.structure,
                      fid={'op':'H2DVectorField.compute_direction()'},
                      validity=self.validity.copy(),
                      processtype=self.processtype)
        f.setdata(direction)
        if self.spectral:
            f.gp2sp(self.spectral_geometry)

        return f

    def reproject_wind_on_lonlat(self,
                                 map_factor_correction=True,
                                 reverse=False):
        """
        Reprojects a wind vector (u, v) from the grid axes onto real
        sphere, i.e. with components on true zonal/meridian axes.

        :param map_factor_correction: if True, apply a correction of magnitude
                                      due to map factor.
        :param reverse: if True, apply the reverse reprojection.
        """
        (lon, lat) = self.geometry.get_lonlat_grid()
        assert not self.spectral
        u = self.components[0].getdata()
        v = self.components[1].getdata()
        if self.geometry.name == 'rotated_reduced_gauss':
            (u, v) = self.geometry.reproject_wind_on_lonlat(u.compressed(),
                                                            v.compressed(),
                                                            lon.compressed(),
                                                            lat.compressed(),
                                                            map_factor_correction=map_factor_correction,
                                                            reverse=reverse)
            u = self.geometry.reshape_data(u, first_dimension='T')
            v = self.geometry.reshape_data(v, first_dimension='T')
        else:
            (u, v) = self.geometry.reproject_wind_on_lonlat(u, v, lon, lat,
                                                            map_factor_correction=map_factor_correction,
                                                            reverse=reverse)
        self.setdata([u, v])

    def map_factorize(self, reverse=False):
        """
        Multiply the field by its map factor.

        :param reverse: if True, divide.
        """
        if self.spectral:
            spgeom = self.spectral_geometry
            self.sp2gp()
            was_spectral = True
        else:
            was_spectral = False
        m = self.geometry.map_factor_field()
        if reverse:
            op = '/'
        else:
            op = '*'
        self.components[0].operation_with_other(op, m)
        self.components[1].operation_with_other(op, m)
        if was_spectral:
            self.gp2sp(spgeom)

    def compute_vordiv(self, divide_by_m=False):
        """
        Compute vorticity and divergence fields from the vector field.

        :param divide_by_m: if True, apply f = f/m beforehand, where m is the
                            map factor.
        """
        if divide_by_m:
            field = self.deepcopy()
            field.map_factorize(reverse=True)
        else:
            field = self
        (dudx, dudy) = field.components[0].compute_xy_spderivatives()
        (dvdx, dvdy) = field.components[1].compute_xy_spderivatives()
        vor = dvdx - dudy
        div = dudx + dvdy
        vor.fid = {'derivative':'vorticity'}
        div.fid = {'derivative':'divergence'}
        vor.validity = dudx.validity
        div.validity = dudx.validity

        return (vor, div)

    def extract_subdomain(self, *args, **kwargs):
        """Cf. D3Field.extract_subdomain()"""
        return make_vector_field(self.components[0].extract_subdomain(*args, **kwargs),
                                 self.components[1].extract_subdomain(*args, **kwargs))

    def extract_zoom(self, *args, **kwargs):
        """Cf. D3Field.extract_zoom()"""
        return make_vector_field(self.components[0].extract_zoom(*args, **kwargs),
                                 self.components[1].extract_zoom(*args, **kwargs))

    def extract_subarray(self, *args, **kwargs):
        """Cf. D3Field.extract_subarray()"""
        return make_vector_field(self.components[0].extract_subarray(*args, **kwargs),
                                 self.components[1].extract_subarray(*args, **kwargs))

    def resample(self, *args, **kwargs):
        """Cf. D3Field.resample()"""
        return make_vector_field(self.components[0].resample(*args, **kwargs),
                                 self.components[1].resample(*args, **kwargs))

    def resample_on_regularll(self, *args, **kwargs):
        """Cf. D3Field.resample_on_regularll()"""
        return make_vector_field(self.components[0].resample_on_regularll(*args, **kwargs),
                                 self.components[1].resample_on_regularll(*args, **kwargs))

###################
# PRE-APPLICATIVE #
###################
# (but useful and rather standard) !
# [so that, subject to continuation through updated versions,
#  including suggestions/developments by users...]

    def plotfield(self,
                  over=(None, None),
                  subzone=None,
                  title=None,
                  gisquality='i',
                  specificproj=None,
                  zoom=None,
                  use_basemap=None,
                  drawcoastlines=True,
                  drawcountries=True,
                  drawrivers=False,
                  departments=False,
                  boundariescolor='0.25',
                  parallels='auto',
                  meridians='auto',
                  subsampling=1,
                  symbol='barbs',
                  symbol_options={'color':'k', },
                  plot_module=True,
                  plot_module_options=None,
                  bluemarble=0.,
                  background=False,
                  quiverkey=None,
                  quiver_options=None,
                  components_are_projected_on='grid',
                  map_factor_correction=True,
                  mask_threshold=None,
                  figsize=None):
        """
        Makes a simple plot of the field, with a number of options.

        :param over: to plot the vectors over an existing figure
          (e.g. colorshades).
          Any existing figure and/or ax to be used for the
          plot, given as a tuple (fig, ax), with None for
          missing objects. *fig* is the frame of the
          matplotlib figure, containing eventually several
          subplots (axes); *ax* is the matplotlib axes on
          which the drawing is done. When given (is not None),
          these objects must be coherent, i.e. ax being one of
          the fig axes.
        :param subzone: among ('C', 'CI'), for LAM fields only, plots the data
          resp. on the C or C+I zone. \n
          Default is no subzone, i.e. the whole field.
        :param gisquality: among ('c', 'l', 'i', 'h', 'f') -- by increasing
          quality. Defines the quality for GIS elements (coastlines, countries
          boundaries...). Default is 'i'. Cf. 'basemap' doc for more details.
        :param specificproj: enables to make basemap on the specified projection,
          among: 'kav7', 'cyl', 'ortho', ('nsper', {...}) (cf. Basemap doc). \n
          In 'nsper' case, the {} may contain:\n
          - 'sat_height' = satellite height in km;
          - 'lon' = longitude of nadir in degrees;
          - 'lat' = latitude of nadir in degrees. \n
          Overwritten by *zoom*.
        :param zoom: specifies the lon/lat borders of the map, implying hereby
          a 'cyl' projection.
          Must be a dict(lonmin=, lonmax=, latmin=, latmax=).\n
          Overwrites *specificproj*.
        :param use_basemap: a basemap.Basemap object used to handle the
          projection of the map. If given, the map projection
          options (*specificproj*, *zoom*, *gisquality* ...)
          are ignored, keeping the properties of the
          *use_basemap* object. (because making Basemap is the most
          time-consuming step).
        :param drawrivers: to add rivers on map.
        :param departments: if True, adds the french departments on map (instead
          of countries).
        :param boundariescolor: color of lines for boundaries (countries,
          departments, coastlines)
        :param drawcoastlines: to add coast lines on map.
        :param drawcountries: to add countries on map.
        :param title: title for the plot. Default is field identifier.
        :param meridians: enable to fine-tune the choice of lines to
          plot, with either:\n
          - 'auto': automatic scaling to the basemap extents
          - 'default': range(0,360,10)
          - a list of values
          - a grid step, e.g. 5 to plot each 5 degree.
          - None: no one is plot
          - *meridian* == 'greenwich' // 'datechange' // 'greenwich+datechange'
            combination (,) will plot only these.
        :param parallels: enable to fine-tune the choice of lines to
          plot, with either:\n
          - 'auto': automatic scaling to the basemap extents
          - 'default': range(-90,90,10)
          - a list of values
          - a grid step, e.g. 5 to plot each 5 degree.
          - None: no one is plot
          - 'equator' // 'polarcircles' // 'tropics' or any
            combination (,) will plot only these.
        :param subsampling: to subsample the number of gridpoints to plot.
          Ex: *subsampling* = 10 will only plot one gridpoint upon 10.
        :param symbol: among ('barbs', 'arrows', 'stream')
        :param symbol_options: a dict of options to be passed to **barbs** or
          **quiver** method.
        :param plot_module: to plot module as colorshades behind vectors.
        :param plot_module_options: options (dict) to be passed to module.plotfield().
        :param bluemarble: if > 0.0 (and <=1.0), displays NASA's "blue marble"
          as background. The numerical value sets its transparency.
        :param background: if True, set a background color to
          continents and oceans.
        :param quiverkey: to activate quiverkey; must contain arguments to be
          passed to pyplot.quiverkey(), as a dict.
        :param components_are_projected_on: inform the plot on which axes the
          vector components are projected on ('grid' or 'lonlat').
        :param map_factor_correction: if True, applies a correction of magnitude
          to vector due to map factor.
        :param mask_threshold: dict with min and/or max value(s) to mask outside.
        :param figsize: figure sizes in inches, e.g. (5, 8.5).
                        Default figsize is config.plotsizes.

        This method uses (hence requires) 'matplotlib' and 'basemap' libraries.
        """
        import matplotlib.pyplot as plt
        plt.rc('font', family='serif')
        if figsize is None:
            figsize = config.plotsizes

        plot_module_options = util.ifNone_emptydict(plot_module_options)
        quiver_options = util.ifNone_emptydict(quiver_options)

        if self.spectral:
            raise epygramError("please convert to gridpoint with sp2gp()" +
                               " method before plotting.")

        # 1. Figure, ax
        if not plot_module:
            fig, ax = set_figax(*over, figsize=figsize)

        # 2. Set up the map
        academic = self.geometry.name == 'academic'
        if (academic and use_basemap is not None):
            epylog.warning('*use_basemap* is ignored for academic geometries fields')
        if use_basemap is None and not academic:
            bm = self.geometry.make_basemap(gisquality=gisquality,
                                            subzone=subzone,
                                            specificproj=specificproj,
                                            zoom=zoom)
        elif use_basemap is not None:
            bm = use_basemap
        elif academic:
            raise NotImplementedError('plot VectorField in academic geometry')
            bm = None
        if not academic:
            if plot_module:
                module = self.to_module()
                if 'gauss' in self.geometry.name and self.geometry.grid['dilatation_coef'] != 1.:
                    if map_factor_correction:
                        module.operation_with_other('*', self.geometry.map_factor_field())
                    else:
                        epylog.warning('check carefully *map_factor_correction* w.r.t. dilatation_coef')
                fig, ax = module.plotfield(use_basemap=bm,
                                           over=over,
                                           subzone=subzone,
                                           specificproj=specificproj,
                                           title=title,
                                           drawrivers=drawrivers,
                                           drawcoastlines=drawcoastlines,
                                           drawcountries=drawcountries,
                                           meridians=meridians,
                                           parallels=parallels,
                                           departments=departments,
                                           boundariescolor=boundariescolor,
                                           bluemarble=bluemarble,
                                           background=background,
                                           **plot_module_options)
            else:
                util.set_map_up(bm, ax,
                                drawrivers=drawrivers,
                                drawcoastlines=drawcoastlines,
                                drawcountries=drawcountries,
                                meridians=meridians,
                                parallels=parallels,
                                departments=departments,
                                boundariescolor=boundariescolor,
                                bluemarble=bluemarble,
                                background=background)
        # 3. Prepare data
        # mask values
        mask_outside = {'min':-config.mask_outside,
                        'max':config.mask_outside}
        if mask_threshold is not None:
            mask_outside.update(mask_threshold)
        data = [numpy.ma.masked_outside(data,
                                        mask_outside['min'],
                                        mask_outside['max']) for data in
                self.getdata(subzone=subzone)]
        if data[0].ndim == 1:  # self.geometry.dimensions['Y'] == 1:
            u = data[0][::subsampling]
            v = data[1][::subsampling]
        else:
            u = data[0][::subsampling, ::subsampling]
            v = data[1][::subsampling, ::subsampling]
        (lons, lats) = self.geometry.get_lonlat_grid(subzone=subzone)
        if lons.ndim == 1:  # self.geometry.dimensions['Y'] == 1:
            lons = lons[::subsampling]
            lats = lats[::subsampling]
        else:
            lons = lons[::subsampling, ::subsampling]
            lats = lats[::subsampling, ::subsampling]
        if isinstance(u, numpy.ma.masked_array) \
        or isinstance(v, numpy.ma.masked_array):
            assert isinstance(u, numpy.ma.masked_array) == isinstance(u, numpy.ma.masked_array)
            common_mask = u.mask + v.mask
            u.mask = common_mask
            v.mask = common_mask
            lons = numpy.ma.masked_where(common_mask, lons)
            lats = numpy.ma.masked_where(common_mask, lats)
        x, y = bm(lons, lats)

        # Calculate the orientation of the vectors
        assert components_are_projected_on in ('grid', 'lonlat')
        if components_are_projected_on == 'grid' and 'gauss' not in self.geometry.name \
           and (specificproj is None and zoom is None):
            # map has same projection than components: no rotation necessary
            u_map = u
            v_map = v
        else:
            # (1or2) rotation(s) is(are) necessary
            if components_are_projected_on == 'lonlat' or self.geometry.name == 'regular_lonlat':
                (u_ll, v_ll) = (stretch_array(u), stretch_array(v))
            else:
                # wind is projected on a grid that is not lonlat: rotate to lonlat
                (u_ll, v_ll) = self.geometry.reproject_wind_on_lonlat(stretch_array(u), stretch_array(v),
                                                                      stretch_array(lons), stretch_array(lats),
                                                                      map_factor_correction=map_factor_correction)
            # rotate from lonlat to map projection
            (u_map, v_map) = bm.rotate_vector(u_ll,
                                              v_ll,
                                              stretch_array(lons),
                                              stretch_array(lats))
            # go back to 2D if necessary
            if symbol == 'stream':
                u_map = u_map.reshape(u.shape)
                v_map = v_map.reshape(v.shape)

        if symbol == 'stream':
            if self.geometry.rectangular_grid:
                xf = x[0, :]  # in basemap space, x is constant on a column
                yf = y[:, 0]  # in basemap space, y is constant on a row
                u = u_map
                v = v_map
                speed_width = 2 * numpy.sqrt(u ** 2 + v ** 2) / min(u.max(), v.max())
            else:
                raise NotImplementedError("matplotlib's streamplot need an evenly spaced grid.")
        else:
                xf = stretch_array(x)
                yf = stretch_array(y)
                u = stretch_array(u_map)
                v = stretch_array(v_map)
        if symbol == 'barbs':
            bm.barbs(xf, yf, u, v, ax=ax, **symbol_options)
        elif symbol == 'arrows':
            q = bm.quiver(xf, yf, u, v, ax=ax, **symbol_options)
            if quiverkey:
                ax.quiverkey(q, **quiverkey)
        elif symbol == 'stream':
            bm.streamplot(xf, yf, u, v, ax=ax, linewidth=speed_width, **symbol_options)
        if title is None:
            ax.set_title(str(self.fid) + "\n" + str(self.validity.get()))
        else:
            ax.set_title(title)

        return (fig, ax)

    def plotanimation(self,
                      title='__auto__',
                      repeat=False,
                      interval=1000,
                      **kwargs):
        """
        Plot the field with animation with regards to time dimension.
        Returns a :class:`matplotlib.animation.FuncAnimation`.

        In addition to those specified below, all :meth:`plotfield` method
        arguments can be provided.

        :param title: title for the plot. '__auto__' (default) will print
          the current validity of the time frame.
        :param repeat: to repeat animation
        :param interval: number of milliseconds between two validities
        """
        import matplotlib.animation as animation

        if len(self.validity) == 1:
            raise epygramError("plotanimation can handle only field with several validities.")

        if title is not None:
            if title == '__auto__':
                title_prefix = ''
            else:
                title_prefix = title
            title = title_prefix + '\n' + self.validity[0].get().isoformat(sep=b' ')
        else:
            title_prefix = None
        field0 = self.deepcopy()
        for c in field0.components:
            c.validity = self.validity[0]
        field0.validity = field0.components[0].validity
        field0.setdata([d[0, ...] for d in self.getdata()])
        if kwargs.get('plot_module', True):
            module = self.to_module()
            mindata = module.getdata(subzone=kwargs.get('subzone')).min()
            maxdata = module.getdata(subzone=kwargs.get('subzone')).max()
            plot_module_options = kwargs.get('plot_module_options', {})
            if plot_module_options == {}:
                kwargs['plot_module_options'] = {}
            minmax = plot_module_options.get('minmax')
            if minmax is None:
                minmax = (mindata, maxdata)
            kwargs['plot_module_options']['minmax'] = minmax
        academic = self.geometry.name == 'academic'
        if not academic:
            bm = kwargs.get('use_basemap')
            if bm is None:
                bm = self.geometry.make_basemap(gisquality=kwargs.get('gisquality', 'i'),
                                                subzone=kwargs.get('subzone'),
                                                specificproj=kwargs.get('specificproj'),
                                                zoom=kwargs.get('zoom'))
            kwargs['use_basemap'] = bm
        fig, ax = field0.plotfield(title=title,
                                   **kwargs)
        if kwargs.get('plot_module', True):
            if kwargs['plot_module_options'].get('colorbar_over') is None:
                kwargs['plot_module_options']['colorbar_over'] = fig.axes[-1]  # the last being created, in plotfield()
        kwargs['over'] = (fig, ax)

        def update(i, ax, myself, fieldi, title_prefix, kwargs):
            if i < len(myself.validity):
                ax.clear()
                for c in fieldi.components:
                    c.validity = myself.validity[i]
                fieldi.validity = fieldi.components[0].validity
                fieldi.setdata([d[i, ...] for d in myself.getdata()])
                if title_prefix is not None:
                    title = title_prefix + '\n' + fieldi.validity.get().isoformat(sep=b' ')
                fieldi.plotfield(title=title,
                                 **kwargs)

        anim = animation.FuncAnimation(fig, update,
                                       fargs=[ax, self, field0, title_prefix, kwargs],
                                       frames=list(range(len(self.validity) + 1)),  # AM: don't really understand why but needed for the last frame to be shown
                                       interval=interval,
                                       repeat=repeat)

        return anim

    def getvalue_ij(self, *args, **kwargs):
        """
        Returns the value of the different components of the field from indexes.
        """
        return [f.getvalue_ij(*args, **kwargs) for f in self.components]

    def getvalue_ll(self, *args, **kwargs):
        """
        Returns the value of the different components of the field from coordinates.
        """
        return [f.getvalue_ll(*args, **kwargs) for f in self.components]

    def min(self, subzone=None):
        """Returns the minimum value of data."""
        return [f.min(subzone=subzone) for f in self.components]

    def max(self, subzone=None):
        """Returns the maximum value of data."""
        return [f.max(subzone=subzone) for f in self.components]

    def mean(self, subzone=None):
        """Returns the mean value of data."""
        return [f.mean(subzone=subzone) for f in self.components]

    def std(self, subzone=None):
        """Returns the standard deviation of data."""
        return [f.std(subzone=subzone) for f in self.components]

    def quadmean(self, subzone=None):
        """Returns the quadratic mean of data."""
        return [f.quadmean(subzone=subzone) for f in self.components]

    def nonzero(self, subzone=None):
        """
        Returns the number of non-zero values (whose absolute
        value > config.epsilon).
        """
        return [f.nonzero(subzone=subzone) for f in self.components]

    def global_shift_center(self, longitude_shift):
        """
        Shifts the center of the geometry (and the data accordingly) by
        *longitude_shift* (in degrees). *longitude_shift* has to be a multiple
        of the grid's resolution in longitude.

        For global RegLLGeometry grids only.
        """
        if self.geometry.name != 'regular_lonlat':
            raise epygramError("only for regular lonlat geometries.")
        for f in self.components:
            f.global_shift_center(longitude_shift)

    def what(self, out=sys.stdout,
             vertical_geometry=True,
             cumulativeduration=True):
        """
        Writes in file a summary of the field.

        :param out: the output open file-like object (duck-typing: *out*.write()
          only is needed).
        :param vertical_geometry: if True, writes the vertical geometry of the
          field.
        """
        for f in self.components:
            f.what(out,
                   vertical_geometry=vertical_geometry,
                   cumulativeduration=cumulativeduration)

#############
# OPERATORS #
#############

    def _check_operands(self, other):
        """
        Internal method to check compatibility of terms in operations on fields.
        """
        if 'vector' not in other._attributes:
            raise epygramError("cannot operate a Vector field with a" +
                               " non-Vector one.")
        else:
            if isinstance(other, self.__class__):
                if len(self.components) != len(other.components):
                    raise epygramError("vector fields must have the same" +
                                       " number of components.")
            super(H2DVectorField, self)._check_operands(other)

    def __add__(self, other):
        """
        Definition of addition, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'+'} and null validity.
        """
        if isinstance(other, self.__class__):
            newcomponents = [self.components[i] + other.components[i] for i in range(len(self.components))]
        else:
            newcomponents = [self.components[i] + other for i in range(len(self.components))]

        newid = {'op':'+'}
        newfield = fpx.field(fid=newid,
                             structure=self.structure,
                             validity=self.validity,
                             processtype=self.processtype,
                             vector=True,
                             components=newcomponents)

        return newfield

    def __mul__(self, other):
        """
        Definition of multiplication, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'*'} and null validity.
        """
        if isinstance(other, self.__class__):
            newcomponents = [self.components[i] * other.components[i] for i in range(len(self.components))]
        else:
            newcomponents = [self.components[i] * other for i in range(len(self.components))]
        newid = {'op':'*'}
        newfield = fpx.field(fid=newid,
                             structure=self.structure,
                             validity=self.validity,
                             processtype=self.processtype,
                             vector=True,
                             components=newcomponents)
        return newfield

    def __sub__(self, other):
        """
        Definition of substraction, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'-'} and null validity.
        """
        if isinstance(other, self.__class__):
            newcomponents = [self.components[i] - other.components[i] for i in range(len(self.components))]
        else:
            newcomponents = [self.components[i] - other for i in range(len(self.components))]
        newid = {'op':'-'}
        newfield = fpx.field(fid=newid,
                             structure=self.structure,
                             validity=self.validity,
                             processtype=self.processtype,
                             vector=True,
                             components=newcomponents)
        return newfield

    def __div__(self, other):
        """
        Definition of division, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'/'} and null validity.
        """
        if isinstance(other, self.__class__):
            newcomponents = [self.components[i] / other.components[i] for i in range(len(self.components))]
        else:
            newcomponents = [self.components[i] / other for i in range(len(self.components))]
        newid = {'op':'/'}
        newfield = fpx.field(fid=newid,
                             structure=self.structure,
                             validity=self.validity,
                             processtype=self.processtype,
                             vector=True,
                             components=newcomponents)
        return newfield

    __radd__ = __add__
    __rmul__ = __mul__

    def __rsub__(self, other):
        """
        Definition of substraction, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'-'} and null validity.
        """
        if isinstance(other, self.__class__):
            newcomponents = [other.components[i] - self.components[i] for i in range(len(self.components))]
        else:
            newcomponents = [other - self.components[i] for i in range(len(self.components))]
        newid = {'op':'-'}
        newfield = fpx.field(fid=newid,
                             structure=self.structure,
                             validity=self.validity,
                             processtype=self.processtype,
                             vector=True,
                             components=newcomponents)
        return newfield

    def __rdiv__(self, other):
        """
        Definition of division, 'other' being:
        - a scalar (integer/float)
        - another Field of the same subclass.
        Returns a new Field whose data is the resulting operation,
        with 'fid' = {'op':'/'} and null validity.
        """
        if isinstance(other, self.__class__):
            newcomponents = [other.components[i] / self.components[i] for i in range(len(self.components))]
        else:
            newcomponents = [other / self.components[i] for i in range(len(self.components))]
        newid = {'op':'/'}
        newfield = fpx.field(fid=newid,
                             structure=self.structure,
                             validity=self.validity,
                             processtype=self.processtype,
                             vector=True,
                             components=newcomponents)
        return newfield
