#!/usr/bin/env python
#!/opt/hoomd-0.11.3/hoomdblue-install/bin/hoomd
#!/Applications/HOOMD-blue.app/Contents/MacOS/hoomd

"""
NOTES

what you are looking for is described here:

http://codeblue.umich.edu/hoomd-blue/doc-master/classhoomd__script_1_1analyze_1_1log.html#a7077167865224233566753fc78aadb36

basically you want to do

#setup logger
logger=analyze.log(filename='mylog.log', quantities=['pair_lj_energy','pair_lj_energy','potential_energy','potential_energy_b1'],period=10, header_prefix='#')

#run simulation
run(100)

# query potential energy
pe_c1 = logger.query('potential_energy_b1')
pe = logger.query('potential_energy')

"""
import collections
import csv
import logging
import math
import os
import sys
import time
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

PARAM_SEP=','

# Needs to be defined here to avoid circular import in util.py
def read_bond_params(bond_file):
    if not os.path.isfile(bond_file): raise RuntimeError("Cannot find bond parameter file: {0}".format(bond_file))
    BondParams = collections.namedtuple('BondParams', ['A', 'B', 'k', 'r0', 'comments'])
    params = []
    for i, bp in enumerate(map(BondParams._make, csv.reader(open(bond_file, "r"), delimiter=PARAM_SEP, quotechar='"'))):
        if i == 0: # check header ok
            if bp.A != 'A' and bp.B != 'B' and bp.k != 'k' and bp.r0 != 'r0':
                raise RuntimeError("Incorrect header for bond param file: {0}".format(bond_file))
            continue
        params.append(bp)
    return params

from paths import PARAMS_DIR
import util
import hoomdblue

class FfieldParameters(object):

    def __init__(self):
        # All parameters calculated to fit PCFF adapted forcefield Holden et al j.phys.chem.c 2012
        # from combining rules calculated using dlpoly-prep (Willock)
        # bonds adapted from quartic PCFF
        self.bonds = self._processBonds(os.path.abspath(os.path.join(PARAMS_DIR, 'bond_params.csv')))
        self.angles = self._processAngles(os.path.abspath(os.path.join(PARAMS_DIR, 'angle_params.csv')))
        self.dihedrals = self._processDihedrals(os.path.abspath(os.path.join(PARAMS_DIR, 'dihedral_params.csv')))
        self.impropers = self._processImpropers(os.path.abspath(os.path.join(PARAMS_DIR, 'improper_params.csv')))
        self.pairs = self._readPairs(os.path.abspath(os.path.join(PARAMS_DIR, 'pair_params.csv')))
        return
    
    def _processBonds(self,bond_file):
        bond_params = read_bond_params(bond_file)
        if not len(bond_params): raise RuntimeError("Could not read any parameters from bond file: {0}".format(bond_file))
        bonds = {}
        for p in bond_params:
            try: 
                bonds[(p.A, p.B)] = {'k' : float(p.k), 'r0' : float(p.r0)}
            except Exception as e:
                logger.critical("Error reading angle parameters from file: {0}".format(bond_file))
                logger.critical("Error occured with parameter {0}".format(p))
                raise e
        return bonds
    
    def _processAngles(self, angle_file):
        # REM: angles are stored in degrees in the parameter file, but we convert to radians for our uses
        if not os.path.isfile(angle_file): raise RuntimeError, "Cannot find angle parameter file: {0}".format(angle_file)
        header = ['angle', 'k', 't0', 'comments']
        angles = {}
        with open(angle_file) as f:
            reader = csv.reader(f, delimiter=PARAM_SEP, quotechar='"')
            for i, row in enumerate(reader):
                if i == 0:
                    if row != header: raise RuntimeError, "Header for {0} file, should be: {1}".format(angle_file, ",".join(header))
                    else: continue
                try:
                    angle = row[0]
                    k = float(row[1])
                    t0 = math.radians(float(row[2]))
                    angles[angle] = {'k' : k, 't0' : t0}
                except Exception as e:
                    logger.critical("Error reading angle parameters from file: {0}".format(angle_file))
                    logger.critical("Error occured on line {0}: {1}".format(i+1,PARAM_SEP.join(row)))
                    raise e
        return angles

    def _processDihedrals(self, dihedral_file):
        if not os.path.isfile(dihedral_file): raise RuntimeError, "Cannot find dihedral parameter file: {0}".format(dihedral_file)
        header = ['dihedral', 'k', 'd', 'n', 'comments']
        dihedrals = {}
        with open(dihedral_file) as f:
            reader = csv.reader(f, delimiter=PARAM_SEP, quotechar='"')
            for i, row in enumerate(reader):
                if i == 0:
                    if row != header: raise RuntimeError, "Header for {0} file, should be: {1}".format(dihedral_file, ",".join(header))
                    else: continue
                if row[0].startswith('#'): continue
                try:
                    dihedral = row[0]
                    k = float(row[1])
                    d = int(row[2])
                    n = int(row[3])
                    dihedrals[dihedral] = {'k' : k, 'd' : d, 'n' : n}
                except Exception as e:
                    logger.critical("Error reading dihedral parameters from file: {0}".format(dihedral_file))
                    logger.critical("Error occured on line {0}: {1}".format(i+1,PARAM_SEP.join(row)))
                    raise e
        return dihedrals
    
    def _processImpropers(self,improper_file):
        if not os.path.isfile(improper_file): raise RuntimeError, "Cannot find dihedral parameter file: {0}".format(improper_file)
        header = ['improper', 'k', 'chi', 'comments']
        impropers = {}
        with open(improper_file) as f:
            reader = csv.reader(f, delimiter=PARAM_SEP, quotechar='"')
            for i, row in enumerate(reader):
                if i == 0:
                    if row != header: raise RuntimeError, "Header for {0} file, should be: {1}".format(improper_file, ",".join(header))
                    else: continue
                try:
                    improper = row[0]
                    k = float(row[1])
                    chi = float(row[2])
                    impropers[improper] = {'k' : k, 'chi' : chi}
                except Exception as e:
                    logger.critical("Error reading improper parameters from file: {0}".format(improper_file))
                    logger.critical("Error occured on line {0}: {1}".format(i+1,PARAM_SEP.join(row)))
                    raise e
        return impropers
    
    def _readPairs(self,pairs_file):
        if not os.path.isfile(pairs_file): raise RuntimeError, "Cannot find pair parameter file: {0}".format(pairs_file)
        header = ['atom1', 'atom2', 'epsilon', 'sigma', 'comments']
        pairs = {}
        with open(pairs_file) as f:
            reader = csv.reader(f, delimiter=PARAM_SEP, quotechar='"')
            for i, row in enumerate(reader):
                if i == 0:
                    if row != header: raise RuntimeError, "Header for {0} file, should be: {1}".format(pairs_file, ",".join(header))
                    else: continue
                try:
                    atom1 = row[0]
                    atom2 = row[1]
                    epsilon = float(row[2])
                    sigma = float(row[3])
                    pairs[(atom1, atom2)] = {'epsilon' : epsilon, 'sigma' : sigma}
                except Exception as e:
                    logger.critical("Error reading pair parameters from file: {0}".format(pairs_file))
                    logger.critical("Error occured on line {0}: {1}".format(i+1,PARAM_SEP.join(row)))
                    raise e
        return pairs
    
    def angleParameter(self, angle):
        return self.angles[ angle ]

    def hasAngle(self, angle):
        return angle in self.angles.keys()

    def bondParameter(self, bond):
        a, b = bond.split('-')
        if (a, b) in self.bonds.keys():
            return self.bonds[(a, b)]
        elif (b, a) in self.bonds.keys():
            return self.bonds[(b, a)]
        else:
            raise RuntimeError, "Missing bond parameter for: {0} {1}".format(a, b)

    def hasBond(self, bond):
        a, b = bond.split('-')
        return (a, b) in self.bonds.keys() or (b, a) in self.bonds.keys()

    def dihedralParameter(self, dihedral):
        return self.dihedrals[ dihedral ]

    def hasDihedral(self, dihedral):
        return dihedral in self.dihedrals.keys()

    def improperParameter(self, improper):
        return self.impropers[ improper ]

    def hasImproper(self, improper):
        return improper in self.impropers.keys()

    def pairParameter(self, p1, p2):
        """ Return whichever pair is defined """
        if (p1, p2) in self.pairs:
            return self.pairs[ (p1, p2) ]
        if (p2, p1) in self.pairs:
            return self.pairs[ (p2, p1) ]

        assert False, "Could not find {0} {1}".format(p1, p2)
        return

    def hasPair(self, p1, p2):
        """ dummy atoms treated specially """
        if p1.lower() == 'x' or p2.lower() == 'x':
            return True
        if self.pairs.has_key((p1, p2)) or self.pairs.has_key((p2, p1)):
            return True
        return False

