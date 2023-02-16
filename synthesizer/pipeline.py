#!/usr/bin/env python3

import os
import sys
import random
import requests
import subprocess
import numpy as np
from glob import glob
from pathlib import Path
import astropy.units as u
import matplotlib.pyplot as plt
from astropy.io import ascii, fits
from scipy.interpolate import griddata

from synthesizer import utils
from synthesizer import synobs
from synthesizer import gridder
from synthesizer import dustmixer


class Pipeline:
    
    def __init__(self, lam=1300, amax=10, nphot=1e5, nthreads=1, sootline=300,
            lmin=0.1, lmax=1e5, nlam=200, star=None, dgrowth=False, csubl=0, 
            material='sg', polarization=False, alignment=False, overwrite=False, verbose=True):
        self.steps = []
        self.lam = int(lam)
        self.lmin = lmin
        self.lmax = lmax
        self.nlam = nlam
        self.lgrid = np.logspace(np.log10(lmin), np.log10(lmax), nlam)
        self.amax = str(int(amax))
        self.material = material
        self.nphot = int(nphot)
        self.nthreads = int(nthreads)
        self.polarization = polarization
        self.alignment = alignment
        if polarization:
            self.scatmode = 5
            self.inputstyle = 10
        else:
            self.scatmode = 2
            self.inputstyle = 1

        if alignment:
            self.scatmode = 4
            self.inputstyle = 20
            self.polarization = True
    
        self.csubl = csubl
        self.nspec = 1 if self.csubl == 0 else 2
        self.dcomp = [material]*2 if self.csubl == 0 else [material, material+'o']
        self.sootline = sootline
        self.dgrowth = dgrowth
        self.opacfile = 'dustkapscatmat_' if self.polarization else 'dustkappa_' 
        self.k_ext = None
        if star is None:
            self.xstar = 0
            self.ystar = 0
            self.zstar = 0
            self.rstar = 2e11
            self.mstar = 3e22
            self.tstar = 4000        
        else:
            self.xstar = star[0]
            self.ystar = star[1]
            self.zstar = star[2]
            self.rstar = star[3]
            self.mstar = star[4]
            self.tstar = star[5]

        self.npix = None
        self.incl = None
        self.sizeau = None
        self.overwrite = overwrite
        self.verbose = verbose

    @utils.elapsed_time
    def create_grid(self, model=None, sphfile=None, amrfile=None, 
            source='sphng-bin', bbox=None, rout=None, ncells=None, 
            vector_field=None, show_2d=False, show_3d=False, vtk=False, 
            render=False, g2d=100, temperature=True):
        """ Initial step in the pipeline: creates an input grid for RADMC3D """

        self.model = model
        self.sphfile = sphfile
        self.amrfile = amrfile
        self.ncells = ncells
        self.bbox = bbox
        self.rout = rout
        self.g2d = g2d

        # Create a grid instance
        print('')
        utils.print_('Creating model grid ...\n', bold=True)
    
        if model is not None:
            self.grid = gridder.AnalyticalModel(
                model=self.model,
                bbox=self.bbox, 
                ncells=self.ncells, 
                g2d=self.g2d,
                nspec=self.nspec,
                temp=temperature, 
            )
            
            # Create a model density grid 
            self.grid.create_model()

        elif sphfile is not None:
            self.grid = gridder.CartesianGrid(
                ncells=self.ncells, 
                bbox=self.bbox, 
                rout=self.rout,
                csubl=self.csubl, 
                nspec=self.nspec, 
                sootline=self.sootline, 
                g2d=self.g2d, 
                temp=temperature,
            )

            # Read the SPH data
            self.grid.read_sph(self.sphfile, source=source)

            # Set a bounding box to trim the new grid
            if self.bbox is not None:
                self.grid.trim_box(bbox=self.bbox * u.au.to(u.cm))

            # Set a radius at which to trim the new grid
            if self.rout is not None:
                self.grid.trim_box(rout=self.rout * u.au.to(u.cm))
    
            # Interpolate the SPH points onto a regular cartesian grid
            self.grid.interpolate_points('dens', 'linear', fill='min')

            if temperature:
                self.grid.interpolate_points('temp', 'linear', fill='min')

        elif amrfile is not None:
            self.grid = gridder.CartesianGrid(
                ncells=self.ncells, 
                bbox=self.bbox, 
                rout=self.rout,
                csubl=self.csubl, 
                nspec=self.nspec, 
                sootline=self.sootline, 
                g2d=self.g2d, 
                temp=temperature,
            )
            
            # Read the AMR data
            self.grid.read_amr(self.amrfile, source=source)

        # Write the new cartesian grid to radmc3d file format
        self.grid.write_grid_file()

        # Write the dust density distribution to radmc3d file format
        self.grid.write_density_file()
        
        if temperature:
            # Write the dust temperature distribution to radmc3d file format
            self.grid.write_temperature_file()

        if vector_field is not None:
            self.grid.write_vector_field(morphology=vector_field)

        # Plot the density midplane
        if show_2d:
            self.grid.plot_dens_midplane()

        # Plot the temperature midplane
        if show_2d and temperature:
            self.grid.plot_temp_midplane()

        # Render the density volume in 3D using Mayavi
        if show_3d:
            self.grid.plot_dens_3d()

        # Render the temperature volume in 3D using Mayavi
        if show_3d and temperature:
            self.grid.plot_temp_3d()
        
        # Call RADMC3D to read the grid file and generate a VTK representation
        if vtk:
            self.grid.create_vtk(dust_density=False, dust_temperature=True, rename=True)
        
        # Visualize the VTK grid file using ParaView
        if render:
            self.grid.render()

        # Register the pipeline step 
        self.steps.append('create_grid')


    @utils.elapsed_time
    def dust_opacity(self, amin, amax, na, q=-3.5, nang=3, material=None, 
            show_nk=False, show_opac=False, savefig=None):
        """
            Call dustmixer to generate dust opacity tables. 
            New dust materials can be manually defined here if desired.
        """

        print('')
        utils.print_("Calculating dust opacities ...\n", bold=True)

        if material is not None: self.material = material
        self.amin = amin
        self.amax = amax
        self.na = na
        self.q = q 
        self.a_dist = np.logspace(np.log10(amin), np.log10(amax), na)
        if self.polarization and nang < 181:
            self.nang = 181
        else:
            self.nang = nang

        # Use 1 until the parallelization of polarization is properly implemented
        nth = self.nthreads if not self.polarization else 1

        repo = 'https://raw.githubusercontent.com/jzamponi/utils/main/' +\
                f'opacity_tables/'
        
        if self.material == 's':
            mix = dustmixer.Dust(name='Silicate')
            mix.set_lgrid(self.lmin, self.lmax, self.nlam)
            mix.set_nk(f'{repo}/astrosil-Draine2003.lnk', skip=1, get_dens=True)
            mix.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
        
        elif self.material == 'g':
            mix = dustmixer.Dust(name='Graphite')
            mix.set_lgrid(self.lmin, self.lmax, self.nlam)
            mix.set_nk(f'{repo}/c-gra-Draine2003.lnk', skip=1, get_dens=True)
            mix.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)

        elif self.material == 'p':
            mix = dustmixer.Dust(name='Pyroxene')
            mix.set_lgrid(self.lmin, self.lmax, self.nlam)
            mix.set_nk(f'{repo}/pyr-mg70-Dorschner1995.lnk', get_dens=False)
            mix.set_density(3.01, cgs=True)
            mix.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
        
        elif self.material == 'o':
            mix = dustmixer.Dust(name='Organics')
            mix.set_lgrid(self.lmin, self.lmax, self.nlam)
            mix.set_nk(f'{repo}/organics-Pollack1995.nk', meters=True, skip=1, 
                get_dens=True)
            mix.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
        
        elif self.material == 'sg':
            sil = dustmixer.Dust(name='Silicate')
            gra = dustmixer.Dust(name='Graphite')
            sil.set_lgrid(self.lmin, self.lmax, self.nlam)
            gra.set_lgrid(self.lmin, self.lmax, self.nlam)
            sil.set_nk(f'{repo}/astrosil-Draine2003.lnk', skip=1, get_dens=True)
            gra.set_nk(f'{repo}/c-gra-Draine2003.lnk', skip=1, get_dens=True)
            sil.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
            gra.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)

            # Sum the opacities weighted by their mass fractions
            mix = sil * 0.625 + gra * 0.375

        elif self.material == 'sgo':
            sil = dustmixer.Dust(name='Silicate')
            gra = dustmixer.Dust(name='Graphite')
            org = dustmixer.Dust(name='Organics')
            sil.set_lgrid(self.lmin, self.lmax, self.nlam)
            gra.set_lgrid(self.lmin, self.lmax, self.nlam)
            org.set_lgrid(self.lmin, self.lmax, self.nlam)
            sil.set_nk(f'{repo}/astrosil-Draine2003.lnk', skip=1, get_dens=True)
            gra.set_nk(f'{repo}/c-gra-Draine2003.lnk', skip=1, get_dens=True)
            gra.set_nk(f'{repo}/organics-Pollack1995.lnk', meters=True, skip=1,
                 get_dens=True)
            sil.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
            gra.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
            org.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)

            # Sum the opacities weighted by their mass fractions
            mix = sil * 0.625 + gra * 0.375

        else:
            try:
                mix = dustmixer.Dust(self.material.split('/')[-1].split('.')[0])
                mix.set_lgrid(self.lmin, self.lmax, self.nlam)
                mix.set_nk(path=self.material, skip=1, get_dens=True)
                mix.get_opacities(a=self.a_dist, nang=self.nang, nproc=nth)
                self.material = mix.name

            except Exception as e:
                utils.print_(e, red=True)
                raise ValueError(f'Material = {material} not found.')

        if show_nk or savefig is not None:
            mix.plot_nk(show=show_nk, savefig=savefig)

        if show_opac or savefig is not None:
            mix.plot_opacities(show=show_opac, savefig=savefig)

        # Write the opacity table
        mix.write_opacity_file(scatmat=self.polarization, 
            name=f'{self.material}-a{int(self.amax)}um')

        # Write the alignment efficiencies
        if self.alignment:
            mix.write_align_factor(f'{self.material}-a{int(self.amax)}um')

        # Register the pipeline step 
        self.steps.append('dustmixer')
    
    def generate_input_files(self, mc=False, inpfile=False, wavelength=False, 
            stars=False, dustopac=False, dustkappa=False, dustkapalignfact=False,
            grainalign=False):
        """ Generate the necessary input files for radmc3d """

        if inpfile:
            # Create a RADMC3D input file
            with open('radmc3d.inp', 'w+') as f:
                f.write(f'incl_dust = 1\n')
                f.write(f'istar_sphere = 0\n')
                f.write(f'modified_random_walk = 1\n')
                f.write(f'setthreads = {self.nthreads}\n')
                f.write(f'nphot = {int(self.nphot)}\n')
                f.write(f'nphot_scat = {int(self.nphot)}\n')
                f.write(f'iseed = {random.randint(-1e4, 1e4)}\n')
                f.write(f'scattering_mode = {self.scatmode}\n')
                if self.alignment and not mc: 
                    f.write(f'alignment_mode = 1\n')

        if wavelength: 
            # Create a wavelength grid in micron
            with open('wavelength_micron.inp', 'w+') as f:
                f.write(f'{self.lgrid.size}\n')
                for wav in self.lgrid:
                    f.write(f'{wav:13.6}\n')

        if stars:
            # Create a stellar spectrum file
            with open('stars.inp', 'w+') as f:
                f.write('2\n')
                f.write(f'1 {self.lgrid.size}\n')
                f.write(f'{self.rstar} {self.mstar} ')
                f.write(f'{self.xstar} {self.ystar} {self.zstar}\n')
                for wav in self.lgrid:
                    f.write(f'{wav:13.6}\n')
                f.write(f'{-self.tstar}\n')

        if dustopac:
            # Create a dust opacity file
            self.amax = int(self.amax)
            with open('dustopac.inp', 'w+') as f:
                f.write('2\n')
                f.write(f'{self.nspec}\n')
                f.write('---------\n')
                f.write(f'{self.inputstyle}\n')
                f.write('0\n')
                f.write(f'{self._get_opac_file_name()}\n')

                if self.nspec > 1:
                    # Define a second species 
                    f.write('---------\n')
                    f.write(f'{self.inputstyle}\n')
                    f.write('0\n')
                    f.write(f'{self._get_opac_file_name()}\n')
                f.write('---------\n')

        if dustkappa:

            # Fetch the corresponding opacity table from a public repo
            table = 'https://raw.githubusercontent.com/jzamponi/utils/main/' +\
                f'opacity_tables/dustkappa_{self.dcomp[0]}-a{self.amax}um.inp'

            utils.download_file(table)

            if self.csubl > 0:
                # Download also the table for a second dust composition
                table = table.replace(f'{self.dcomp[0]}', f'{self.dcomp[1]}')
                if 'sgo' in table:
                    table = table.replace('um.inp', f'um-{int(self.csubl)}org.inp')

                if self.dgrowth:
                    # Download also the table for grown dust
                    table = table.replace(f'{self.amax}', '1000') 

                utils.download_file(table)

        if dustkapalignfact:
            # To do: convert the graphite_oblate.dat and silicate_oblate.dat 
            # from the polaris repo, into a radmc3d format. Then upload the
            # radmc3d table to my github repo and download it from here
            
            raise ImportError(f'{utils.color.red}There is no ' +\
                f'dustkapalignfact_*.inp file. Run synthesizer again with ' +\
                f'the option --opacity --alignment.{utils.color.none}')

        if grainalign:
            raise ImportError(f'{utils.color.red}There is no ' +\
                f'grainalign_dir.inp file. Run synthesizer again adding ' +\
                f'--vector-field to --grid to create the alignment field ' +\
                f'from the input model.{utils.color.none}')

    @utils.elapsed_time
    def monte_carlo(self, nphot, radmc3d_cmds=''):
        """ 
            Call radmc3d to calculate the radiative temperature distribution 
        """

        print('')
        utils.print_("Running a thermal Monte Carlo ...", bold=True)
        self.nphot = nphot

        # Generate only the input files that are not available in the directory
        if not os.path.exists('radmc3d.inp') or self.overwrite:
            self.generate_input_files(inpfile=True, mc=True)

        if not os.path.exists('wavelength_micron.inp') or self.overwrite:
            self.generate_input_files(wavelength=True)

        if not os.path.exists('stars.inp') or self.overwrite:
            self.generate_input_files(stars=True)

        # Write a new dustopac file only if dustmixer was used or if unexistent
        if not os.path.exists('dustopac.inp') or \
            'dustmixer' in self.steps or self.overwrite:
            self.generate_input_files(dustopac=True)

        # If opacites were calculated within the pipeline, don't overwrite them
        if 'dustmixer' not in self.steps:
            # If not manually provided, download it from the repo
            if not self.polarization:
                if len(glob('dustkappa*')) == 0 or self.overwrite:
                    try:
                        self.generate_input_files(dustkappa=True)
                    except Exception as e:
                        utils.print_(
                            f'Unable to download opacity table. I will call ' +\
                            'dustmixer, as in synthesizer --opacity using '+\
                            'default values.', blue=True)

                        self.dust = self.dust_opacity(amin=0.1, amax=self.amax, 
                            na=100, q=3.5, nang=181, material=self.material)
            else:
                utils.print_(
                    f'Unable to download opacity table. I will call ' +\
                    'dustmixer, as in synthesizer --opacity using default ' +\
                    'values.', blue=True)

                self.dust = self.dust_opacity(amin=0.1, amax=self.amax,  
                    na=100, q=3.5, nang=181, material=self.material)
                

        # Call RADMC3D and pipe the output also to radmc3d.out
        try:
            utils.print_(f'Executing command: radmc3d mctherm {radmc3d_cmds}')
            self._radmc3d_banner()
            os.system(
                f'radmc3d mctherm {radmc3d_cmds} 2>&1 | tee -a radmc3d.out')

        except KeyboardInterrupt:
            raise Exception('Received SIGKILL. Execution halted by user.')

        self._radmc3d_banner()
        
        self._catch_radmc3d_error()

        # Register the pipeline step 
        self.steps.append('monte_carlo')

    @utils.elapsed_time
    def raytrace(self, lam=None, incl=None, npix=None, sizeau=None, show=True, 
            distance=141, tau=False, tau_surf=None, show_tau_surf=False, 
            noscat=True, fitsfile='radmc3d_I.fits', radmc3d_cmds=''):
        """ 
            Call radmc3d to raytrace the newly created grid and plot an image 
        """

        print('')
        utils.print_("Ray-tracing the model density and temperature ...\n", 
            bold=True)

        self.distance = distance
        self.tau = tau
        self.tau_surf = tau_surf

        if lam is not None:
            self.lam = lam
        if npix is not None:
            self.npix = npix
        if sizeau is not None:
            self.sizeau = sizeau
        if incl is not None:
            self.incl = incl

        # Explicitly the model rotate by 180.
        # Only for the current model. This line should be later removed.
        self.incl = 180 - int(self.incl)

        # To do: What's the diff. between passing noscat and setting scatmode=0
        if noscat: self.scatmode = 0

        # Generate only the input files that are not available in the directory
        if not os.path.exists('radmc3d.inp') or self.overwrite:
            self.generate_input_files(inpfile=True)

        if not os.path.exists('wavelength_micron.inp') or self.overwrite:
            self.generate_input_files(wavelength=True)

        if not os.path.exists('stars.inp') or self.overwrite:
            self.generate_input_files(stars=True)

        # Write a new dustopac file only if dustmixer was used or if unexistent
        if not os.path.exists('dustopac.inp') or \
            'dustmixer' in self.steps or self.overwrite:
            self.generate_input_files(dustopac=True)

        # If opacites were calculated within the pipeline, don't overwrite them
        if 'dustmixer' not in self.steps:
            # If not manually provided, download it from the repo
            if not self.polarization:
                if len(glob('dustkappa*')) == 0 or self.overwrite:
                    try:
                        self.generate_input_files(dustkappa=True)
                    except Exception as e:
                        utils.print_(
                            f'Unable to download opacity table. I will call ' +\
                            'dustmixer, as in synthesizer --opacity.', bold=True
                        )
                        Pipeline.dust_opacity(amin=0.1, amax=self.amax, na=100,  
                            q=3.5, nang=181, material=self.material)
                        

        # If align factors were calculated within the pipeline, don't overwrite
        if self.alignment:
            if 'dustmixer' not in self.steps:
                # If not manually provided, download it from the repo
                if len(glob('dustkapalignfact*')) == 0:
                    self.generate_input_files(dustkapalignfact=True)

            if not os.path.exists('grainalign_dir.inp'):
                self.generate_input_files(grainalign=True)

        # Now double check that all necessary input files are available 
        utils.file_exists('amr_grid.inp')
        utils.file_exists('dust_density.inp')
        utils.file_exists('dust_temperature.dat')
        utils.file_exists('radmc3d.inp')
        utils.file_exists('wavelength_micron.inp')
        utils.file_exists('stars.inp')
        utils.file_exists('dustopac.inp')
        utils.file_exists('dustkapscat*' if self.polarization else 'dustkappa*')
        if self.alignment: 
            utils.file_exists('dustkapalignfact*')
            utils.file_exists('grainalign_dir.inp')

        # Generate a 2D optical depth map
        if self.tau:
            self._plot_tau(show)
            
        # Set the RADMC3D command by concatenating options
        cmd = f'radmc3d image '
        cmd += f'lambda {self.lam} '
        cmd += f'incl {self.incl} ' if self.incl is not None else ' '
        cmd += f'npix {self.npix} ' if self.npix is not None else ' '
        cmd += f'sizeau {self.sizeau} ' if self.sizeau is not None else ' '
        cmd += f'stokes ' if self.polarization else ' '
        cmd += f'{" ".join(radmc3d_cmds)} '
        

        # Call RADMC3D and pipe the output also to radmc3d.out
        try:
            utils.print_(f'Executing command: {cmd}')
            self._radmc3d_banner()
            os.system(f'{cmd} 2>&1 | tee --append radmc3d.out')

        except KeyboardInterrupt:
            raise Exception('Received SIGKILL. Execution halted by user.')

        self._radmc3d_banner()
        
        self._catch_radmc3d_error()
    
        # Generate FITS files from the image.out
        utils.radmc3d_casafits(fitsfile, stokes='I', dpc=distance)

        if self.polarization:
            utils.radmc3d_casafits('radmc3d_Q.fits', stokes='Q', dpc=distance)
            utils.radmc3d_casafits('radmc3d_U.fits', stokes='U', dpc=distance)

        # Plot the new image in Jy/pixel
        if show:
            self.plot_rt()

        # Generate a 3D surface at tau = tau_surf
        if self.tau_surf is not None:
            try:
                utils.print_(
                    'Generating tau surface at tau = {self.tau_surf}')
                os.system(f'radmc3d tausurf {self.tau_surf} ' +\
                f'lambda {self.lam} noscat '
                f'npix {self.npix} ' if self.npix is not None else ' ' +\
                f'sizeau {self.sizeau} ' if self.sizeau is not None else ' '+\
                f'incl {self.incl} ' if self.incl is not None else ' ')

                os.rename('image.out', 'tauimage.out')
            except Exception as e:
                utils.print_(f'Unable to generate tau surface.\n{e}\n', red=True)

        # Render the 3D surface in 
        if show_tau_surf:
            utils.not_implemented()
            from mayavi import mlab
            utils.file_exists('tausurface_3d.out')

        # Register the pipeline step 
        self.steps.append('raytrace')

    @utils.elapsed_time
    def synthetic_observation(self, show=False, cleanup=True, 
            script=None, simobserve=True, clean=True, exportfits=True, 
            obstime=1, resolution=None, obsmode='int', graphic=True, 
            telescope=None, verbose=False):
        """ 
            Prepare the input for the CASA simulator from the RADMC3D output,
            and call CASA to run a synthetic observation.
        """

        print('')
        utils.print_('Running synthetic observation ...\n', bold=True)

        # If the observing wavelength is outside the working range of CASA, 
        # simplify the synthetic obs. to a PSF convolution and thermal noise
        if self.lam > 400 or self.lam < 4500:
    
            if resolution is not None:
                self.resolution = resolution
            else:
                utils.print_(
                    '--resolution has not been set. I will use 0.1"', blue=True)
                self.resolution = 0.1

            img = synobs.SynImage('radmc3d_I.fits')
            img.convolve(self.resolution)
            img.add_noise(obstime, bandwidth=8*u.GHz.to(u.Hz))
            img.write_fits('synobs_I.fits')

            if self.polarization:
                img_q = synobs.SynImage('radmc3d_Q.fits')
                img_u = synobs.SynImage('radmc3d_U.fits')
                img_q.convolve(self.resolution)
                img_u.convolve(self.resolution)
                img_q.add_noise(obstime, bandwidth=8*u.GHz.to(u.Hz))
                img_u.add_noise(obstime, bandwidth=8*u.GHz.to(u.Hz))
                img_q.write_fits('synobs_Q.fits')
                img_u.write_fits('synobs_U.fits')

        else:
            if script is None:
                # Create a minimal template CASA script
                script = synobs.CasaScript(lam=self.lam)
                script.polarization = self.polarization
                script.simobserve = simobserve
                script.clean = clean
                script.graphic = graphic
                script.overwrite = self.overwrite
                script.resolution = resolution
                script.obsmode = obsmode
                script.telescope = telescope
                if self.npix is not None: script.npix = int(self.npix + 20)
                script.totaltime = f'{obstime}h'
                script.verbose = False
                script.write('casa_script.py')

            elif 'http' in script: 
                # Download the script if a URL is provided
                url = script
                utils.download_file(url)
                script = synobs.CasaScript()
                script.name = script.split('/')[-1]
                script.read(script.name)

            self.script = script

            # Call CASA
            script.run()

            # Clean-up and remove unnecessary files created by CASA 
            if not simobserve or not tclean or not exportfits:
                script.cleanup()

        # Show the new synthetic image
        if show:
            self.plot_synobs()

        # Register the pipeline step 
        self.steps.append('synobs')



    def plot_rt(self):
        utils.print_('Plotting image.out')

        try:
            if self.alignment:
                utils.print_(f'Rotating vectors by 90 deg.')

            if self.polarization:
                fig = utils.polarization_map(
                    source='radmc3d',
                    render='I', 
                    rotate=90 if self.alignment else 0, 
                    step=15, 
                    scale=10, 
                    min_pfrac=0, 
                    const_pfrac=True, 
                    vector_color='white',
                    vector_width=1, 
                    verbose=False,
                    block=True, 
                )
            else:
                fig = utils.plot_map(
                    filename='radmc3d_I.fits', 
                    bright_temp=False,
                    verbose=False,
                )
        except Exception as e:
            utils.print_(
                f'Unable to plot radmc3d image.\n{e}', bold=True)
    
    def plot_synobs(self):
        utils.print_(f'Plotting the new synthetic image')

        try:
            utils.file_exists('synobs_I.fits')
            utils.fix_header_axes('synobs_I.fits')
                
            if self.polarization:
                utils.file_exists('synobs_Q.fits')
                utils.file_exists('synobs_U.fits')
                utils.fix_header_axes('synobs_Q.fits')
                utils.fix_header_axes('synobs_U.fits')

                fig = utils.polarization_map(
                    source='obs', 
                    render='I', 
                    stokes_I='synobs_I.fits', 
                    stokes_Q='synobs_Q.fits', 
                    stokes_U='synobs_U.fits', 
                    rotate=0, 
                    step=15, 
                    scale=10, 
                    const_pfrac=True, 
                    vector_color='white',
                    vector_width=1, 
                    verbose=True,
                )
            else:
                fig = utils.plot_map(
                    filename='synobs_I.fits',
                    bright_temp=False,
                    verbose=False,
                )
        except Exception as e:
            utils.print_(
                f'Unable to plot synobs_I.fits:\n{e}', bold=True)

    def plot_tau(self, show=False):
        utils.print_(f'Generating optical depth map at {self.lam} microns')
        utils.file_exists('dust_density.inp')
        utils.file_exists('amr_grid.inp')
        rho = np.loadtxt('dust_density.inp', skiprows=3)
        amr = np.loadtxt('amr_grid.inp', skiprows=6)
        dl = np.diff(amr)[0]
        nx = int(np.cbrt(rho.size))
        rho = rho.reshape((nx, nx, nx))
        tau2d = np.sum(rho * self._get_opacity() * dl, axis=0).T
        if show:
            plt.rcParams['font.family'] = 'Times New Roman'
            plt.rcParams['xtick.direction'] = 'in'
            plt.rcParams['ytick.direction'] = 'in'
            plt.rcParams['xtick.top'] = True
            plt.rcParams['ytick.right'] = True
            plt.rcParams['xtick.minor.visible'] = True
            plt.rcParams['ytick.minor.visible'] = True
            plt.title(fr'Optical depth at $\lambda = ${self.lam}$\mu$m')
            plt.imshow(tau2d, origin='lower')
            plt.yticks([])
            plt.xticks([])
            plt.colorbar()
            plt.show()

        utils.write_fits('tau.fits', data=tau2d, overwrite=True)

    def _get_opac_file_name(self):
        """ Get the name of the currently used opacity file dustk*.inp """

        if self.csubl > 0:
            ext = f'{self.dcomp[1]}-a{self.amax}um-{int(self.csubl)}org'
        else:
            ext = f'{self.material}-a{self.amax}um'

        if self.dgrowth:
            ext = f'{self.dcomp[0]}-a1000um'
        else:
            ext = f'{self.dcomp[0]}-a{self.amax}um'

        self.opacfile = self.opacfile + ext + '.inp'
        return ext 
    
    def _get_opacity(self):
        """ Read in an opacity file, interpolate and find the opacity at lambda """
        from scipy.interpolate import interp2d

        # Generate the opacfile string and make sure file exists
        self._get_opac_file_name()

        if not utils.file_exists(self.opacfile, raise_=False): 
            utils.print_(
                f"I couldn't obtain the opacity from {self.opacfile}. " +\
                "I will calculate tau using k_ext = 1 g/cm3.", bold=True)
            return 1

        header = np.loadtxt(self.opacfile, max_rows=2)
        iformat = header[0]
        nlam = header[1]
        skip = 3 if 'kapscat' in opacfile else 2
        d = ascii.read(self.opacfile, data_start=skip, data_end=nlam + skip)
        l = d['col1']
        self.k_abs = d['col2']
        if iformat > 1: 
            self.k_sca = d['col3']
            self.k_ext = self.k_abs + self.k_sca
        else:
            self.k_ext = self.k_abs

        return interp1d(l, self.k_ext)(self.lam)

    def _radmc3d_banner(self):
        print(f'{utils.color.blue}{"="*31}  <RADMC3D>  {"="*31}{utils.color.none}')

    def _catch_radmc3d_error(self):
        """ Raise an exception to halt synthesizer if RADMC3D ended in Error """

        # Read radmc3d.out and stop the pipeline if RADMC3D finished in error
        utils.file_exists('radmc3d.out')
        with open ('radmc3d.out', 'r') as out:
            for line in out.readlines():
                if 'error' in line.lower() or 'stop' in line.lower():
                    raise Exception(
                        f'{utils.color.red}\r[RADMC3D] {line}{utils.color.none}')
