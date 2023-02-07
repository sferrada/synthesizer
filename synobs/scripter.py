import re
import numpy as np
import astropy.units as u
import astropy.constants as c
from synthesizer import utils

class CasaScript():
    
    def __init__(self, lam, name='casa_script.py'):
        self.name = name
        self.lam = lam
        self.freq = c.c.cgs.value / (lam * u.micron.to(u.cm))
        self.simobserve = True
        self.clean = True
        self.exportfits = True
        self.graphics = 'both'
        self.overwrite = True
        self.polarization = True
        self.project = ""
        self.fitsI = 'radmc3d_I.fits'
        self.fitsQ = 'radmc3d_Q.fits'
        self.fitsU = 'radmc3d_U.fits'

    
    def write(self, name=None):
        """ Write a CASA script using the CasaScript parameters """

        if name is not None: self.name = name

        stokes = ['I', 'Q', 'U'] if self.polarization else ['I']
    
        with open(self.name, 'w+') as f:
            f.write('# Template CASA script to simulate observations. \n')
            f.write('# Written by Synthesizer. \n\n')

            for q in stokes:
                f.write(f'print("\033[1m\\n[alma_simulation] ')
                f.write(f'Observing Stokes {q} ...\033[0m\\n")\n')
                if self.simobserve:
                    f.write(f'simobserve( \n')
                    f.write(f'    project = {self.project}, \n')
                    f.write(f'    skymodel = "radmc3d_{q}.fits", \n')
                    f.write(f'    inbright = {self.inbright}, \n')
                    f.write(f'    incell = {self.incell}, \n')
                    f.write(f'    incenter = "{self.freq}Hz", \n')
                    f.write(f'    mapsize = {self.mapsize}, \n')
                    f.write(f'    setpointings = {self.setpointings}, \n')
                    f.write(f'    indirection = {self.indirection}, \n')
                    f.write(f'    integration = {self.integration}, \n')
                    f.write(f'    totaltime = {self.totaltime}, \n')
                    f.write(f'    hourangle = {self.hourangle}, \n')
                    f.write(f'    obsmode = {self.obsmode}, \n')
                    f.write(f'    antennalist = {self.arrayconfig}, \n')
                    f.write(f'    thermalnoise = {self.thermalnoise}, \n')
                    f.write(f'    graphics = {self.graphics}, \n')
                    f.write(f'    overwrite = {self.overwrite}, \n')
                    f.write(f'    verbose = {self.verbose}, \n')
                    f.write(f') \n')
            
                if self.clean:
                    f.write(f'tclean( \n')
                    f.write(f'    vis = {self.vis}, \n')
                    f.write(f'    imagename = {self.imagename}, \n')
                    f.write(f'    imsize = {self.imsize}, \n')
                    f.write(f'    cell = {self.cell}, \n')
                    f.write(f'    specmode = {self.specmode}, \n')
                    f.write(f'    gridder = {self.gridder}, \n')
                    f.write(f'    deconvolver = {self.deconvolver}, \n')
                    f.write(f'    scales = {self.scales}, \n')
                    f.write(f'    weighting = {self.weighting}, \n')
                    f.write(f'    robust = {self.robust}, \n')
                    f.write(f'    niter = {self.niter}, \n')
                    f.write(f'    threshold = {self.threshold}, \n')
                    f.write(f'    mask = {self.mask}, \n')
                    f.write(f'    interactive = {self.interactive}, \n')
                    f.write(f'    verbose = {self.verbose}, \n')
                    f.write(f') \n')

                if self.exportfits:
                    f.write(f'exportfits( \n')
                    f.write(f'    imagename = {self.imagename}, \n')
                    f.write(f'    fitsimage = {self.fitsimage}, \n')
                    f.write(f'    dropstokes = {self.dropstokes}, \n')
                    f.write(f'    overwrite = {self.overwrite}, \n')
                    f.write(f') \n\n')
                

    def read(self, name):
        """ Read variables and parameters from an already existing file """

        # Raise an error if file doesn't exist, including wildcards
        utils.file_exists(name)

        f = open(name, 'r')

        # Make sure at least simobserve or tclean are defined within the script
#        for line in f.readlines():
#            if re.search('simobserve', line) or re.search('tclean', line):
#                pass
#            else:
#                raise ValueError(f'{name} is not a valid CASA script. Either '+\
#                    'simobserve() or tclean() function calls must be given')
        def strip_line(l):
            l = l.split('=')[1]
            l = l.strip('\n')
            l = l.strip(',')
            l = l.strip()
            l = l.strip(',')
            if ',' in l and not '[' in l: l = l.split(',')[0]
            return l

        for line in f.readlines():
            # Simobserve
            if 'project' in line: self.project = strip_line(line)
            if 'skymodel' in line: self.skymodel = strip_line(line)
            if 'inbright' in line: self.inbright = strip_line(line)
            if 'incell' in line: self.incell = strip_line(line)
            if 'mapsize' in line: self.mapsize = strip_line(line)
            if 'incenter' in line: self.incenter = strip_line(line)
            if 'inwidth' in line: self.inwidth = strip_line(line)
            if 'setpointings' in line: self.setpointings = strip_line(line)
            if 'integration' in line: self.integration = strip_line(line)
            if 'totaltime' in line: self.totaltime = strip_line(line)
            if 'indirection' in line: self.indirection = strip_line(line)
            if 'hourangle' in line: self.hourangle = strip_line(line)
            if 'obsmode' in line: self.obsmode = strip_line(line)
            if 'antennalist' in line: self.arrayconfig = strip_line(line)
            if 'thermalnoise' in line: self.thermalnoise = strip_line(line)
            if 'graphics' in line: self.graphics = strip_line(line)
            if 'overwrite' in line: self.overwrite = strip_line(line)
            if 'verbose' in line: self.verbose = strip_line(line)
    
            # tclean
            if 'vis' in line: self.vis = strip_line(line)
            if 'imagename' in line: self.imagename = strip_line(line)
            if 'imsize' in line: self.imsize = strip_line(line)
            if 'cell' in line: self.cell = strip_line(line)
            if 'specmode' in line: self.specmode = strip_line(line)
            if 'gridder' in line: self.gridder = strip_line(line)
            if 'deconvolver' in line: self.deconvolver = strip_line(line)
            if 'scales' in line: self.scales = strip_line(line)
            if 'weighting' in line: self.weighting = strip_line(line)
            if 'robust' in line: self.robust = strip_line(line)
            if 'niter' in line: self.niter = strip_line(line)
            if 'threshold' in line: self.threshold = strip_line(line)
            if 'mask' in line: self.mask = strip_line(line)
            if 'interactive' in line: self.interactive = strip_line(line)

            # Exportfits
            if 'fitsimage' in line: self.fitsimage = strip_line(line)
            if 'dropstokes' in line: self.dropstokes = strip_line(line)

        f.close()

    def clean_projects(self):
        """ Delete any previous project to avoid the CASA clashing """

        if self.overwrite and len(glob('band*')) > 0:
            projs = [i for i in glob("band*")]
            utils.print_(f'Deleting previous observation project(s): {projs}')
            subprocess.run('rm -r band*', shell=True)

    def run(self):
        """ Run the ALMA/JVLA simulation script """

        subprocess.run(f'casa -c {self.name} --nologger'.split())