class FFIELD(object):

    def __init__(self):
        self.ffield = FfieldParameters()
        self.bonds = None
        self.angles = None
        self.dihedrals = None
        self.impropers = None
        self.atomTypes = None
        return

    def checkParameters(self, skipDihedrals=False):

        assert self.ffield
        assert self.atomTypes

        ok = True
        missingBonds = []
        for bond in self.bonds:
            if not self.ffield.hasBond(bond):
                ok = False
                missingBonds.append(bond)
        missingAngles = []
        for angle in self.angles:
            if not self.ffield.hasAngle(angle):
                ok = False
                missingAngles.append(angle)
        missingDihedrals = []
        missingImpropers = []
        if not skipDihedrals:
            for dihedral in self.dihedrals:
                if not self.ffield.hasDihedral(dihedral):
                    ok = False
                    missingDihedrals.append(dihedral)
            for improper in self.impropers:
                if not self.ffield.hasImproper(improper):
                    ok = False
                    missingImpropers.append(improper)

        missingPairs = []
        for i, atype in enumerate(self.atomTypes):
            for j, btype in enumerate(self.atomTypes):
                if j >= i:
                    if not self.ffield.hasPair(atype, btype):
                        ok = False
                        missingPairs.append((atype, btype))

        if not ok:
            msg = "The following parameters could not be found:\n"
            if missingBonds:
                msg += "Bonds: {0}\n".format(missingBonds)
            if missingAngles:
                msg += "Angles: {0}\n".format(missingAngles)
            if missingDihedrals:
                msg += "Dihedrals: {0}\n".format(missingDihedrals)
            if missingImpropers:
                msg += "Impropers: {0}\n".format(missingImpropers)
            if missingPairs:
                msg += "Pairs: {0}\n".format(missingPairs)

            msg += "Please add these to the files in the directory: {0}\n".format(PARAMS_DIR)
            raise RuntimeError, msg
        return

class DLPOLY(FFIELD):
    """
    write out CONFIG file
    write out FIELD file
    """

    def _writeCONFIG(self,
                    cell,
                    types,
                    coords,
                    fileName="CONFIG",
                    ):
        """Write out DLPOLY CONFIG file

        DLPOLY assumes a centered cell.
        """

        with open(fileName, 'w') as f:

            # header
            f.write("Ambuild CONFIG file\n")

            levcfg = 0 # just coordinates
            # imcon 1=cubic bounduary conditions, 2=orthorhombic boundary conditions
            imcon = 1 if cell[0] == cell[1] == cell[2] else 2
            f.write("{0:>10}{1:>10}\n".format(levcfg, imcon))

            # Now cell
            f.write("{0: > 20.6F}{1: > 20.6F}{2: > 20.6F}\n".format(cell[0], 0.0, 0.0))
            f.write("{0: > 20.6F}{1: > 20.6F}{2: > 20.6F}\n".format(0.0, cell[1], 0.0))
            f.write("{0: > 20.6F}{1: > 20.6F}{2: > 20.6F}\n".format(0.0, 0.0, cell[2]))

            # Loop through coordinates
            count = 1  # FORTRAN COUNTING
            for i, coord in enumerate(coords):
                # Remove atom index so we can be used by earlier DL-POLY versions
                #f.write("{0}    {1}\n".format(types[i], count))
                f.write("{0}\n".format(types[i]))
                x, y, z = coord
                f.write("{0: > 20.6F}{1: > 20.6F}{2: > 20.6F}\n".format(x, y, z))
                count += 1
        return
    
    def writeCONTROL(self):
        txt = """simulation NPT
temperature           zero
pressure              0.001
ensemble npt hoover   0.1 1.0
steps                 3
equilibration         2
print                 1
stats                 1
timestep              1.00E-4
cutoff                10.0
delr width            2.00E-01
rvdw cutoff           10.0
ewald precision       1.0E-06
job time              1.0E+04
close time            1.0E+02
finish
"""
        with open('CONTROL', 'w') as w:
            w.write(txt)
        return

    def writeFIELDandCONFIG(self,
                   cell,
                   rigidBody=True,
                   periodic=True,
                   center=True,
                   skipDihedrals=False):
        """
        ALSO WRITES OUT CONFIG

        For each block
        count atoms & keep atomType list
        create list of bonds
        create list of angles
        create list of dihedrals
        create list of rigid body indices
        count

        """

        angles = []
        angleTypes = []
        bonds = []
        bondTypes = []
        propers = []
        properTypes = []
        impropers = []
        improperTypes = []

        types = []
        bonds = []
        bondTypes = []
        coords = []
        images = []
        charges = []
        diameters = []
        masses = []
        symbols = []
        bodies = []
        bodies2 = []
        frozen = []

        atomCount = 0  # Global count in cell
        bodyCount = -1
        for idxBlock, block in cell.blocks.iteritems():

            blockBonds = []
            blockBondTypes = []
            blockAngles = []
            blockAngleTypes = []
            blockPropers = []
            blockProperTypes = []
            blockImpropers = []
            blockImproperTypes = []

            # Do bonds first as counting starts from atomCount and goes up through the blocks
            # It turns out the counting is within a molecule, not global so need to fix.
            if not rigidBody:
                # add all bonds, angles and dihederals throughout the whole block
                # Add all bonds
                # blockBonds += [ (a1+atomCount, a2+atomCount) for a1, a2 in block.bonds() ]
                blockBonds += block.bonds()
                blockBondTypes += [ (block.type(a1), block.type(a2)) for a1, a2 in block.bonds() ]
                _angles, _propers, _impropers = block.anglesAndDihedrals()
                # Add all angles
                # blockAngles += [ (a1+atomCount, a2+atomCount, a3+atomCount) for a1, a2, a3 in _angles ]
                blockAngles += _angles
                blockAngleTypes += [ (block.type(a1), block.type(a2), block.type(a3)) for a1, a2, a3 in _angles ]
                # Add all propers
                # blockPropers += [ (a1+atomCount, a2+atomCount, a3+atomCount, a4+atomCount) \
                #                 for a1, a2, a3, a4 in _propers ]
                blockPropers += _propers
                blockProperTypes += [ (block.type(a1),
                                       block.type(a2),
                                       block.type(a3),
                                       block.type(a4)
                                       ) for a1, a2, a3, a4 in _propers ]
                # Add all impropers
                # blockImpropers += [ (a1+atomCount, a2+atomCount, a3+atomCount, a4+atomCount) \
                #                   for a1, a2, a3, a4 in _impropers ]
                blockImpropers += _impropers
                blockImproperTypes += [ (block.type(a1),
                                         block.type(a2),
                                         block.type(a3),
                                         block.type(a4)
                                         ) for a1, a2, a3, a4 in _impropers ]

            else:
                # Just add the bonds between blocks. Also add angles for all atoms connected to the bonds
                # we do this so that we can exclude them from VdW interactions in MD codes
                for b1, b2 in block.blockBonds():

                    # The bonds themselves
                    # blockBonds.append( (b1+atomCount,b2+atomCount) )
                    blockBonds.append((b1, b2))
                    blockBondTypes.append((block.type(b1), block.type(b2)))

                    _angles = set()
                    # Atoms connected to the endGroup that we need to specify as connected so we add as angles
                    for batom in block.atomBonded1(b1):
                        # The opposite endGroup is included in the list bonded to an endGroup so skip
                        if batom == b2:
                            continue
                        _angles.add((batom, b1, b2))

                    for batom in block.atomBonded1(b2):
                        # The opposite endGroup is included in the list bonded to an endGroup so skip
                        if batom == b1:
                            continue
                        _angles.add((b1, b2, batom))

                    # Add to overall lists
                    for a1, a2, a3 in _angles:
                        # blockAngles.append( (a1+atomCount, a2+atomCount, a3+atomCount))
                        blockAngles.append((a1, a2, a3))
                        blockAngleTypes.append((block.type(a1),
                                                  block.type(a2),
                                                  block.type(a3)))

                    #
                    # Dihedrals
                    #
                    # jmht CHECK PROPERS AND IMPROPERS
                    for dindices in block.dihedrals(b1, b2):
                        # dihedral = ( dindices[0] + atomCount,
                        #             dindices[1] + atomCount,
                        #             dindices[2] + atomCount,
                        #             dindices[3] + atomCount )
                        dihedral = (dindices[0], dindices[1], dindices[2], dindices[3])
                        blockPropers.append(dihedral)
                        blockProperTypes.append((block.type(dindices[0]),
                                                   block.type(dindices[1]),
                                                   block.type(dindices[2]),
                                                   block.type(dindices[3])
                                                ))

            blockTypes = []
            blockCoords = []
            blockImages = []
            blockCharges = []
            blockDiameters = []
            blockMasses = []
            blockSymbols = []
            blockBodies = []
            blockBodies2 = []
            blockFrozen = []

            # Now loop through fragments and coordinates
            if hasattr(block, '_fragments'):
                fragments = block._fragments
            else:
                fragments = block.fragments
            # for idxFrag,frag in enumerate(block.fragments): # need index of fragment in block
            molCount = 0
            for idxFrag, frag in enumerate(fragments):  # need index of fragment in block

                # Body count always increments with fragment although it may go up within a fragment too
                bodyCount += 1

                lastBody = frag.body(0)
                # bstart=atomCount
                bstart = molCount
                for i, coord in enumerate(frag.iterCoord()):
                    if periodic:
                        x, ix = util.wrapCoord(coord[0], cell.dim[0], center=center)
                        y, iy = util.wrapCoord(coord[1], cell.dim[1], center=center)
                        z, iz = util.wrapCoord(coord[2], cell.dim[2], center=center)
                        blockCoords.append([x, y, z])
                        blockImages.append([ix, iy, iz])
                    else:
                        blockCoords.append(coord)
                        blockImages.append([0, 0, 0])

                    blockTypes.append(frag.type(i))
                    blockCharges.append(frag.charge(i))
                    blockDiameters.append(0.1)
                    blockMasses.append(frag.mass(i))
                    blockSymbols.append(frag.symbol(i))

                    # Work out which body this is in
                    b = frag.body(i)
                    if b != lastBody:
                        bodyCount += 1
                        lastBody = b
                        # blockBodies2.append((bstart,atomCount))
                        # bstart=atomCount+1
                        blockBodies2.append((bstart, molCount))
                        bstart = molCount + 1
                    blockBodies.append(bodyCount)
                    if frag.static:
                        blockFrozen.append(1)
                    else:
                        blockFrozen.append(0)

                    # Increment global atom count
                    atomCount += 1  # NOT USED AS COUNTING IS INTER_MOLECULAR!
                    molCount += 1

                # Work out which fragment this is in
                # REM blockCount is NOT idxBlock in the dict - need to rationalise this.
                # d.tagIndices.append((idxBlock,idxFrag,atomCount-i,atomCount))
                # blockBodies2.append((bstart,atomCount))
                blockBodies2.append((bstart, molCount))

            # END loop through fragments

            # Now have all data pertaining to a particular block
            bonds.append(blockBonds)
            bondTypes.append(blockBondTypes)
            angles.append(blockAngles)
            angleTypes.append(blockAngleTypes)
            propers.append(blockPropers)
            properTypes.append(blockProperTypes)
            impropers.append(blockImpropers)
            improperTypes.append(blockImproperTypes)

            types.append(blockTypes)
            coords.append(blockCoords)
            images.append(blockImages)
            charges.append(blockCharges)
            diameters.append(blockDiameters)
            masses.append(blockMasses)
            symbols.append(blockSymbols)
            bodies.append(blockBodies)
            bodies2.append(blockBodies2)
            frozen.append(blockFrozen)

        # End block loop

        # First write out the CONFIG file
        # Unpack the coordinates and types from the blocks
        self._writeCONFIG(cell.dim, [j for i in types for j in i], [j for i in coords for j in i])

        # Quick hack hijacking hoomdblue machinary
        # Check we have all the parameters we need
        self.bonds = set([ "{0}-{1}".format(j[0], j[1]) for i in bondTypes for j in i ])
        self.angles = set([ "{0}-{1}-{2}".format(j[0], j[1], j[2]) for i in angleTypes for j in i ])
        self.dihedrals = set([ "{0}-{1}-{2}-{3}".format(j[0], j[1], j[2], j[3]) for i in properTypes for j in i ])
        self.impropers = set([ "{0}-{1}-{2}-{3}".format(j[0], j[1], j[2], j[3]) for i in improperTypes for j in i ])
        self.atomTypes = set([ j for i in types for j in i ])
        # Pierre wants us to write things out even if there are missing dihedral parameters, but we need to know
        # if there are any valid parameters as that determines whether to add the relevant section
        self.checkParameters(skipDihedrals=skipDihedrals)

        # Now write out FIELD file
        # REM DLPOLY does FORTRAN counting so add 1 to everything

        # Each are organised in lists by molecule
        numMolecules = len(coords)
        with open('FIELD', 'w') as f:

            # Header
            f.write("Ambuild FIELD file with {0} molecules\n".format(numMolecules))
            f.write("UNITS kcal\n")
            f.write("MOLECULES {0}\n".format(numMolecules))

            _types = set()
            for i in range(numMolecules):
                f.write("Molecule #{0}\n".format(i))
                f.write("NUMMOLS 1\n")
                f.write("ATOMS {0}\n".format(len(coords[i])))
                # x=set()
                # Loop over each atom and add to set and write out at end - clumsy
                for j in range(len(coords[i])):
                    t = types[i][j]
                    _types.add(t)
                    # f.write("{0:6}  {1:6}  {2:6}    1\n".format( t, masses[i][j], charges[i][j] ))
                    f.write("{0:6}  {1:6}  {2:6}    1    {3}\n".format(t, masses[i][j], charges[i][j], frozen[i][j]))
                    # d = (t, masses[i][j], charges[i][j])
                    # x.add(d)
                # for t,m,c in x:
                #    f.write("{0:6} {1:10} {2:10}\n".format( t, m, c ))

                # Rigid bodies
                if rigidBody:
                    nb = len(bodies2[i])
                    f.write("RIGID {0}\n".format(nb))
                    for bstart, bend in bodies2[i]:
                        nsites = bend - bstart
                        s = "{0}    ".format(nsites)

                        # First line is length and up to 15 entries
                        for b in range(min(15, nsites)):
                            s += "{0}    ".format(bstart + b + 1)
                        s += "\n"

                        # Remaining lines can take 16 per line
                        if nsites > 15:
                            for b in range(nsites - 15):
                                if b % 16 == 0 and b > 0:
                                    s += "\n{0}    ".format(bstart + b + 15 + 1)
                                else:
                                    s += "{0}    ".format(bstart + b + 15 + 1)
                            s += "\n"
                        f.write(s)

                # Bonds
                if (len(bonds[i])):
                    f.write("BONDS {0}\n".format(len(bonds[i])))
                    for j in range(len(bonds[i])):
                        b1, b2 = sorted(bondTypes[i][j])
                        b = "{0}-{1}".format(b1, b2)
                        param = self.ffield.bondParameter(b)
                        f.write("harm    {0}    {1}    {2}    {3}\n".format(bonds[i][j][0] + 1, bonds[i][j][1] + 1, param['k'], param['r0']))

                # Angles
                if (len(angles[i])):
                    f.write("ANGLES {0}\n".format(len(angles[i])))
                    for j in range(len(angles[i])):
                        # a1,a2,a3 = sorted( angleTypes[i][j] )
                        a1, a2, a3 = angleTypes[i][j]
                        a = "{0}-{1}-{2}".format(a1, a2, a3)
                        param = self.ffield.angleParameter(a)
                        f.write("harm    {0}    {1}    {2}    {3}    {4}\n".format(angles[i][j][0] + 1,
                                                                                   angles[i][j][1] + 1,
                                                                                   angles[i][j][2] + 1,
                                                                                   param['k'],
                                                                                   math.degrees(param['t0'])))

                # Dihedrals
                if (len(propers[i])):
                    # Check if any are valid
                    ok_propers = []
                    for j in range(len(propers[i])):
                        d1, d2, d3, d4 = properTypes[i][j]
                        d = "{0}-{1}-{2}-{3}".format(d1, d2, d3, d4)
                        if self.ffield.hasDihedral(d): ok_propers.append(True)
                        else: ok_propers.append(False)
                     
                    if any(ok_propers):
                        f.write("DIHEDRALS {0}\n".format(sum(ok_propers)))
                        for j in range(len(propers[i])):
                            if not ok_propers[j]: continue
                            # d1,d2,d3,d4 = sorted(properTypes[i][j] )
                            d1, d2, d3, d4 = properTypes[i][j]
                            d = "{0}-{1}-{2}-{3}".format(d1, d2, d3, d4)
                            param = self.ffield.dihedralParameter(d)
                            # A delta m - DLPOLY
                            # k d  n - hoomd
                            # d parameter should be 0 or 180
                            if param['d'] == -1: dp = 180
                            elif param['d'] == 1: dp = 0
                            f.write("cos  {0:6}  {1:6}  {2:6}  {3:6}  {4:6}  {5:6} {6:6}\n".format(propers[i][j][0] + 1,
                                                                                             propers[i][j][1] + 1,
                                                                                             propers[i][j][2] + 1,
                                                                                             propers[i][j][3] + 1,
                                                                                             param['k'] / 2,
                                                                                             dp,
                                                                                             param['n']))

                # End of Molecule
                f.write("FINISH\n")

            # End of MOLECULE loop so write out non-bonded parameters
            _types = sorted(_types)
            p = []
            for i, atype in enumerate(_types):
                for j, btype in enumerate(_types):
                    if j >= i:
                        param = self.ffield.pairParameter(atype, btype)
                        p.append((atype, btype, param['epsilon'], param['sigma']))

            f.write("VDW    {0}\n".format(len(p)))
            for a, b, e, s in p:
                f.write("{0:8} {1:6}  lj  {2:6}  {3:6}\n".format(a, b, e, s))

            # EOF
            f.write("CLOSE\n")

        return


#     def writeFIELD(self,
#                    cell,
#                    ):
#         """
#         Assumes block/frag indices have been set
#         """
#
#         bonds = []
#         bondTypes = []
#         angles = []
#         angleTypes = []
#         propers = []
#         properTypes = []
#         impropers = []
#         improperTypes = []
#
#         types = []
#         coords = []
#         images = []
#         charges = []
#         diameters = []
#         masses = []
#         symbols = []
#         bodies = []
#
#
#         atomCount = 0 # Global count in cell
#         bodyCount = -1
#         for idxBlock, block in cell.blocks.iteritems():
#
#             # Do bonds first as counting starts from atomCount and goes up through the blocks
#             if not rigidBody:
#                 # add all bonds, angles and dihederals throughout the whole block
#                 # Add all bonds
#                 bonds += [ (a1+block.cellIdx, a2+block.cellIdx) for a1, a2 in block.bonds() ]
#                 blockBondTypes += [ (block.type(a1),block.type(a2)) for a1, a2 in block.bonds() ]
#                 angles, propers, impropers = block.anglesAndDihedrals()
#                 # Add all angles
#                 blockAngles += [ (a1+block.cellIdx, a2+block.cellIdx, a3+block.cellIdx) for a1, a2, a3 in angles ]
#                 blockAngleTypes += [ (block.type(a1),block.type(a2),block.type(a3)) for a1, a2, a3 in angles ]
#                 # Add all propers
#                 blockPropers += [ (a1+block.cellIdx, a2+block.cellIdx, a3+block.cellIdx, a4+block.cellIdx) \
#                                  for a1, a2, a3, a4 in propers ]
#                 blockProperTypes += [ (block.type(a1),
#                                        block.type(a2),
#                                        block.type(a3),
#                                        block.type(a4)
#                                        ) for a1, a2, a3, a4 in propers ]
#                 # Add all impropers
#                 blockImpropers += [ (a1+block.cellIdx, a2+block.cellIdx, a3+block.cellIdx, a4+block.cellIdx) \
#                                    for a1, a2, a3, a4 in impropers ]
#                 blockImproperTypes += [ (block.type(a1),
#                                          block.type(a2),
#                                          block.type(a3),
#                                          block.type(a4)
#                                          ) for a1, a2, a3, a4 in impropers ]
#
#             else:
#                 # Just add the bonds between blocks. Also add angles for all atoms connected to the bonds
#                 # we do this so that we can exclude them from VdW interactions in MD codes
#                 for b1, b2 in block.blockBonds():
#
#                     # The bonds themselves
#                     blockBonds.append( (b1+block.cellIdx,b2+block.cellIdx) )
#                     blockBondTypes.append(( block.type(b1),block.type(b2) ))
#
#                     _angles=set()
#                     # Atoms connected to the endGroup that we need to specify as connected so we add as angles
#                     for batom in block.atomBonded1( b1 ):
#                         # The opposite endGroup is included in the list bonded to an endGroup so skip
#                         if batom == b2:
#                             continue
#                         _angles.add( ( batom, b1, b2 ) )
#
#                     for batom in block.atomBonded1( b2 ):
#                         # The opposite endGroup is included in the list bonded to an endGroup so skip
#                         if batom == b1:
#                             continue
#                         _angles.add( ( b1, b2, batom ) )
#
#                     # Add to overall lists
#                     for a1, a2, a3 in _angles:
#                         blockAngles.append( (a1+block.cellIdx, a2+block.cellIdx, a3+block.cellIdx))
#                         blockAngleTypes.append( ( block.type( a1 ),
#                                                   block.type( a2 ),
#                                                   block.type( a3 ) ) )
#
#                     #
#                     # Dihedrals
#                     #
#                     for dindices in block.dihedrals( b1, b2 ):
#                         dihedral = ( dindices[0] + block.cellIdx,
#                                      dindices[1] + block.cellIdx,
#                                      dindices[2] + block.cellIdx,
#                                      dindices[3] + block.cellIdx )
#                         blockPropers.append( dihedral )
#                         blockProperTypes.append( ( block.type( dindices[0] ),
#                                                    block.type( dindices[1] ),
#                                                    block.type( dindices[2] ),
#                                                    block.type( dindices[3] )
#                                                 ) )
#
#             # Now loop through fragments and coordinates
#             #for i, coord in enumerate(block.iterCoord() ):
#             for idxFrag,frag in enumerate(block.fragments): # need index of fragment in block
#
#                 # Body count always increments with fragment although it may go up within a fragment too
#                 bodyCount += 1
#
#                 lastBody=frag.body(0)
#                 for i,coord in enumerate(frag.iterCoord()):
#                     if periodic:
#                         x, ix = util.wrapCoord( coord[0], self.A, center=center )
#                         y, iy = util.wrapCoord( coord[1], self.B, center=center )
#                         z, iz = util.wrapCoord( coord[2], self.C, center=center )
#                         blockCoords.append( numpy.array([x,y,z]))
#                         blockImages.append([ix,iy,iz])
#                     else:
#                         blockCoords.append(coord)
#                         blockImages.append([0,0,0])
#
#                     blockTypes.append(frag.type(i))
#                     blockCharges.append(frag.charge(i))
#                     blockDiameters.append(0.1)
#                     blockMasses.append(frag.mass(i))
#                     blockSymbols.append(frag.symbol(i))
#
#                     # Work out which body this is in
#                     b = frag.body(i)
#                     if b != lastBody:
#                         bodyCount +=1
#                         lastBody = b
#                     blockBodies.append( bodyCount )
#
#                     # Increment global atom count
#                     atomCount += 1
#
#                 # Work out which fragment this is in
#                 # REM blockCount is NOT idxBlock in the dict - need to rationalise this.
#                 d.tagIndices.append((idxBlock,idxFrag,atomCount-i,atomCount))
#
#             #END loop through fragments
#
#             # Now have all data pertaining to a particular block
#             bonds.append(blockBonds)
#             bondTypes.append(blockBondTypes)
#             angles.append(blockAngles)
#             angleTypes.append(blockAngleTypes)
#             propers.append(blockPropers)
#             properTypes.append(blockProperTypes)
#             impropers.append(blockImpropers)
#             improperTypes.append(blockImproperTypes)
#
#             types.append(blockTypes)
#             coords.apend(blockCoords)
#             images.append(blockImages)
#             charges.append(blockCharges)
#             diameters.append(blockDiameters)
#             masses.append(blockMasses)
#             symbols.append(blockSymbols)
#             bodies.append(blockBodies)
#
#
#
#         # End block loop
#
#
#         return


class HoomdOptimiser(FFIELD):

    def __init__(self):

        self.ffield = FfieldParameters()
        self.system = None
        self.bonds = None
        self.angles = None
        self.dihedrals = None
        self.impropers = None
        self.atomTypes = None
        self.masked = None
        self.rCut = 5.0
        
        self.groupActive = None
        self.groupAll = None
        self.groupStatic = None
        
        self.debug = False

        # kB = 8.310 * 10**-23 Angstroms**2 g mole**-1 s**-2 K**-1
        # Incoming T is in Kelvin so we multiply by kB
        self.CONVERSIONFACTOR = 8.310E-23
        return

    def fragMaxEnergy(self,
                      data,
                      xmlFilename,
                      doDihedral=False,
                      doImproper=False,
                      rigidBody=True,
                      rCut=None,
                      quiet=None,
                       **kw):

        if rCut is not None:
            self.rCut = rCut

        if doDihedral and doImproper:
            raise RuntimeError, "Cannot have impropers and dihedrals at the same time"

        self.system = self.setupSystem(data,
                                       xmlFilename=xmlFilename,
                                       doDihedral=doDihedral,
                                       doImproper=doImproper,
                                       rCut=self.rCut,
                                       quiet=quiet,
                                       maxE=True,
                                    )

        quantities = ['potential_energy', 'kinetic_energy']

        # see setupSystem for where the groups are created
        for idxBlock, idxFragment, start, end in data.tagIndices:
            quantities.append("potential_energy_{0}:{1}".format(start, end))

        self.hlog = hoomdblue.analyze.log(filename='mylog1.csv',
                                     quantities=quantities,
                                     period=1,
                                     header_prefix='#',
                                     overwrite=True
                                     )

        optimised = self._optimiseGeometry(rigidBody=rigidBody,
                                            optCycles=10,
                                            **kw)

        maxe = -10000
        maxi = -1
        for i, (idxBlock, idxFragment, start, end) in enumerate(data.tagIndices):
            label = "potential_energy_{0}:{1}".format(start, end)
            print "LABEL ", label
            e = self.toStandardUnits(self.hlog.query(label))
            print "GOT E ", e
            if e > maxe:
                maxe = e
                maxi = i

        assert not i == -1
        idxBlock, idxFragment, start, end = data.tagIndices[maxi]
        return maxe, idxBlock, idxFragment

    def fromStandardUnits(self, value):
        # return float(value) * self.CONVERSIONFACTOR
        return float(value)

    def optimiseGeometry(self,
                          data,
                          xmlFilename="hoomdOpt.xml",
                          rigidBody=True,
                          doDihedral=False,
                          doImproper=False,
                          doCharges=True,
                          rCut=None,
                          quiet=None,
                          walls=None,
                          wallAtomType=None,
                          **kw):

        if rCut is not None:
            self.rCut = rCut

        if doDihedral and doImproper:
            raise RuntimeError, "Cannot have impropers and dihedrals at the same time"

        self.system = self.setupSystem(data,
                                       xmlFilename=xmlFilename,
                                       rigidBody=rigidBody,
                                       doDihedral=doDihedral,
                                       doImproper=doImproper,
                                       rCut=self.rCut,
                                       quiet=quiet,
                                       walls=walls,
                                       wallAtomType=wallAtomType,
                                       )

        # Logger - we don't write anything but query the final value - hence period 0 and overwrite
        self.hlog = hoomdblue.analyze.log(filename='mylog.csv',
                                     quantities=[
                                                 'num_particles',
                                                 'pair_lj_energy',
                                                 'potential_energy',
                                                 'kinetic_energy',
                                                 ],
                                     period=100,
                                     header_prefix='#',
                                     overwrite=True
                                     )

        optimised = self._optimiseGeometry(rigidBody=rigidBody,
                                            **kw)

        # Extract the energy
        if 'd' in kw and kw['d'] is not None:
            for i in ['potential_energy' ]:
                kw['d'][ i ] = self.toStandardUnits(self.hlog.query(i))

        return optimised

    def _optimiseGeometry(self,
                          carOut="hoomdOpt.car",
                          rigidBody=True,
                          optCycles=1000000,
                          dump=False,
                          dt=0.005,
                          Nmin=5,
                          alpha_start=0.1,
                          ftol=1e-2,
                          Etol=1e-5,
                          finc=1.1,
                          fdec=0.5,
                          max_tries=3,
                          retries_on_error=3,
                          **kw):
        """Optimise the geometry with hoomdblue"""
        
        assert max_tries > 0 and retries_on_error > 0

        for i in range(retries_on_error):
            # Try optimising and lower the timestep and increasing the number of cycles each time
            try:
                # Create the integrator with the values specified
                if rigidBody:
                    fire = hoomdblue.integrate.mode_minimize_rigid_fire(group=self.groupActive,
                                                                         dt=dt,
                                                                         Nmin=Nmin,
                                                                         alpha_start=alpha_start,
                                                                         ftol=ftol,
                                                                         Etol=Etol,
                                                                         finc=finc,
                                                                         fdec=fdec)
                else:
                    fire = hoomdblue.integrate.mode_minimize_fire(group=self.groupActive,
                                                                dt=dt,
                                                                Nmin=Nmin,
                                                                alpha_start=alpha_start,
                                                                ftol=ftol,
                                                                Etol=Etol,
                                                                finc=finc,
                                                                fdec=fdec)
                if dump:
                    # For tracking the optimsation
                    xmld = hoomdblue.dump.xml(filename="runopt.xml", vis=True)
                    dcdd = hoomdblue.dump.dcd(filename="runopt.dcd",
                                              period=1,
                                              unwrap_full=True,
                                              overwrite=True)
                optimised = False
                for j in range(max_tries):
                    logger.info("Running {0} optimisation cycles in macrocycle {1}".format(optCycles,j))
                    hoomdblue.run(optCycles,
                                   callback=lambda x:-1 if fire.has_converged() else 0,
                                   callback_period=1)
                    if fire.has_converged():
                        logger.info("Optimisation converged on macrocycle {0}".format(j))
                        optimised = True
                        break
                    else:
                        logger.info("Optimisation failed to converge on macrocycle {0}".format(j))
                        if j+1 < max_tries:  logger.info("Attempting another optimisation macrocycle")
                break # Break out of try/except loop
            except RuntimeError as e:
                logger.info("Optimisation step {0} failed!\n{1}".format(i,e))
                if i+1 < retries_on_error:
                    dt_old = dt
                    dt = dt_old * 0.1
                    logger.info("Rerunning optimisation changing dt {0} -> {1}".format(dt_old, dt))
                else:
                    # If we're not going to try again we re-raise the last exception that we caught
                    raise
            # if float( self.hlog.query( 'potential_energy' ) ) < 1E-2:
            #    print "!!!!!!!!!!!HACK CONVERGENCE CRITERIA!!!!!!"
            #    optimised=True
            #    break
        # Delete variables before we return to stop memory leaks
        # del fire
        if dump and False:
            xmld.disable()
            dcdd.disable()
            del xmld
            del dcdd
#         del harmonic
#         del aharmonic
#         del improper
#         del lj
        # Write out a car file so we can see what happened
        # self.writeCar( system=self.system, filename=carOut, unwrap=True )
        return optimised

    def runMD(self,
              data,
              xmlFilename="hoomdMD.xml",
              doDihedral=False,
              doImproper=False,
              doCharges=True,
              rigidBody=True,
              rCut=None,
              quiet=None,
              walls=None,
              wallAtomType=None,
              **kw):

        if rCut is not None:
            self.rCut = rCut

        if doDihedral and doImproper:
            raise RuntimeError, "Cannot have impropers and dihedrals at the same time"

        self.system = self.setupSystem(data,
                                       xmlFilename=xmlFilename,
                                       rigidBody=rigidBody,
                                       doDihedral=doDihedral,
                                       doImproper=doImproper,
                                       rCut=self.rCut,
                                       quiet=quiet,
                                       walls=walls,
                                       wallAtomType=wallAtomType,
                                       )

        # Logger - we don't write anything but query the final value - hence period 0 and overwrite
        hlog = hoomdblue.analyze.log(filename='mylog.log',
                                     quantities=[
                                                 'num_particles',
                                                 'pair_lj_energy',
                                                 'potential_energy',
                                                 'kinetic_energy',
                                                 ],
                                     period=0,
                                     header_prefix='#',
                                     overwrite=True
                                     )

        self._runMD(rigidBody=rigidBody,
                    **kw)

        # Extract the energy
        if 'd' in kw and kw['d'] is not None:
            for i in ['potential_energy' ]:
                kw['d'][ i ] = self.toStandardUnits(hlog.query(i))

        return True

    def runMDAndOptimise(self,
                         data,
                         xmlFilename="hoomdMdOpt.xml",
                         rigidBody=True,
                         doDihedral=False,
                         doImproper=False,
                         doCharges=True,
                         rCut=None,
                         quiet=None,
                         walls=None,
                         wallAtomType=None,
                         **kw):

        if rCut is not None:
            self.rCut = rCut

        if doDihedral and doImproper:
            raise RuntimeError, "Cannot have impropers and dihedrals at the same time"

        self.system = self.setupSystem(data,
                                       xmlFilename=xmlFilename,
                                       rigidBody=rigidBody,
                                       doDihedral=doDihedral,
                                       doImproper=doImproper,
                                       rCut=self.rCut,
                                       quiet=quiet,
                                       walls=walls,
                                       wallAtomType=wallAtomType,
                                       )

        # Logger - we don't write anything but query the final value - hence period 0 and overwrite
        self.hlog = hoomdblue.analyze.log(filename='mylog.csv',
                                     quantities=[
                                                 'num_particles',
                                                 'pair_lj_energy',
                                                 'potential_energy',
                                                 'kinetic_energy',
                                                 ],
                                     period=0,
                                     header_prefix='#',
                                     overwrite=True
                                     )

        # pre-optimise for preopt steps to make sure the sytem is sane - otherwise the MD
        # blows up
        preOptCycles = 5000
        self._optimiseGeometry(optCycles=preOptCycles,
                               dt=0.0001)
        # Now run the MD steps
        self._runMD(**kw)

        # Finally do a full optimisation
        optimised = self._optimiseGeometry(**kw)

        # Extract the energy
        if 'd' in kw and kw['d'] is not None:
            for i in ['potential_energy' ]:
                kw['d'][ i ] = self.toStandardUnits(self.hlog.query(i))

        return optimised

    def _runMD(self, mdCycles=100000,
               rigidBody=True,
               integrator='nvt',
               T=1.0,
               tau=0.5,
               P=1,
               tauP=0.5,
               dt=0.0005,
               dump=False,
               dumpPeriod=100, **kw):

        # Added **kw arguments so that we don't get confused by arguments intended for the optimise
        # when MD and optimiser run together
        # T= 0.1

        # Convert T
        # kB = 8.310 * 10**-23 Angstroms**2 g mole**-1 s**-2 K**-1
        # Incoming T is in Kelvin so we multiply by kB
        T = self.fromStandardUnits(T)
        integrator_mode = hoomdblue.integrate.mode_standard(dt=dt)

        if integrator == 'nvt':
            if rigidBody:
                # nvt = hoomdblue.integrate.nvt_rigid(group=hoomdblue.group.rigid(), T=T, tau=tau )
                integ = hoomdblue.integrate.nvt_rigid(group=self.groupActive, T=T, tau=tau)
            else:
                integ = hoomdblue.integrate.nvt(group=self.groupActive, T=T, tau=tau)
        elif integrator == 'npt':
            if rigidBody:
                integ = hoomdblue.integrate.npt_rigid(group=self.groupActive, T=T, tau=tau, P=P, tauP=tauP)
            else:
                integ = hoomdblue.integrate.npt(group=self.groupActive, T=T, tau=tau, P=P, tauP=tauP)
        else:
            raise RuntimeError("Unrecognised integrator: {0}".format(integrator))

        if dump:
            xmld = hoomdblue.dump.xml(filename="runmd.xml", vis=True)
            dcdd = hoomdblue.dump.dcd(filename="runmd.dcd",
                                      period=dumpPeriod,
                                      unwrap_full=True,
                                      overwrite=True)

        # run mdCycles time steps
        hoomdblue.run(mdCycles)

        integ.disable()
        if dump:
            #xmld.disable()
            dcdd.disable()
            del xmld
            del dcdd
        del integ
        del integrator_mode
        return

    def setAngle(self, anglePotential):
        for angle in self.angles:
            param = self.ffield.angleParameter(angle)
            if self.debug:
                logger.info("DEBUG: angle set_coeff( '{0}',  k={1}, t0={2} )".format(angle, param['k'], param['t0']))
            anglePotential.set_coeff(angle, k=param['k'], t0=param['t0'])
        return

    def setBond(self, bondPotential):
        for bond in self.bonds:
            param = self.ffield.bondParameter(bond)
            if self.debug:
                logger.info("DEBUG: bond_coeff.set( '{0}',  k={1}, r0={2} )".format(bond, param['k'], param['r0']))
            bondPotential.bond_coeff.set(bond, k=param['k'], r0=param['r0'])
        return

    def setDihedral(self, dihedralPotential):
        for dihedral in self.dihedrals:
            param = self.ffield.dihedralParameter(dihedral)
            if self.debug:
                logger.info("DEBUG: dihedral set_coeff.('{0}',  k={1}, d={2}, n={3})".format(dihedral, param['k'], param['d'], param['n']))
            dihedralPotential.set_coeff(dihedral, k=param['k'], d=param['d'], n=param['n'])
        return

    def setImproper(self, improperPotential):
        for improper in self.impropers:
            param = self.ffield.improperParameter(improper)
            improperPotential.set_coeff(improper, k=param['k'], chi=param['chi'])
        return

    def setPair(self, pairPotential):
        for i, atype in enumerate(self.atomTypes):
            for j, btype in enumerate(self.atomTypes):
                if j >= i:
                    # dummy atoms treated specially
                    #if atype.lower() in ['x','hn'] or btype.lower() in ['x','hn']:
                    if self.masked[i] or self.masked[j]:
                        epsilon = 0.0
                        sigma = 0.0
                    else:
                        param = self.ffield.pairParameter(atype, btype)
                        epsilon = param['epsilon']
                        sigma = param['sigma']
                        
                    pairPotential.pair_coeff.set(atype, btype, epsilon=epsilon, sigma=sigma)
                    if self.debug:
                        logger.info("DEBUG: pair_coeff.set( '{0}', '{1}', epsilon={2}, sigma={3} )".format(atype,
                                                                                                           btype,
                                                                                                           epsilon,
                                                                                                           sigma))
        return

    def setAttributesFromFile(self, xmlFilename):
        """Parse the xml file to extract the bonds, angles etc."""

        tree = ET.parse(xmlFilename)
        root = tree.getroot()

        bonds = []
        x = root.findall(".//bond")
        if len(x):
            btext = x[0].text
            for line in btext.split(os.linesep):
                line = line.strip()
                if line:
                    bond = line.split()[0]
                    if bond not in bonds:
                        bonds.append(bond)
        self.bonds = bonds

        angles = []
        x = root.findall(".//angle")
        if len(x):
            atext = x[0].text
            for line in atext.split(os.linesep):
                line = line.strip()
                if line:
                    angle = line.split()[0]
                    if angle not in angles:
                        angles.append(angle)
        self.angles = angles

        dihedrals = []
        dn = root.findall(".//dihedral")
        if len(dn):
            dtext = dn[0].text
            for line in dtext.split(os.linesep):
                line = line.strip()
                if line:
                    dihedral = line.split()[0]
                    if dihedral not in dihedrals:
                        dihedrals.append(dihedral)
        self.dihedrals = dihedrals

        impropers = []
        dn = root.findall(".//improper")
        if len(dn):
            dtext = dn[0].text
            for line in dtext.split(os.linesep):
                line = line.strip()
                if line:
                    improper = line.split()[0]
                    if improper not in impropers:
                        impropers.append(improper)
        self.impropers = impropers

        atomTypes = []
        atext = root.findall(".//type")[0].text
        for line in atext.split(os.linesep):
            atomType = line.strip()
            if atomType and atomType not in atomTypes:
                atomTypes.append(atomType)

        self.atomTypes = atomTypes

        return
    
    def setupGroups(self, data):
        self.groupAll = hoomdblue.group.all()
        # All atoms that are part of static fragments
        if any(data.static):
            self.groupStatic = hoomdblue.group.tag_list(name="static",
                                                      tags=[i for i, s in enumerate(data.static) if s])
            self.groupActive = hoomdblue.group.difference(name="active",
                                                        a=self.groupAll,
                                                        b=self.groupStatic)
        else:
            self.groupActive = self.groupAll
        return

    def setupSystem(self,
                    data,
                    xmlFilename,
                    doDihedral=False,
                    doImproper=False,
                    doCharges=True,
                    rigidBody=True,
                    rCut=None,
                    quiet=False,
                    maxE=False,
                    walls=None,
                    wallAtomType=None,
                     ):

        self.writeXml(data,
                      xmlFilename=xmlFilename,
                      rigidBody=rigidBody,
                      doCharges=doCharges,
                      doDihedral=doDihedral,
                      doImproper=doImproper)

        # Set the masked array
        self.masked = data.masked
        # Read parameters from file, set them as  attributes & check them
        self.setAttributesFromFile(xmlFilename)
        self.checkParameters()

        if hoomdblue.init.is_initialized():
            hoomdblue.init.reset()

        # Init the sytem from the file
        system = hoomdblue.init.read_xml(filename=xmlFilename)

        # Below disables pretty much all output
        if quiet:
            logger.info("Disabling HOOMD-Blue output!")
            hoomdblue.globals.msg.setNoticeLevel(0)

        # Set the parameters
        harmonic = None
        if len(self.bonds):
            harmonic = hoomdblue.bond.harmonic()
            self.setBond(harmonic)

        aharmonic = None
        if len(self.angles):
            aharmonic = hoomdblue.angle.harmonic()
            self.setAngle(aharmonic)

        dharmonic = improper = None
        if doDihedral and len(self.dihedrals):
                dharmonic = hoomdblue.dihedral.harmonic()
                self.setDihedral(dharmonic)
        elif doImproper and len(self.dihedrals):
            improper = hoomdblue.improper.harmonic()
            self.setImproper(improper)

        lj = hoomdblue.pair.lj(r_cut=rCut)
        self.setPair(lj)
        
        # Specify the groups
        self.setupGroups(data)
        
        # Add any walls
        self.setupWalls(walls, system, wallAtomType, rCut)

        if rigidBody:
            hoomdblue.globals.neighbor_list.reset_exclusions(exclusions=['1-2', '1-3', '1-4', 'angle', 'body'])
        else:
            hoomdblue.globals.neighbor_list.reset_exclusions(exclusions=['1-2', '1-3', '1-4', 'angle'])

        # For calculating groups
        # self.labels=[]
        if maxE:
            for idxBlock, idxFragment, start, end in data.tagIndices:
                # create the group
                l = "{0}:{1}".format(start, end)
                g = hoomdblue.group.tag_list(name=l, tags=range(start, end))
                print "SET GROUP ", start, end
                # create the compute for this group
                c = hoomdblue.compute.thermo(group=g)
                # self.labels.append(l)


# Do we need to think about saving the references and deleting them?
#         del harmonic
#         del aharmonic
#         del improper
#         del lj

        return system
    
    def setupWalls(self, walls, system, wallAtomType, rCut):
        """Set up walls for the simulation
        
        I think that we require two walls. One on the front side with the potential facing in,
        the other on the back wall with the potential facing back towards the other potential.
        The origin of the wall is the centre of plane but then back half a cell along the axis 
        that isn't part of the wall.
        """
        if walls is None: return
        assert len(walls) is 3 # array of three booleans - one per wall
        if not any(walls): return
        assert wallAtomType is not None,"Need to set a wallAtomType!"
        wtypes = ['XOY', 'XOZ', 'YOZ'] # Oroder of walls
        wallstructure = None
        for do, wtype in zip(walls, wtypes):
            if do:
                logger.info('Setting wall in HOOMDBLUE for {0} of atomType {1}'.format(wtype, wallAtomType))
                if wtype is 'XOY':
                    originFront = (0, 0, -system.box.Lz/2)
                    originBack  = (0, 0,  system.box.Lz/2)
                    normal = (0, 0, 1)
                elif wtype is 'XOZ':
                    originFront = (0, -system.box.Ly/2, 0)
                    originBack  = (0,  system.box.Ly/2, 0)
                    normal = (0, 1, 0)
                elif wtype is 'YOZ':
                    originFront = (-system.box.Lx/2, 0, 0)
                    originBack  = ( system.box.Lx/2, 0, 0)
                    normal = (1, 0, 0)
                else:
                    raise RuntimeError("Unrecognised Wall Type! {0}".format(wtype))
            
                if not wallstructure:
                    # We only create the wall and the LJ potentials once as they are used
                    # by all subsequent walls in the group
                    try: 
                        wallstructure = hoomdblue.wall.group()
                    except AttributeError:
                        raise RuntimeError('HOOMD-blue wall does not have a group attribute. You may need to update your version of HOOMD-Blue in order to use walls')
                    lj = hoomdblue.wall.lj(wallstructure, r_cut=rCut)
                    for atype in self.atomTypes:
                        param = self.ffield.pairParameter(atype, wallAtomType)
                        lj.force_coeff.set(atype, epsilon=param['epsilon'], sigma=param['sigma'])
                
                # Add the two walls
                # Front
                wallstructure.add_plane(origin=originFront, normal=normal, inside=True)
                # Back
                wallstructure.add_plane(origin=originBack, normal=normal, inside=False)
        return

    def toStandardUnits(self, value):
        # return float(value) / self.CONVERSIONFACTOR
        return float(value)

    def writeCar(self, system, filename, unwrap=True, pbc=True):
        """Car File
        """

        car = "!BIOSYM archive 3\n"
        car += "PBC=ON\n"

        car += "ambuild generated car file\n"
        tstr = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime())
        car += "!DATE {0}\n".format(tstr)

        xdim = system.box[0]
        ydim = system.box[1]
        zdim = system.box[2]
        if pbc:
            car += "PBC  {0: < 9.4F} {1: < 9.4F} {2: < 9.4F}  90.0000   90.0000   90.0000 (P1)\n".format(xdim,
                                                                                                      ydim,
                                                                                                      zdim)

        for p in system.particles:

                label = atype = p.type.strip()

                # Treat x-atoms differently
                if label[0].lower() == 'x':
                    symbol = 'x'
                else:
                    symbol = util.label2symbol(label)

                x, y, z = p.position
                ix, iy, iz = p.image
                charge = float(p.charge)

                if unwrap:
                    x = util.unWrapCoord(x, ix, xdim, centered=False)
                    y = util.unWrapCoord(y, iy, ydim, centered=False)
                    z = util.unWrapCoord(z, iz, zdim, centered=False)
                else:
                    # Put back with origin at corner
                    x = x + (xdim / 2)
                    y = y + (ydim / 2)
                    z = z + (zdim / 2)

                car += "{0: <5} {1: >15.10} {2: >15.10} {3: >15.10} XXXX 1      {4: <4}    {5: <2} {6: > 2.3f}\n".format(label, x, y, z, atype, symbol, charge)

        car += "end\nend\n\n"

        with open(filename, 'w') as f:
            f.writelines(car)

        return

    def writeXml(self,
                 data,
                 xmlFilename="hoomd.xml",
                 rigidBody=True,
                 doCharges=True,
                 doDihedral=False,
                 doImproper=False
                 ):
        """Write out a HOOMD Blue XML file.
        """
        d = data
        #
        # Got data so now put into xml
        #
        body = "\n" + "\n".join(map(str, d.bodies)) + "\n"
        charge = "\n" + "\n".join(map(str, d.charges)) + "\n"
        diameter = "\n" + "\n".join(map(str, d.diameters)) + "\n"
        mass = "\n" + "\n".join(map(str, d.masses)) + "\n"
        ptype = "\n" + "\n".join(map(str, d.atomTypes)) + "\n"

        image = "\n"
        position = "\n"
        for i in range(len(d.coords)):
            image += "{0} {1} {2}\n".format(d.images[i][0],
                                             d.images[i][1],
                                             d.images[i][2])
            position += "{0} {1} {2}\n".format(d.coords[i][0],
                                                d.coords[i][1],
                                                d.coords[i][2])

        # Now do all angles and bonds
        bond = False
        if len(d.bonds):
            bond = "\n"
            for i, b in enumerate(d.bonds):
                bond += "{0} {1} {2}\n".format(d.bondLabels[i], b[0], b[1])

        angle = False
        if len(d.angles):
            angle = "\n"
            for i, a in enumerate(d.angles):
                angle += "{0} {1} {2} {3}\n".format(d.angleLabels[i], a[0], a[1], a[2])

        dihedral = False
        if len(d.propers):
            dihedral = "\n"
            for i, dh in enumerate(d.propers):
                dihedral += "{0} {1} {2} {3} {4}\n".format(d.properLabels[i], dh[0], dh[1], dh[2], dh[3])

        root = ET.Element('hoomd_xml', version="1.4")
        config = ET.SubElement(root, "configuration", timestep="0")

        # e = ET.SubElement( config, "box",
        ET.SubElement(config, "box",
                        Lx=str(d.cell[0]),
                        Ly=str(d.cell[1]),
                        Lz=str(d.cell[2]))

        e = ET.SubElement(config, "position")
        e.text = position
        e = ET.SubElement(config, "image")
        e.text = image

        if rigidBody:
            e = ET.SubElement(config, "body")
            e.text = body
        if doCharges:
            e = ET.SubElement(config, "charge")
            e.text = charge
        e = ET.SubElement(config, "diameter")
        e.text = diameter
        e = ET.SubElement(config, "type")
        e.text = ptype
        e = ET.SubElement(config, "mass")
        e.text = mass

        if bond:
            e = ET.SubElement(config, "bond")
            e.text = bond
        if angle:
            e = ET.SubElement(config, "angle")
            e.text = angle
        if dihedral:
            if doDihedral:
                e = ET.SubElement(config, "dihedral")
                e.text = dihedral
            elif doImproper:
                e = ET.SubElement(config, "improper")
                e.text = dihedral

        tree = ET.ElementTree(root)

        # ET.dump(tree)

        # tree.write(file_or_filename, encoding, xml_declaration, default_namespace, method)
        tree.write(xmlFilename)

        return True

    def writeXyz(self, system, filename=None, unwrap=True):
        """Car File
        """

        xyz = "{0}\n".format(len(system.particles))
        xyz += "opt.xyz file\n"

        xdim = system.box[0]
        ydim = system.box[1]
        zdim = system.box[2]

        for p in system.particles:

                label = util.label2symbol(p.type.strip())
                x, y, z = p.position
                ix, iy, iz = p.image

                if unwrap:
                    x = util.unWrapCoord(x, ix, xdim, centered=False)
                    y = util.unWrapCoord(y, iy, ydim, centered=False)
                    z = util.unWrapCoord(z, iz, zdim, centered=False)
                else:
                    # Put back with origin at corner
                    x = x + (xdim / 2)
                    y = y + (ydim / 2)
                    z = z + (zdim / 2)
                xyz += "{0:5}   {1:0< 15}   {2:0< 15}   {3:0< 15}\n".format(label, x, y, z)

        with open(filename, 'w') as f:
            f.writelines(xyz)

        return

def xml2xyz(xmlFilename, xyzFilename):
    """Convert a hoomdblue xml file to xyz"""


    tree = ET.parse(xmlFilename)
    root = tree.getroot()

    atomTypes = []
    atext = root.findall(".//type")[0].text
    atomTypes = [ line.strip() for line in atext.split(os.linesep) if line.strip() ]

    ptext = root.findall(".//position")[0].text
    positions = [ line.strip().split() for line in ptext.split(os.linesep) if line.strip() ]

    assert len(atomTypes) == len(positions)

    # Convert atom types to symbols
    symbols = []
    for at in atomTypes:
        if at.lower()[0] == 'x':
            symbols.append('x')
        else:
            symbols.append(util.label2symbol(at))

    # Now write out xyz
    util.writeXyz(xyzFilename, positions, symbols)
#     with open( xyzFilename, 'w') as o:
#         o.write("{0}\n".format( len( positions ) ) )
#         o.write("XYZ file created from: {0}\n".format( xmlFilename ) )
#         for i, symbol in enumerate( symbols ):
#             o.write( "{0:5}   {1:0< 15}   {2:0< 15}   {3:0< 15}\n".format( symbol,
#                                                                            float( positions[i][0] ),
#                                                                            float( positions[i][1] ),
#                                                                            float( positions[i][2] )
#                                                                            ) )
#
#         o.write("\n")

    print "Wrote file: {0}".format(xyzFilename)

    return


if __name__ == "__main__":

    # xmlFilename = sys.argv[1]
    # xyzFilename = xmlFilename +".xyz"
    # xml2xyz( xmlFilename, xyzFilename )

    opt = HoomdOptimiser()
    mycell = util.cellFromPickle(sys.argv[1])
    rigidBody = False
    data = mycell.dataDict(periodic=True, center=True, rigidBody=rigidBody)
    ok = opt.optimiseGeometry(data,
                            xmlFilename="opt.xml",
                            rigidBody=rigidBody,
                            doDihedral=True,
                            doImproper=False,
                            doCharges=True
                            )

    # optimiser.optimiseGeometry( xmlFilename=xmlFilename, doDihedral=False )

