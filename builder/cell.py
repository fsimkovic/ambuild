'''
Created on Jan 15, 2013

@author: abbietrewin
'''

import collections
import copy
import cPickle
import csv
import logging
import math
import os
import random
import sys
import time
import unittest
import xml.etree.ElementTree as ET

# External modules
import numpy

# Our modules
import buildingBlock
import fragment
import opt
import util

class Analyse():
    def __init__(self, cell, logfile="ambuild.csv"):
        
        self.fieldnames = ['step',
                           'type',
                           'tot_time',
                           'time',
                           'num_frags',
                           'num_particles',
                           'num_blocks',
                           'density',
                           'num_free_endGroups',
                           'potential_energy',
                           'num_tries',
                           'fragment_types',
                           'file_count',
                            ]
        self.cell = cell
        
        self.step = 0
        self._startTime = time.time()
        self._stepTime  = time.time()
        
        # Need to create an initial entry as we query the previous one for any data we don't have
        d = {}
        for f in self.fieldnames:
            if f == 'time':
                d[ f ] = self._startTime
            #elif f == 'file_count':
            elif f == 'type':
                d[ f ] = 'init'
            else:
                d[ f ] = 0
        
        self.last = d
        
        self.logfile = logfile
        self._logWriter = csv.DictWriter( open(self.logfile, 'w'), self.fieldnames )
        
        self._logWriter.writeheader()
        
        return
    
    def start(self):
        """Called whenever we start a step"""
        assert self._stepTime == None
        assert self.last
        self.step += 1
        self._stepTime = time.time()
        return
    
    def stop(self, stype, d={}):
        """Called at the end of a step with the data to write to the csv file"""
        
        new = {}
        
        for f in self.fieldnames:
            if f == 'type':
                new[ f ] = stype
            elif f == 'step':
                new [ f ] = self.step
            elif f == 'time':
                new[ f ] = time.time() - self._stepTime
            elif f == 'tot_time':
                new[ f ] = time.time() - self._startTime
                self._stepTime
            elif f == 'num_blocks':
                new[ f ] = self.cell.numBlocks()
            elif f == 'num_frags':
                new[ f ] = self.cell.numFragments()
            elif f == 'num_particles':
                new[ f ] = self.cell.numAtoms()
            elif f == 'num_free_endGroups':
                new[ f ] = self.cell.numFreeEndGroups()
            elif f == 'density':
                new[ f ] = self.cell.density()
            elif f == 'fragment_types':
                new[ f ] = str( self.cell.fragmentTypes() )
            elif f == 'file_count':
                new[ f ] = self.cell._fileCount
            elif f in d:
                new[ f ] = d[ f ]
            else:
                new[ f ] = self.last[ f ]
        
        self._logWriter.writerow( new )
        
        self.last = new
        self._stepTime = None
        self.start()
        return

class Cell():
    '''
    classdocs
    '''
    
    BONDTYPESEP     = "-" # Character for separating bonds
    ENDGROUPSEP     = ":" # Character for separating endGroups in bonds

    def __init__( self, atomMargin=0.5, bondMargin=0.5, bondAngleMargin=15, doLog=False ):
        '''
        Constructor
        '''

        # A, B and C are cell vectors - for the time being we assume they are orthogonal
        # so they are just floats
        self.A = self.B = self.C = None
        
        # For time being origin always 0,0,0
        self.origin = numpy.array( [0,0,0], dtype=numpy.float64 )
        
        # additional distance to add on to the characteristic bond length
        # when checking whether 2 atoms are close enough to bond
        self.bondMargin = bondMargin
        
        # additional distance to add on to the atom covalent radii when checking if two atoms 
        # are close enough to clash
        self.atomMargin = atomMargin
        
        # convert bondAngle and bondMargin to angstroms
        # Could check values are in degrees and not radians?
        self.bondAngleMargin = math.radians(bondAngleMargin)
        
        self.targetDensity = 10
        self.targetEndGroups = 100 # number of free endgroups left
        
        # Dict mapping box key to a list of tuples defining the atoms in that box
        self.box1={}
        
        # Dict mapping key to list of boxes surrounding the keyed box
        self.box3={}
        
        # max atom radius - used to calculate box size
        self.boxSize = None
        self.maxAtomRadius=-1
        
        # see optimiseGeometry
        self.rCut = 5.0
        self.minCell = False
        self.minCellData = None
        
        # number of boxes in A,B,C axes - used for calculating PBC
        self.numBoxA = None
        self.numBoxB = None
        self.numBoxC = None
        
        self._fragmentLibrary = {} # fragmentType -> parentFragment
        self._endGroup2LibraryFragment = {} # endGroup type -> parentFragment
        self.bondTypes = []
        self._bondTable = {} # endGroup type -> set of endGroups it can bond to
        
        # dictionary mapping id of the block to the block - can't use a list and indices
        # as we add and remove blocks and need to keep track of them
        self.blocks = collections.OrderedDict()
        
        # Holds possible bond after checkMove is run
        self._possibleBonds = []
        
        # Logging functions
        self.logger = None
        self.setupLogging( doLog=doLog )
        
        # For analysis csv
        self._setupAnalyse()
        
        self._fileCount=0 # for naming output files
        
        return
    
    def addBlock( self, block, idxBlock=None ):
        """
        Add the block and put all atoms in their cells
        """
        
        # The id of the new block
        if idxBlock == None:
            idxBlock = block.id
        
        # Add to the dict
        self.blocks[ idxBlock ] = block
        
        # Each atom has its own cell - X atoms remain as Nones
        block.atomCell = [ None ] * block.numAllAtoms()
        
        #print "nbox ",self.numBoxA,self.numBoxB,self.numBoxC
        for idxCoord,coord in enumerate( block.iterCoord() ):
            
            # Skip adding dummy atoms
            if block.invisibleAtom( idxCoord ):
                #print "SKIPPING AS BONDED or x"
                continue
            
            # Periodic Boundaries
            x = coord[0] % self.A
            y = coord[1] % self.B
            z = coord[2] % self.C
            
            # Calculate which cell the atom is in
            a=int( math.floor( x / self.boxSize ) )
            b=int( math.floor( y / self.boxSize ) ) 
            c=int( math.floor( z / self.boxSize ) )
            key = (a,b,c)
            block.atomCell[ idxCoord ] = key
            
            try:
                # Add the atom to the cell
                self.box1[ key ].append( ( idxBlock, idxCoord ) )
            except KeyError:
                # Add the cell to the list and then add the atom
                self.box1[ key ] = [ ( idxBlock, idxCoord ) ]
                # Map the cells surrounding this one
                self.box3[ key ] = self.surroundCells( key )
                
        return idxBlock
    
    def addBondType( self, bondType ):
        """what it says"""
        
        try:
            b1EndGroupType, b2EndGroupType = bondType.split(self.BONDTYPESEP)
            b1FragmentType = b1EndGroupType.split(self.ENDGROUPSEP)[0]
            b2FragmentType = b2EndGroupType.split(self.ENDGROUPSEP)[0]
        except ValueError:
            raise RuntimeError,"Error adding BondType {0} - string needs to be of form 'A:a-B:b'".format( bondType )
        
        # Checks
        assert b1FragmentType in self._fragmentLibrary,\
        "No fragment type {0} in fragmentLibrary".format( b1FragmentType )
        assert b1EndGroupType in self._fragmentLibrary[ b1FragmentType ].endGroupTypes(),\
        "Fragment type {0} has no endGroup type {1}".format( b1FragmentType, b1EndGroupType )
        assert b2FragmentType in self._fragmentLibrary,"No fragment type {0} in fragmentLibrary".format( b2FragmentType )
        assert b2EndGroupType in self._fragmentLibrary[ b2FragmentType ].endGroupTypes(),\
        "Fragment type {0} has no endGroup type {1}".format( b2FragmentType, b2EndGroupType )
        
        assert b1EndGroupType in self._endGroup2LibraryFragment.keys(),\
        "No endGroup type {0} in fragmentLibrary!".format(b1EndGroupType)
        assert b2EndGroupType in self._endGroup2LibraryFragment.keys(),\
        "No endGroup type {0} in fragmentLibrary!".format(b2EndGroupType)
        
        bt = (b1EndGroupType, b2EndGroupType)
        if bt in self.bondTypes:
            raise RuntimeError,"Adding an existing bond type: {0}".format( t )
        
        self.bondTypes.append( bt )
        
        # Now recalculate the bond table
        self._updateBondTable()
        
        return
    
    def _updateBondTable(self):
        """Recalculate the dicionary of what endGroups can bond to which"""
        self._bondTable = {}
        for bondA, bondB in self.bondTypes:
            if bondA not in self._bondTable:
                self._bondTable[ bondA ] = set()
            if bondB not in self._bondTable:
                self._bondTable[ bondB ] = set()
            
            self._bondTable[ bondA ].add( bondB )
            self._bondTable[ bondB ].add( bondA )
        return
    
    def addInitBlock( self, filename, fragmentType='A' ):
        """add a block of type ftype from the file filename"""
        
        if self._fragmentLibrary.has_key( fragmentType ):
            raise RuntimeError,"Adding existing ftype {0} again!".format( fragmentType )
        
        # For now don't allow adding blocks when the cell has blocks in
        assert not len(self.blocks),"Cannot add library fragments with populated cell!"
        
        # Create fragment
        f = fragment.Fragment( filename, fragmentType )
        
        # Update cell parameters for this fragment
        maxAtomRadius = f.maxAtomRadius()
        if  maxAtomRadius > self.maxAtomRadius:
            self.updateCellSize( maxAtomRadius=maxAtomRadius )
        
        # Add to _fragmentLibrary
        self._fragmentLibrary[ fragmentType ] = f
        
        # create dictionary keyed by endGroup types
        for ft in f.endGroupTypes():
            assert ft not in self._endGroup2LibraryFragment,"Adding existing endGroup type to library: {0}".format(ft)
            self._endGroup2LibraryFragment[ ft ] = fragmentType
        
        return
    
    def attachBlock(self, growEndGroup, staticEndGroup, dihedral=None ):
        """
        Position growBlock so it can bond to blockS, using the given _endGroups
        
        Arguments:
        
        We take responsibility for adding and removing the growBlock from the cell on 
        success or failure
        """
        
        growBlock      = growEndGroup.block()
        staticBlock    = staticEndGroup.block()
        idxStaticBlock = staticBlock.id
        
        staticBlock.positionGrowBlock( staticEndGroup, growBlock, growEndGroup, dihedral=dihedral )
        
        # Now add growBlock to the cell so we can check for clashes
        blockId = self.addBlock( growBlock )
        
        #print "attachBlock got ",blockId, self.blocks
        #self.dump()
        #sys.exit()
        
        # Check it doesn't clash
        if self.checkMove( blockId ) and self.processBonds() > 0:
            self.logger.debug("attachBlock first checkMove returned True")
            return True
        else:
            self.logger.debug("attachBlock first checkMove returned False")
        
        # Only attempt rotation if we're not worried about the dihedral
        # NOTE! - should only bother with the rotation if the cell is relatively crowded - otherwise
        # the multiple rotations are the slowest step
        if not dihedral:
            # Didn't work so try rotating the growBlock about the bond to see if that lets it fit
            
            # Determine the axis and center to rotate about
            blockEndGroup = growBlock.atomCoord( growEndGroup.blockEndGroupIdx )
            blockS = self.blocks[ idxStaticBlock ]
            blockSEndGroup = blockS.atomCoord( staticEndGroup.blockEndGroupIdx )
            axis = blockSEndGroup - blockEndGroup
            center = blockSEndGroup
            
            #step = math.pi/18 # 10 degree increments
            step = math.pi/9 # 20 degree increments
            for angle in util.frange( step, math.pi*2, step):
                
                #print "attachBlock rotating as clash: {}".format(angle*util.RADIANS2DEGREES)
                
                # remove the growBlock from the cell
                self.delBlock(blockId)
                
                # rotate by increment
                self.logger.debug("attachBlock rotating by {0} to {1}".format( math.degrees(step),
                                                                               math.degrees(angle) ) )
                growBlock.rotate( axis, angle, center=center)
                
                # add it and check
                self.addBlock(growBlock)
                
                if self.checkMove( blockId ) and self.processBonds() > 0:
                    self.logger.debug("attachBlock rotate worked")
                    return True
        
        # remove the growBlock from the cell
        self.delBlock(blockId)
        
        return False

    def bondAllowed( self, endGroup1, endGroup2 ):
        """Check if the given bond is permitted from the types of the two fragments
        """
        
        #    self.logger.debug( "checking bondAllowed {0} {1}".format( ftype1, ftype2 ) )
        if endGroup1.fragmentType() == "cap" or endGroup2.fragmentType() == "cap":
            assert False,"NEED TO FIX CAPS!"
            return True
        
        # Get the two fragment types for this bond
        eg1 = endGroup1.type()
        eg2 = endGroup2.type()
        for type1, type2 in self.bondTypes:
            #self.logger.debug("bondTypes {0}".format((type1, type2)) )
            if ( eg1 == type1 and eg2 == type2 ) or ( eg1 == type2 and eg2 == type1 ):
                #self.logger.debug( "BOND RETURN TRUE" )
                return True
            
        #self.logger.debug( "BOND RETURN FALSE" )
        return False
    
    def bondBlock(self, bond ):
        """ Bond the second block1 to the first and update the data structures
        """
        self.logger.debug( "cell bondBlock: {0}".format( bond ) )
        #self.logger.debug("before bond: {0} - {1}".format( bond.idxBlock1, bond.block1._bondObjects) )
        
        # We need to remove the block even if we are bonding to self as we need to recalculate the atomCell list
        self.delBlock( bond.endGroup1.block().id )
        if bond.endGroup1.block() != bond.endGroup2.block():
            self.delBlock( bond.endGroup2.block().id )
        else:
            self.logger.info("self-bonded block1: {0}".format( bond ) )
        
        #bond.block1.bondBlock( bond )
        bond.endGroup1.block().bondBlock( bond )
        #self.logger.debug("after bond: {0} - {1}".format( idxBlock1, block1._bondObjects) )
        idxBlock = self.addBlock( bond.endGroup1.block() )
        return

    def canBond( self,
                 staticBlock,
                 idxStaticAtom,
                 addBlock,
                 idxAddAtom,
                 distance,
                 bondMargin,
                 bondAngleMargin
                ): 
        
        # The check should have been made before this is called on whether the two atoms are endGroup
        
        # Check length
        bond_length = util.bondLength( addBlock.atomSymbol( idxAddAtom ), staticBlock.atomSymbol( idxStaticAtom ) )
        if bond_length < 0:
            raise RuntimeError,"Missing bond distance for: {0}-{1}".format( addBlock.atomSymbol( idxAddAtom ),
                                                                            staticBlock.atomSymbol( idxStaticAtom ) )
        
        # See if the distance between them is acceptable
        #print "CHECKING BOND ATOMS ",bond_length,self.distance( addCoord, staticCoord )
        if  not ( max( 0.1, bond_length - bondMargin ) < distance < bond_length + bondMargin ):
            self.logger.debug( "Cannot bond due to distance: {0}".format( distance ) )
            return False
        
        # Now loop over all endGroups seeing if any of the angles are satisfied
        for staticEndGroup in staticBlock.atomEndGroups( idxStaticAtom ):
            for addEndGroup in addBlock.atomEndGroups( idxAddAtom ):
                
                # EndGroups in the same fragment can never bond
                if staticEndGroup.fragment == addEndGroup.fragment:
                    break
                
                assert staticEndGroup.free() and addEndGroup.free()
                
                # We need to check that we've not already added these endGroups as possible bonds
                if self._endGroupsInPossibleBonds( [ staticEndGroup, addEndGroup ] ):
                    continue
            
                # First check if endGroups of this type can bond - will apply to all so can bail on first fail
                if not self.bondAllowed( staticEndGroup, addEndGroup ):
                    self.logger.debug( "Bond disallowed by bonding rules: {0} : {1}".format( staticEndGroup, 
                                                                                              addEndGroup
                                                                                             ) )
                    return False

                #print "Possible bond for {0} {1} {2} dist {3}".format( idxAddAtom,
                #                                                       idxStaticBlock,
                #                                                       idxStaticAtom, 
                #                                                       self.distance( addCoord, staticCoord ) )
                addCoord      = addBlock.atomCoord( idxAddAtom )
                staticCoord   = staticBlock.atomCoord( idxStaticAtom )
                addCapAtom    = addBlock.atomCoord( addEndGroup.blockCapIdx )
                angle1        = util.angle( addCapAtom, addCoord, staticCoord )
                staticCapAtom = staticBlock.atomCoord( staticEndGroup.blockCapIdx )
                angle2        = util.angle( staticCapAtom, staticCoord, addCoord )
                
                #print "CHECKING ANGLE BETWEEN: {0} | {1} | {2}".format( angleAtom, addCoord, staticCoord )
                #print "{} < {} < {}".format( (self.bondAngle-bondAngleMargin) * util.RADIANS2DEGREES,
                #                             angle * util.RADIANS2DEGREES, 
                #                             (self.bondAngle+bondAngleMargin) * util.RADIANS2DEGREES  )
                
                # Check if atoms are in line (i.e. angle is 0 or 180) within given margin
                if not ( ( 0.0-bondAngleMargin < angle1 < 0.0+bondAngleMargin and \
                           0.0-bondAngleMargin < angle2 < 0.0+bondAngleMargin ) or \
                        ( math.pi-bondAngleMargin < angle1 < math.pi+bondAngleMargin and \
                          math.pi-bondAngleMargin < angle2 < math.pi+bondAngleMargin ) ):
                    self.logger.debug( "Cannot bond due to angles: {0} : {1}".format( math.degrees(angle1),
                                                                                     math.degrees(angle2) ) )
                    continue
                
                self.logger.debug( "Acceptable bond with angles: {0} : {1} | distance {2}".format( math.degrees(angle1),
                                                                                    math.degrees(angle2),
                                                                                    distance ) )
                
                # Create bond object and set the parameters
                bond = buildingBlock.Bond(staticEndGroup,addEndGroup)
                self._possibleBonds.append( bond )
                self.logger.debug( "canBond returning True with bonds: {0}".format( self._possibleBonds ) )
                return True
        
        self.logger.debug( "canBond returning False" )
        return False

    def capBlocks(self, fragmentType=None, filename=None ):
        
        # Create the cap block
        capBlock = buildingBlock.Block( filePath=filename, fragmentType='cap' )
        
        # The endgroup is always the first only endGroup
        capEndGroup = capBlock.freeEndGroups()[0]
        
        # Get a list of blocks - need to do it this way or else we are changing the list of blocks while
        # we iterate through them
        cblocks = self.blocks.copy()
        for blockId, block in cblocks.iteritems():
            
            if block.numFreeEndGroups() == 0:
                self.logger.info("capBlocks block {0} already has no free endGroups".format( blockId ) )
                continue
            else:
                self.logger.info("capBlocks capping {0} endGroups of block {1}".format( block.numFreeEndGroups(),
                                                                                        blockId  )  )
            
            # If there are no free this won't loop
            for endGroup in block.freeEndGroupsFromTypes( [ fragmentType ] ):
                
                cblock = capBlock.copy()
                #print "ADDING CAPBLOCK ",id(cblock)
                block.positionGrowBlock( endGroup, cblock, capEndGroup )
                
                idxBlock = self.addBlock( cblock )
            
                # Test for Clashes with other blocks
                if self.checkMove( idxBlock ) and self.processBonds() > 0:
                    self.logger.info("Capped block {0} endGroup {1}".format( blockId, endGroup ) )
                else:
                    self.logger.critical("Failed to cap block {0} endGroup {1}".format( blockId, endGroup ) )
                    # Unsuccessful so remove the block from cell
                    self.delBlock(idxBlock)
        
        return
    
    def cellAxis(self,A=None,B=None,C=None):
        """
        Set the cell axes
        """
        #self.A = numpy.array( [A,0.0,0.0], dtype=numpy.float64 )
        #self.C = numpy.array( [0.0,0.0,C], dtype=numpy.float64 )
        #self.B = numpy.array( [0.0,B,0.0], dtype=numpy.float64 )
        self.A = float(A)
        self.B = float(B)
        self.C = float(C)
        return

    def checkMove( self, idxAddBlock ):
        clashing = self._checkMove( idxAddBlock )
        if clashing > 0:
            return False
        
        return True
        
    def _checkMove( self, idxAddBlock ):
        """
        get pairs of close atoms
        
        bond=False
        for each pair:
            if are bonding atoms:
                if distance acceptable:
                    if angle acceptable and bond allowed:
                        bond=True
                        add to possible bonds
        
            if not bond:
                # Add atoms to list clash atoms
        
        if possible bonds:
            remove atoms directly bonded to bond atoms from clash atoms
        
        if there are still clash atoms:
            return False
            
        if possible bonds:
            process the bonds in order
        
        """
        
        # Get a list of the close atoms
        close = self.closeAtoms( idxAddBlock )
        #if close:
        #    print "GOT {0} CLOSE ATOMS ".format( len(close) )
        
        if not close:
            self.logger.debug("_checkMove no close contacts")
            # Nothing to see so move along
            return 0
        
        # Get the block1
        addBlock = self.blocks[ idxAddBlock ]
        
        clashAtoms = []
        self._possibleBonds = []
        for ( idxAddAtom, staticBlock, idxStaticAtom, distance ) in close:
            
#             print "CHECKING  ATOMS {}:{} {} -> {}:{} {}= {}".format( idxAddBlock,
#                                                               idxAddAtom,
#                                                               addSymbol,
#                                                               idxStaticBlock,
#                                                               idxStaticAtom,
#                                                               staticBlock.atomSymbol( idxStaticAtom ),
#                                                               distance )
            
            if not ( addBlock.isEndGroup( idxAddAtom ) and \
                     staticBlock.isEndGroup( idxStaticAtom ) and \
                     self.canBond( staticBlock,
                                   idxStaticAtom,
                                   addBlock,
                                   idxAddAtom,
                                   distance,
                                   self.bondMargin,
                                   self.bondAngleMargin,
                                                        )
                    ):
            
                # No bond so just check if the two atoms are close enough for a clash
                if distance <= addBlock.atomRadius( idxAddAtom ) + staticBlock.atomRadius( idxStaticAtom ) + self.atomMargin:
                    #print "CLASH {}->{} = {} < {}".format( addCoord,staticCoord, d, l  )
                    clashAtoms.append( ( staticBlock, idxStaticAtom, addBlock, idxAddAtom ) )
        
        # Now have list of possible bonds and clashes
        
        # Nothing so return True
        if not len( self._possibleBonds ) and not len( clashAtoms ):
            self.logger.debug( "NO BONDS AND NO ATOMS" )
            return 0
        
        # no bonds but a clash - return False
        if not len( self._possibleBonds ) and len( clashAtoms ):
            self.logger.debug( "No bonds and clashing atoms {0}".format( clashAtoms ) )
            return len( clashAtoms )
        
        s = ""
        for b in self._possibleBonds:
            s += str(b)+ " | "
        self.logger.debug( "Bonds {0} and clashing atoms {1}".format( s, clashAtoms ) )
        
        addBlock    = None
        staticBlock = None
        for bond in self._possibleBonds:
            
            b1Block = bond.endGroup1.block()
            b2Block = bond.endGroup2.block()
            
            # We need to remove any clashes with the cap atoms - the added block isn't bonded
            # so the cap atoms aren't excluded
            b1Cap      = bond.endGroup1.blockCapIdx
            b2Cap      = bond.endGroup2.blockCapIdx
            b1EndGroup = bond.endGroup1.blockEndGroupIdx
            b2EndGroup = bond.endGroup2.blockEndGroupIdx
            
            # Also need to remove any clashes of the endGroups with atoms directly bonded to the 
            # opposite endGroup
            b1BondAtoms = b1Block.atomBonded1( b1EndGroup )
            # Only need to do this if the cap was added to the cell
            if not b1Block.invisibleAtom( b1Cap ):
                 b1BondAtoms.remove( b1Cap )
                
            b2BondAtoms    = b2Block.atomBonded1( b2EndGroup )
            # Only need to do this if the cap was added to the cell
            if not b2Block.invisibleAtom( b2Cap ):
                b2BondAtoms.remove( b2Cap )

            toGo = [] # Need to remember indices as we can't remove from a list while we cycle through it
            for i, ( cellBlock, idxCellAtom, addBlock, idxAddAtom) in enumerate(clashAtoms):
                #self.logger.debug("CHECKING {0} {1} {2} {3}".format( idxAddBlock, idxAddAtom, idxStaticBlock, idxStaticAtom ) )
                # Remove any clashes with the cap atoms
                if ( b1Block == cellBlock and idxCellAtom == b1Cap ) or \
                   ( b2Block == addBlock  and idxAddAtom  == b2Cap ):
                    #self.logger.debug("REMOVING {0} {1} {2} {3}".format( idxAddBlock, idxAddAtom, idxStaticBlock, idxStaticAtom ) )
                    toGo.append( i )
                    continue
                
                # remove any clashes with directly bonded atoms
                if (b1Block == cellBlock and idxCellAtom == b1EndGroup and idxAddAtom  in b2BondAtoms ) or \
                   (b2Block == b2Block   and idxAddAtom  == b2EndGroup and idxCellAtom in b1BondAtoms ):
                    #self.logger.info( "REMOVING BOND ATOMS FROM CLASH TEST" )
                    toGo.append( i )
            
            # End of loop so now remove the items
            for i, idx in enumerate(toGo):
                # Need to subtract i as otherwise the indexing is out
                clashAtoms.pop( idx - i )
        
        # If there are any clashing atoms remaining this move failed
        if len( clashAtoms ):
            self.logger.debug( "Got clash atoms {0}".format( clashAtoms ) )
            return len( clashAtoms )
        
        # Got bonds and no clashes
        self.logger.debug( "Checkmove no clashes" )
        return 0
    
    def closeAtoms(self, idxBlock1):
        """
        Find all atoms that are close to the atoms in the given block.
        
        This version is optimised to use numpy to do the PBC distance calculations, so builds up a vector of points and then
        calculates the distances in one go with the distanceV function
        
        Args:
        idxBlock1: index of the block in self.blocks
        
        Returns:
        a list of tuples: (thisAtomIndex, otherBlockIndex, otherAtomIndex, distance) or None if there we no close contacts
        """
        
        # Build up list of the coordinates and an initial contacts array
        c1 = []
        c2 = []
        allContacts=[]
        
        count=0
        block1=self.blocks[ idxBlock1 ]
        for idxAtom1,coord1 in enumerate( block1.iterCoord() ):
            
            # Get the box this atom is in
            key = block1.atomCell[ idxAtom1 ]
            
            # Skip checking dummy atoms
            if key is None:
                continue
            
            #print "Close checking [{}] {}: {} : {}".format(key,idxBlock1,idxAtom1,coord1)
            
            # Get a list of the boxes surrounding this one
            surrounding = self.box3[key]
            
            #For each box loop through all its atoms chekcking for clashes
            for i, sbox in enumerate(surrounding):
                
                #print "KEY ",i,sbox
                # For each box, get the list of the atoms as (block,coord1) tuples
                # Check if we have a box with anything in it
                try:
                    alist = self.box1[ sbox ]
                except KeyError:
                    continue
                
                for (idxBlock2, idxAtom2) in alist:
                    
                    # Check we are not checking ourself - need to check block index too!
                    if idxBlock1 == idxBlock2:
                        continue
                    
                    block2 = self.blocks[idxBlock2]
                    
                    c1.append( coord1 )
                    c2.append( block2.atomCoord( idxAtom2 ) )
                    allContacts.append( ( idxAtom1, block2, idxAtom2 ) )
                    count += 1
        
        # Have list so now calculate distances
        if count == 0:
            return []
        
        # Calculate array of distances for all coordinates
        distances = self.distance(c1, c2)
        
        # prune contacts array according to distances
        return [ ( c[0], c[1], c[2], distances[i] ) for i, c in enumerate( allContacts ) if distances[i] < self.boxSize ]

    def cellEndGroupPair(self, cellEndGroups=None):
        """Return two free endGroups from two different blocks in the cell"""
        
        #
        # Get a list of available free endGroups in the cell
        #
        endGroupTypes2Block = self.endGroupTypes2Block()
        if len(endGroupTypes2Block.keys()) == 0:
            raise RuntimeError,"No available endGroups in the cell"
        #
        # If the user supplied a list of cellEndGroups we use this to determine what can bond - 
        # other wise we use all available endGroups
        allTypes = endGroupTypes2Block.keys() # just for informing the user
        if cellEndGroups is not None:
            if isinstance(cellEndGroups,str):
                cellEndGroups = [ cellEndGroups ]
            cellEndGroups = set( cellEndGroups )
        else:
            cellEndGroups = set(endGroupTypes2Block.keys()) 
        #
        # We create a dictionary mapping which cell endGroups can bond to which
        # This is basically a truncated _bondTable with any endGroups removed that aren't present
        #
        cell2cell = copy.copy(self._bondTable)
        for eg in self._bondTable:
            if eg not in cellEndGroups:
                # First remove all references in the keys
                del cell2cell[ eg ]
            else:
                # The key is valid so remove any missing endGroups from the values
                ceg = cellEndGroups.intersection( cell2cell[ eg ] )
                # Need to check there are some other types that this can bond to, but also there is at least
                # one other block if both are of the same type
                # NB the strange next/iter thing is the only way to get an item from the set
                if len( ceg ) == 0 or \
                   (len( ceg ) == 1 and eg == next(iter(ceg)) and len( endGroupTypes2Block[ eg ] ) < 2 ):
                    # No valid blocks that could bond with this endGroup so delete the entire key
                    del cell2cell[ eg ]
                else:
                    cell2cell[ eg ] = ceg
                    
        if len(cell2cell.keys()) == 0:
            raise RuntimeError,"No endGroups of types {0} are available to bond from {1}".format( cellEndGroups, allTypes )
        
        # At this point we assume we can definitely bond at least 2 blocks
        self.logger.debug("cellEndGroupPair got cell/library endGroups: {0}".format(cell2cell) )
        
        # Select a random block/endGroup from the list
        eg1Type = random.choice( cell2cell.keys() )
        block1 = random.sample( endGroupTypes2Block[ eg1Type ], 1 )[0]
        endGroup1 = block1.randomEndGroup( endGroupTypes=[eg1Type] )
        
        # Pick a random endGroup type that can bond to this
        eg2Type = random.sample( cell2cell[ eg1Type ], 1 )[0]
        
        # Select a random block/endGroup of that type
        # (REM: need to remove the first block from the list of possibles hence the difference thing
        block2 = random.sample( endGroupTypes2Block[ eg2Type ].difference(set([block1])), 1 )[0]
        endGroup2 = block2.randomEndGroup( endGroupTypes=[eg2Type] )
        
        self.logger.debug("cellEndGroupPair returning: {0} {1}".format(endGroup1.type(),endGroup2.type()) )
        return endGroup1, endGroup2

    def dataDict( self, fragmentType=None ):
        """Get the data for the current cell
        """

        # For now use a dictionary to hold all the data
        d = {
        'angleLabel' : [], 
        'angle' : [], 
        'bondLabel' : [], 
        'bond' : [], 
        'body' : [], 
        'charge' : [], 
        'coord' : [], 
        'diameter' : [], 
        'dihedral' : [],  # Used for impropers too
        'dihedralLabel' : [], 
        'fragmentBond' : [], 
        'fragmentBondLabel' : [], 
        'label' : [], 
        'mass' : [], 
        'symbol' : [], 
        'type' : [], 
        }
        
        def b2g( atomIdx, atomMap, atomCount ):
            """Map block atom index to global index in list of all atoms in the cell
            Need to know how long this block is  - len( atomMap )
            subtract this from the atomCount as this is where the data for this block starts
            """
            return atomCount - len( atomMap ) + atomMap[ atomIdx ]
        
        # Cell parameters
        d['A'] = self.A
        d['B'] = self.B
        d['C'] = self.C
        
        atomCount=0 # Tracks overall number of atoms - across blocks
        fragCount=-1 # Tracks fragments (bodies) count starts from 1
        for idxBlock, block in self.blocks.iteritems():
            
            # Coordinates and bodies
            j = 0 # Tracks the atoms within a block
            atomMap = {} # For each block map the internal block index to the one without capAtoms
            lastFrag = (-1, -1)
            for i, ( fragment, atomIdx ) in enumerate( block._dataMap ):
                
                # We are only outputting one of the framgment types so ignore the others
                if fragmentType is not None and fragment.type() != fragmentType:
                    continue
                
                # Increment body count
                if lastFrag != ( fragment, fragment.body( atomIdx ) ):
                    lastFrag = ( fragment, fragment.body( atomIdx ) )
                    fragCount += 1
                    
                # This is how we keep the cap atoms in the data structures but avoid outputting
                # them to Hoomdblue
                if block.ignoreAtom( i ):
                    continue
                else:
                    atomMap[ i ] = j

                d['body'].append( fragCount ) 
                d['coord'].append( copy.copy( block.atomCoord( i ) ) )
                
                # For time being use zero so just under LJ potential & bond
                #diameter += "{0}\n".format( frag._atomRadii[ k ] )
                d['charge'].append( block.atomCharge( i ) )
                # HACK
                if block.atomSymbol( i ) == 'j':
                    d['diameter'].append( 0.1 )
                else:
                    d['diameter'].append( 0.1 )
                d['label'].append( block.atomLabel( i ) )
                d['mass'].append( block.atomMass( i ) )
                d['symbol'].append( block.atomSymbol( i ) )
                d['type'].append( block.atomType( i ) )
                
                j += 1
                atomCount += 1
            
            # Now have overall atom count and map of atoms within block
            
            # Get all internal fragment bonds
            fbonds = block.fragmentBonds()
            for i1, i2 in fbonds:
                try:
                    d['fragmentBond'].append( ( b2g( i1, atomMap, atomCount ), b2g( i2, atomMap, atomCount ) ) )
                    
                    atom1label = block.atomType( i1 )
                    atom2label = block.atomType( i2 )
                    # Sort so the order always the same
                    l = sorted( ( atom1label, atom2label ) )
                    d['fragmentBondLabel'].append( "{0}-{1}".format( l[ 0 ], l[ 1 ] ) )
                except KeyError:
                    # This is a bond that is to a bondedCapAtom so ignored
                    pass
            
            # If we're only outputting one fragment type, bonding etc will be screwed up so skip this
            if fragmentType is not None:
                continue
            
            # Collect all bond information
            for bond in block.bonds():
                
                endGroup1Idx = bond.endGroup1.blockEndGroupIdx
                endGroup2Idx = bond.endGroup2.blockEndGroupIdx
                endGroup1Label = block.atomType( endGroup1Idx )
                endGroup2Label = block.atomType( endGroup2Idx )
                
                # Sort so the order always the same
                l = sorted( ( endGroup1Label, endGroup2Label ) )
                d['bondLabel'].append( "{0}-{1}".format( l[ 0 ], l[ 1 ] ) )
                d['bond'].append( ( b2g( endGroup1Idx, atomMap, atomCount ),
                                    b2g( endGroup2Idx, atomMap, atomCount ) ) )
                
                # Atoms connected to the endGroup that we need to specify as connected so we add as angles
                for batom in block.atomBonded1( endGroup1Idx ):
                    # The opposite endGroup is included in the list bonded to an endGroup so skip
                    if batom == endGroup2Idx:
                        continue
                    a = ( b2g( batom, atomMap, atomCount ),
                          b2g( endGroup1Idx, atomMap, atomCount ),
                          b2g( endGroup2Idx, atomMap, atomCount ) )
                    if a not in d['angle']:
                        d['angleLabel'].append( "{0}-{1}-{2}".format( block.atomType( batom ),
                                                                      endGroup1Label, 
                                                                      endGroup2Label ) )
                        d['angle'].append( a )
                    else:
                        self.logger.debug( "Skipping angle {0}".format( a ) )
                    
                for batom in block.atomBonded1( endGroup2Idx ):
                    # The opposite endGroup is included in the list bonded to an endGroup so skip
                    if batom == endGroup1Idx:
                        continue
                    a = ( b2g( endGroup1Idx, atomMap, atomCount ),
                          b2g( endGroup2Idx, atomMap, atomCount ),
                          b2g( batom, atomMap, atomCount ) )
                    if a not in d['angle']:
                        d['angleLabel'].append( "{0}-{1}-{2}".format( endGroup1Label,
                                                                      endGroup2Label,
                                                                      block.atomType( batom ) ) )
                        d['angle'].append( a )
                    else:
                        self.logger.debug( "Skipping angle {0}".format( a ) )

#                 useAngle=False
#                 if useAngle:
#                     # FIX!! IF NEEDED
#                     if ( bond.endGroup1.blockCapIdx != endGroup1Idx and bond.endGroup2.blockCapIdx != endGroup2Idx ):
#                         d['angleLabel'].append( "aatom" )
#                         d['angle'].append( ( bond.endGroup1.blockCapIdx + atomCount, endGroup1Idx + atomCount, endGroup2Idx + atomCount ) )
#                          
#                         d['angleLabel'].append( "aatom" )
#                         d['angle'].append( ( endGroup1Idx + atomCount, endGroup2Idx + atomCount, bond.endGroup2.blockCapIdx + atomCount ) )

                #
                # Dihedrals
                #
                for dindices in block.dihedrals( endGroup1Idx, endGroup2Idx ):
                    dlabel = "{0}-{1}-{2}-{3}".format( block.atomType( dindices[0] ),
                                                       block.atomType( dindices[1] ),
                                                       block.atomType( dindices[2] ), 
                                                       block.atomType( dindices[3] )
                                                                                     )
                     
                     
                    dihedral = ( b2g( dindices[0], atomMap, atomCount ), 
                                 b2g( dindices[1], atomMap, atomCount ), 
                                 b2g( dindices[2], atomMap, atomCount ),
                                 b2g( dindices[3], atomMap, atomCount )
                               )
                     
                    d['dihedralLabel'].append( dlabel )
                    d['dihedral'].append( dihedral )

        assert len(d['coord']) > 0,"Found no atoms for fragmentType {0}".format( fragmentType )

        return d

    def delBlock(self,blockId):
        """
        Remove the block with the given index from the cell
        """
        
        #print "Deleting block: {} from {}".format(blockId,self.blocks.keys())
        block =  self.blocks[ blockId ]
        
        # Remove each atom from the list
        keys = []
        for iatom, key in enumerate( block.atomCell ):
            
            # Skip dummy atoms
            if key == None:
                continue
            
            #print "removing ",blockId,iatom,key
            keys.append(key)
            #print "B4 ",self.box1[key]
            self.box1[key].remove( ( blockId, iatom ) )
            #print "AFTER ",self.box1[key]
            
        # Now remove any empty keys and corresponding surrounding boxes
        # Might think about keeping the surrounding boxes as they could be use by other atoms?
        #print "now checking keys"
        for key in keys:
            if self.box1.has_key(key) and len( self.box1[key] ) == 0:
                del self.box1[key]
                del self.box3[key]
        del self.blocks[blockId]
        del block
        
        return 
        
    def density(self):
        """The density of the cell"""
        d = ( sum( [ b.mass() for b in self.blocks.itervalues() ] ) / ( self.A * self.B * self.C ) )
        return d * (10/6.022)

#    def directedShimmy(self, nsteps=100, nmoves=50):
#        """ Shuffle the molecules about making bonds where necessary for nsteps
#        minimoves is number of sub-moves to attempt when the blocks are close
#        """
#        
#        #For writing out our progress
#        filename= "SHIMMY_0.xyz"
#        self.writeXyz( filename )
#        
#        for step in range( nsteps ):
#            
#            if len(self.blocks) == 1:
#                print "NO MORE BLOCKS TO BOND _ HOORAY!"
#                return
#            
#            #if not step % 100:
#            print "Step: {}".format(step)
#            print "BLOCKS",self.blocks.keys()
#            print "KEYS ",self.box1
#            filename = util.newFilename(filename)
#            self.writeXyz( filename )
#            
#            imove_block, istatic_block = self.randomBlockId(count=2)
#            move_block = self.blocks[imove_block]
#            static_block = self.blocks[istatic_block]
#            
#            # Copy the original coordinates so we can reject the move
#            # we copy the whole block so we don't need to recalculate
#            # anything - not sure if this quicker then saving the _coords & updating tho
#            orig_block = copy.deepcopy( move_block )
#            
#            # Calculate how far to move
#            circ = move_block.radius() + static_block.radius()
#            radius = (circ/2) + self.atomMargin
#            
#            for move in range( nmoves ):
#                
#                # Remove the block from the cell so we don't check against itself
#                self.delBlock(imove_block)
#                
#                self.randomMoveAroundCenter( move_block, static_block.centroid(), radius )
#                
#                #Add the block so we can check for clashes/bonds
#                imove_block = self.addBlock(move_block)
#                
#                # Test for Clashes with other molecules
#                ok = self.checkMove( imove_block )
#                
#                # Break out if no clashes
#                if ok:
#                    print "Successful move ",move
#                    break
#                
#                # Put it back where we got it from
#                self.delBlock(imove_block)
#                imove_block = self.addBlock(orig_block)
#                
#                #End move loop
#            #End step loop
#        #End shimmy
#        return

    def XdistanceV(self, x0, x1):
        """Calculate vectors of distances between 2 vectors of points.
        http://stackoverflow.com/questions/11108869/optimizing-python-distance-calculation-while-accounting-for-periodic-boundary-co
        """
        dimensions = numpy.array( [ self.A, self.B, self.C ] )
        x0 = numpy.array( x0 )
        x1 = numpy.array( x1 )
        delta = numpy.abs(x0 - x1)
        delta = numpy.where(delta > 0.5 * dimensions, dimensions - delta, delta)
        return numpy.sqrt((delta ** 2).sum(axis=-1))

    def distance(self, v1, v2):
        """Distance with numpy taking PBC into account
        This works either with 2 points or a vector of any number of points
        Adapted from: http://stackoverflow.com/questions/11108869/optimizing-python-distance-calculation-while-accounting-for-periodic-boundary-co
        Changed so that it can cope with distances across more than one cell
        """
        assert len(v1) > 0 and len(v2) > 0, "distance needs vectors!"
        dimensions = numpy.array( [ self.A, self.B, self.C ] )
        delta = numpy.array(v1) - numpy.array(v2)
        delta = numpy.remainder( delta, dimensions )
        delta = numpy.where(numpy.abs(delta) > 0.5 * dimensions, delta - numpy.copysign( dimensions, delta ), delta)
        return numpy.sqrt((delta ** 2).sum(axis=-1))

    def distanceSimple(self, v1, v2):
        """
        my attempt to do PBC
        """
        dx = v2[0] % self.A - v1[0] % self.A
        if math.fabs(dx) > self.A * 0.5:
            dx = dx - math.copysign( self.A, dx)
            
        dy = v2[1] % self.B - v1[1] % self.B
        if math.fabs(dy) > self.B * 0.5:
            dy = dy - math.copysign( self.B, dy)
            
        dz = v2[2] % self.C - v1[2] % self.C
        if math.fabs(dz) > self.C * 0.5:
            dz = dz - math.copysign( self.C, dz)
            
        return math.sqrt( dx*dx + dy*dy + dz*dz )

    def dump(self, prefix="step", addCount=True ):
        """Write out our current state"""
        
        if addCount:
            self._fileCount+=1
            prefix=prefix+"_{0}".format(self._fileCount)
            
        
        data = self.dataDict()
            
        #self.writeXyz(prefix+".xyz",data=data, periodic=False)
        #self.writeXyz(prefix+"_P.xyz",data=data, periodic=True)
        #self.writeCar(prefix+"_P.car",data=data,periodic=True)
        #self.writeCml(prefix+"_PV.cml", data=data, allBonds=True, periodic=True, pruneBonds=True)
        #self.writeCml(prefix+".cml", data=data, allBonds=True, periodic=False, pruneBonds=False)
        
        # This is too expensive at the moment
        #self.writeHoomdXml( xmlFilename=prefix+"_hoomd.xml", data=data)
        
        self.writePickle(prefix+".pkl")
        return

    def _endGroupsInPossibleBonds(self, endGroups ):
        """Check if any of the endGroups are already in the list of possible bonds"""
        eg = set()
        for b in self._possibleBonds:
            eg.update( [ b.endGroup1, b.endGroup2 ] )
        return bool( eg.intersection( frozenset( endGroups ) ) )

    def endGroupTypes2Block(self ):
        """Return a dictionary mapping free endGroup types to a list of the blocks
        
        We don't check if any are available just return an empty dictionary if not
        """
        endGroupTypes2Block = {}
        for idxBlock, block in self.blocks.iteritems():
            #numFreeEndGroups += block.numFreeEndGroups()
            # Get a list of the free endGroup types in the block
            for endGroupType in block.freeEndGroupTypes():
                if endGroupType not in endGroupTypes2Block:
                    endGroupTypes2Block[ endGroupType ] = set()
                endGroupTypes2Block[ endGroupType ].add( block )
        return endGroupTypes2Block

    def fragmentTypes(self):
        ft = {}
        for b in self.blocks.itervalues():
            d = b.fragmentTypeDict()
            for k,v in d.iteritems():
                try:
                    ft[ k ] += v
                except:
                    ft[ k ] = v
        return ft
    
    def fragmentTypeFromEndGroupType(self, endGroupType):
        return endGroupType.split( self.ENDGROUPSEP)[0]

    def fromHoomdblueSystem(self, system ):
        """Reset the particle positions from hoomdblue system"""
    
        assert system,"No system!"
        
        # Should really check HOOMD version but...
        if hasattr(system.box,"Lx"):
            Lx = system.box.Lx
            Ly = system.box.Ly
            Lz = system.box.Lz
        else:
            Lx = system.box[0]
            Ly = system.box[1]
            Lz = system.box[2]
        
        if self.minCell:
            # Need to take unwrapped coords and put back into 
            # the original cell
            assert self.minCellData
        
        # Read back in the particle positions
        atomCount=0
        for block in self.blocks.itervalues():
            for k in range( block.numAllAtoms() ):
                
                if block.ignoreAtom( k ):
                    # We didn't write out these so don't read back in 
                    continue
                
                p = system.particles[ atomCount ]
                xt, yt, zt  = p.position
                ix, iy, iz = p.image
                
                if self.minCell:
                    
                    assert self.minCellData['A'] == Lx
                    assert self.minCellData['B'] == Ly
                    assert self.minCellData['C'] == Lz
                    
                    # Unwrap the coordinates in the centered cell
                    x = util.unWrapCoord( xt, ix, Lx, centered=False )
                    y = util.unWrapCoord( yt, iy, Ly, centered=False )
                    z = util.unWrapCoord( zt, iz, Lz, centered=False )
                
                    # Need to take unwrapped coords and put back into 
                    # the original cell
                    x = x + Lx/2 + self.minCellData['minA']
                    y = y + Ly/2 + self.minCellData['minB']
                    z = z + Lz/2 + self.minCellData['minC']
                    
                    # Not the case as could be in a different image
                    #assert x >= 0 and x <= self.A
                    #assert y >= 0 and y <= self.B
                    #assert z >= 0 and z <= self.C
                else:
                    x = util.unWrapCoord( xt, ix, Lx, centered=True )
                    y = util.unWrapCoord( yt, iy, Ly, centered=True )
                    z = util.unWrapCoord( zt, iz, Lz, centered=True )
                
                block.atomCoord( k )[0] = x
                block.atomCoord( k )[1] = y
                block.atomCoord( k )[2] = z

                atomCount += 1
               
        if atomCount != len( system.particles ):
            raise RuntimeError,"Read {0} positions but there were {1} particles!".format( atomCount, len( system.particles ) )
        
        # Now have the new coordinates, so we need to put the atoms in their new cells
        self.repopulateCells()
        
        return
        
    def fromCar(self, carFile ):
        """ Read in an xyz file containing a cell and recreate the cell object"""
        reading = True
        coords = []
        atomTypes = []
        symbols = []
        #charges = []
        with open( carFile, "r" ) as f:
            
            # skip first line
            f.readline()
            
            # 2nd states whether PBC: PBC=OFF
            pbc, state = f.readline().strip().split("=")
            assert pbc.strip() == "PBC"
            state=state.strip()
            nskip=3
            if state.upper() == "OFF":
                nskip=2 
            
            for i in range(nskip):
                f.readline()
            
            count=0
            while reading:
                line = f.readline()
                
                line = line.strip()
                if not line:
                    print "END OF CAR WITH NO END!!!"
                    break
                fields = line.split()
                label = fields[0]
                
                # Check end of coordinates
                if label.lower() == "end":
                    reading=False
                    break
                
                #labels.append( label )
                coords.append( numpy.array(fields[1:4], dtype=numpy.float64 ) )
                atomTypes.append( fields[6] )
                symbols.append( fields[7] )
                #charges.append( float( fields[8] ) )
                
                count+=1
        # END READ
        
        count = 0
        for i, (idxBlock, block) in enumerate( self.blocks.iteritems() ):
            #for j, ( fragment, atomIdx ) in enumerate( block._dataMap ):
            for j, coord in enumerate( block.iterCoord() ):
                if block.atomSymbol( j ) != symbols[ count ] or block.atomType( j ) != atomTypes[ count ]:
                    raise RuntimeError, "Error reading coords back in: {0} {1} {2} -> {3} {4} {5}".format( symbols[ count ],
                                                                                            atomTypes[ count ],
                                                                                            coords[ count ],
                                                                                            block.atomSymbol( j ),
                                                                                            block.atomType( j ),
                                                                                            block.atomCoord( j )
                                                                                            )
                block.setCoord( j, coords[ count ] )
                count += 1
                
        if count != len( coords ):
            raise RuntimeError,"Did not read in correct number of coordinates: {0} -> {1}".format( i+ j, len(coords) )
            
        return
            
    def fromPickle(self, pickleFile ):
        
#         if self.A == None or self.B == None or self.C == None:
#             raise RuntimeError,"Need to set cell A, B & C parameters before load!"
        
        with open( pickleFile, 'r' ) as f:
            cell = cPickle.load( f )
            
        
        print "cell is ",cell
            
        assert cell
        
        self = cell
        
        return
    
    def _readXyz(self, xyzFile ):
        """"Read in an xyz file containing a cell - cell axes is title line and 
        atoms are written out with their labels.
        This routine sets the axes and returns a list of the labels and coordinates
        """
        
        # Each block is a list of [label, _coords
        blocks = []
        labels=[]
        coords=[]
        
        with open( xyzFile ) as f:
            
            # First line is number of atoms
            line = f.readline()
            natoms = int(line.strip())
            
            # Title line contains cell info
            line = f.readline().strip()
            fields = line.split(":")
            
            if fields[0] != "Axes":
                raise RuntimeError, "TITLE LINE NEEDS TO CONTAIN THE AXES"
            
            A,B,C = None, None, None
            # bit hacky but I'm lazy...
            exec( "A = {}".format(fields[1]) )
            exec( "B = {}".format(fields[2]) )
            exec( "C = {}".format(fields[3]) )
            
            self.cellAxis(A=A, B=B, C=C)
            
            lastBlock=-1
            for _ in range(natoms):
                
                line = f.readline().strip()
                fields = line.split()
                label = fields[0]
                
                # Determine block from last bit of label
                labelf = label.split("_")
                iblock = int( labelf[-1].split("#")[1] )
                
                if iblock != lastBlock:
                    # Add new block
                    if lastBlock != -1:
                        blocks.append( (labels,coords) )
                    lastBlock = iblock
                    labels=[]
                    coords=[]
                
                if len(labelf) == 2:
                    label = labelf[0]
                elif len(labelf) == 3:
                    label = labelf[0]+"_"+labelf[1]
                else:
                    raise RuntimeError,"HELLLP"
                
                labels.append(label) 
                coords.append( numpy.array(fields[1:4], dtype=numpy.float64) )
        
        # Add the last block
        blocks.append( (labels,coords) )
        
        return blocks

    def getInitBlock( self, fragmentType=None ):
        """Return an initBlock"""
        
        if fragmentType is None:
            # Need to determine the fragmentType from the endGroupType
            fragmentType = random.choice( list( self._fragmentLibrary.keys() ) )
        
        # sanity check
        if not self._fragmentLibrary.has_key( fragmentType ):
            raise RuntimeError, "Asking for a non-existing initBlock type: {0}".format( fragmentType )
        
        # Copy the init fragment
        f = self._fragmentLibrary[ fragmentType ].copy()
        
        return buildingBlock.Block( initFragment=f )

    def growBlocks(self,
                   toGrow,
                   cellEndGroups=None,
                   libraryEndGroups=None,
                   endGroupType=None,
                   dihedral=None,
                   maxTries=50 ):
        """
        Add toGrow new blocks to the cell based on the initBlock
        
        Args:
        toGrow: number of blocks to add
        endGroupType: the type of block to add
        dihedral: the dihedral angle about the bond (3rd column in ambi file)
        maxTries: number of tries to add before we give up
        """

        self.logger.info( "Growing {0} new blocks".format( toGrow ) )
        
        assert len(self.blocks),"Need to seed blocks before growing!"
        
        if endGroupType:
            self.logger.warn('endGroupType is deprecated! Use cellEndGroups/libraryEndGroups instead')
            assert not cellEndGroups or libraryEndGroups
            libraryEndGroups = endGroupType
        
        if dihedral:
            # Convert dihedral to radians
            dihedral = math.radians( dihedral )
        
        added=0
        tries=0
        while added < toGrow:
            
            if tries >= maxTries:
                self.logger.critical("growBlocks - exceeded maxtries {0} when joining blocks!".format( maxTries ) )
                return added
            
            if self.numFreeEndGroups() == 0:
                self.logger.critical("growBlocks got no free endGroups!")
                return added
            
            # Select two random blocks that can be bonded
            #initBlock, newEG, idxStaticBlock, staticEG = self.randomInitAttachments( endGroupType=endGroupType )
            cellEndGroup, libraryEndGroup = self.libraryEndGroupPair(cellEndGroups=cellEndGroups,
                                                                     libraryEndGroups=libraryEndGroups)
            
            # Apply random rotation in 3 axes to randomise the orientation before we align
            libraryBlock = libraryEndGroup.block()
            libraryBlock.randomRotate( origin=self.origin )
            
            # Try and attach it
            ok =  self.attachBlock( libraryEndGroup, cellEndGroup, dihedral=dihedral )
            
            if ok:
                added +=1
                self.logger.info("growBlocks added block {0} after {1} tries.".format( added, tries ) )
                self.analyse.stop('grow', d={'num_tries':tries})
                #print "GOT BLOCK ",[ b  for b in self.blocks.itervalues() ][0]
                tries = 0
            else:
                # del initBlock?
                tries += 1

        self.logger.info("After growBlocks numBlocks: {0}".format( len(self.blocks) ) )
        
        return added

    def joinBlocks(self, toJoin, cellEndGroups=None, dihedral=None, maxTries=100 ):
        """
        Try joining number of blocks together
        
        Args:
        toJoin: number of blocks to join
        maxTries: the maximum number of moves to try when joining
        """
        
        self.logger.info( "Joining {0} new blocks".format( toJoin ) )
        
        if dihedral:
            # Convert dihedral to radians
            dihedral = math.radians( dihedral )

        added=0
        tries=0
        while added < toJoin:
            
            if len ( self.blocks ) == 1:
                self.logger.info("joinBlocks Hooray! - no more blocks to join!")
                return added
                
            if tries > maxTries:
                self.logger.critical("joinBlocks - exceeded maxtries when joining blocks!")
                return added
            
            if self.numFreeEndGroups() == 0:
                self.logger.critical("joinBlocks got no free endGroups!")
                return added
            
            # Select 2 random blocks that can be joined
            moveEndGroup, staticEndGroup = self.cellEndGroupPair(cellEndGroups=cellEndGroups)
            
            # Copy the original block so we can replace it if the join fails
            moveBlock = moveEndGroup.block()
            idxMoveBlock = moveBlock.id
            blockCopy = moveBlock.copy()
            
            # Remove from cell so we don't check against itself and pick a different out
            self.delBlock( idxMoveBlock )
    
            self.logger.debug( "joinBlocks calling attachBlock: {0} {1}".format( moveEndGroup, staticEndGroup ) )
            
            # now attach it
            ok = self.attachBlock( moveEndGroup, staticEndGroup, dihedral=dihedral )
            if ok:
                added+=1
                self.logger.info("joinBlocks joined block {0} after {1} tries.".format( added, tries ) )
                tries=0
            else:
                # Put the original block back in the cell
                self.addBlock( blockCopy )
                tries+=1
        
        self.logger.info("After joinBlocks numBlocks: {0}".format( len(self.blocks) ) )
        
        return added
    
    def libraryEndGroupPair(self, cellEndGroups=None, libraryEndGroups=None ):
        """Return a fee endGroup from the cell and one from the library that can be bonded to it."""
        
        #
        # Get a list of available free endGroups in the cell
        #
        endGroupTypes2Block = self.endGroupTypes2Block()
        if len(endGroupTypes2Block.keys()) == 0:
            raise RuntimeError,"No available endGroups in the cell"
        #
        # We create a dictionary mapping cell endGroups to possible libraryEndGroups
        #
        cell2Library = {}
        for ceg in endGroupTypes2Block.keys():
            # We add those endGroup types that can be bonded to that are also in the library
            leg = self._bondTable[ ceg ].intersection( self._endGroup2LibraryFragment.keys() )
            if len(leg) > 0:
                cell2Library[ ceg ] = leg
        
        # Check that there are some available
        if len(cell2Library.keys()) == 0:
            raise RuntimeError,"No library fragments available to bond under the given rules: {0}".format(endGroupTypes2Block.keys())
        
        #
        # If the user supplied a list of cellEndGroups we prune the list of cell endGroups to those that are in this list
        #
        if cellEndGroups is not None:
            # Convert to a set - make sure is a list first
            if isinstance(cellEndGroups, str):
                cellEndGroups = [ cellEndGroups ]
            for ceg in cell2Library.keys():
                if ceg not in cellEndGroups:
                    del cell2Library[ ceg ]
            
            if len(cell2Library.keys()) == 0:
                raise RuntimeError,"No free endGroups of types in cellEndGroups: {0} - {1}".format(cellEndGroups,
                                                                                                   endGroupTypes2Block.keys())
        
        #
        # If the user supplied a list of libraryEndGroups we remove any library endGroups that aren't in the list
        #
        if libraryEndGroups is not None:
            # Convert to a set - make sure is a list first
            if isinstance(libraryEndGroups, str):
                libraryEndGroups = [ libraryEndGroups ]
            libraryEndGroups = set( libraryEndGroups ) # Save old so we can warn user and also find matching
            tmp = cell2Library
            cell2Library = {}
            for ceg, leg in tmp.iteritems():
                # Only select those that are in the libraryEndGroups
                pleg = libraryEndGroups.intersection( leg )
                if len(pleg) > 0:
                    cell2Library[ ceg ] = pleg
            
            if not len(cell2Library.keys()):
                raise RuntimeError,"No library fragments of type {0} available to bond under the given rules: {0}".format(libraryEndGroups,endGroupTypes2Block.keys())

        self.logger.debug("libraryEndGroupPair got cell/library endGroups: {0}".format(cell2Library) )
        
        # Now we can pick a random endGroup from the cell, get the corresponding library group
        cellEgT = random.choice( cell2Library.keys() )
        
        # First get a block that contains this type of endGroup
        # Need to use sample as sets don't support random.choice
        cellBlock = random.sample( endGroupTypes2Block[ cellEgT ], 1 )[0]
        
        # Now select a random endGroup of that type from it
        cellEndGroup = cellBlock.randomEndGroup( endGroupTypes=[cellEgT] )
        
        # Now get a corresponding library endGroup
        # We need to pick a random one of the types that we can bond to that is also in libraryTypes
        libEgT = random.sample( cell2Library[ cellEgT ], 1)[0]
        
        # Now determine the fragmentType and create the block and fragment
        fragmentType = self._endGroup2LibraryFragment[ libEgT ]
        libraryBlock = self.getInitBlock( fragmentType=fragmentType )
        
        # now get the endGroup
        libraryEndGroup = libraryBlock.randomEndGroup( endGroupTypes=[libEgT] )
        
        # Return them both - phew!
        self.logger.debug("libraryEndGroupPair returning: {0} {1}".format(cellEndGroup.type(),libraryEndGroup.type()) )
        return cellEndGroup, libraryEndGroup

    def numBlocks(self):
        return len( self.blocks)
    
    def numFragments(self):
        return sum( [ len(b._fragments) for b in self.blocks.itervalues() ] )
    
    def numFreeEndGroups(self):
        return sum( [ b.numFreeEndGroups() for b in self.blocks.itervalues() ] )
    
    def numAtoms(self):
        return sum( [ b.numAtoms() for b in self.blocks.itervalues() ] )
    
    def optimiseGeometry(self,
                         xmlFilename="hoomdOpt.xml",
                         doDihedral=False,
                         doImproper=False,
                         **kw ):
        """Optimise the geometry with hoomdblue"""
        
        # HACK
        minCell=False
        self.minCell = minCell
        
        if doDihedral and doImproper:
            raise RuntimeError,"Cannot have impropers and dihedrals at the same time"

        optimiser = opt.HoomdOptimiser()
        if 'rCut' in kw:
            self.rCut = kw['rCut']
        else:
            self.rCut = optimiser.rCut
        
        # Write out HoomdBlue xml file & get parameters
        self.writeHoomdXml( xmlFilename=xmlFilename,
                            doDihedral=doDihedral,
                            doImproper=doImproper )
        
        self.logger.info( "Running optimisation" )
        d = {}
        ok = optimiser.optimiseGeometry( xmlFilename,
                                             doDihedral=doDihedral,
                                             doImproper=doImproper,
                                             d=d,
                                              **kw )
        self.analyse.stop('optimiseGeometry', d )
                
        if ok:
            self.logger.info( "Optimisation succeeded" )
            self.fromHoomdblueSystem( optimiser.system )
            return True
        else:
            self.logger.critical( "Optimisation Failed" )
            return False

    def positionInCell(self, block):
        """Make sure the given block is positioned within the cell"""
        
        bradius = block.radius()
        
        oradius = bradius + ( 2 * self.boxMargin )
        
        # Check there is enough space
        if oradius >= self.A or oradius >= self.B or oradius >= self.C:
            raise RuntimeError, "Cannot fit block with radius {0} into cell [{1}, {2}, {3}]!".format( bradius,
                                                                                                      self.A,
                                                                                                      self.B,
                                                                                                      self.C
                                                                                                       )
            
        # get a range for x, y and z that would fit the block in the cell, pick random values within that
        # and stick the block there
        x = random.uniform( bradius+self.boxMargin, self.A-bradius-self.boxMargin )
        y = random.uniform( bradius+self.boxMargin, self.B-bradius-self.boxMargin )
        z = random.uniform( bradius+self.boxMargin, self.C-bradius-self.boxMargin )
        
        coord = numpy.array([x,y,z], dtype=numpy.float64 )
        
        block.translateCentroid( coord )
        
        self.logger.debug( "positionInCell block moved to: {0}".format( block.centroid() ) )
        
        return

    def prepareHoomdData(self,data=None):
        # Get the data on the blocks
        if data is None:
            data = self.dataDict()
        
        if self.minCell:
        
            # Find the extent of the block in all 3 dimensions
            # remember max, min in all 3 dimemsions
            d = { 
                 'maxA'   : 0,
                 'minA'   : 10000,
                 'maxB'   : 0,
                 'minB'   : 10000,
                 'maxC'   : 0,
                 'minC'   : 10000,
                 'border' : self.rCut
                 }
            
            for i in range( len( data['coord'] ) ):
                coord = data['coord'][i]
                d['minA'] = min( d['minA'], coord[0] )
                d['maxA'] = max( d['maxA'], coord[0] )
                d['minB'] = min( d['minB'], coord[1] )
                d['maxB'] = max( d['maxB'], coord[1] )
                d['minC'] = min( d['minC'], coord[2] )
                d['maxC'] = max( d['maxC'], coord[2] )
            
            # Make sure everything is inside the current cell
            # TODO - switch off Mincell when this isn't the case
            if False:
                tmp = d['border']
                assert d['minA'] > 0 + tmp,"minA {0} border {1}".format( d['minA'], d['border'] )
                assert d['maxA'] + tmp < self.A,"maxA {0} A {1} border {2}".format( d['maxA'], self.A, d['border'] )
                assert d['minB'] > 0 + tmp,"minB {0} border {1}".format( d['minB'], d['border'] )
                assert d['maxB'] + tmp < self.B,"maxB {0} B {1} border {2}".format( d['maxB'], self.B, d['border'] )
                assert d['minC'] > 0 + tmp,"minC {0} border {1}".format( d['minC'], d['border'] )
                assert d['maxC'] + tmp < self.C,"maxC {0} C {1} border {2}".format( d['maxC'], self.C, d['border'] )
            
            # Calculate cell dimensions ( to nearest integer )
            d['A'] = ( math.ceil( d['maxA'] ) - math.floor( d['minA'] ) ) + d['border'] * 2
            d['B'] = ( math.ceil( d['maxB'] ) - math.floor( d['minB'] ) ) + d['border'] * 2
            d['C'] = ( math.ceil( d['maxC'] ) - math.floor( d['minC'] ) ) + d['border'] * 2
            
            # Need to make sure the old dimensions are <= the original
            same = 0
            if d['A'] >= self.A:
                self.logger.debug("MINCELL DIMENSION A IS KEPT SAME")
                d['A'] = self.A
                d['minA'] = 0.0
                d['maxA'] = self.A
                same += 1

            if d['B'] >= self.B:
                self.logger.debug("MINCELL DIMENSION B IS KEPT SAME")
                d['B'] = self.B
                d['minB'] = 0.0
                d['maxB'] = self.B
                same += 1
                
            if d['C'] >= self.C:
                self.logger.debug("MINCELL DIMENSION C IS KEPT SAME")
                d['C'] = self.C
                d['minC'] = 0.0
                d['maxC'] = self.C
                same += 1
                
            if same == 3:
                self.logger.critical("optimiseGeometry minCell - ignoring directive and using full cell")
                self.minCell = False
        
        
        if self.minCell:
            
            # Now set the cell dimensions for hoomdblue
            data['A'] = d['A']
            data['B'] = d['B']
            data['C'] = d['C']
            
            # Move the coordinates into the new cell and center them
            data['position'] = []
            data['image'] = []
            for i in range( len( data['coord'] ) ):
                coord = data['coord'][i]
                
                x =  coord[0] - ( d['minA'] + d['A']/2 )
                y =  coord[1] - ( d['minB'] + d['B']/2 )
                z =  coord[2] - ( d['minC'] + d['C']/2 )
                
                data['position'].append( (x, y, z ) )
                data['image'].append( ( 0, 0, 0 ) ) # Always in the first image
            
            self.minCellData = d
            
        else:
        
            data['position'] = []
            data['image'] = []
            for i in range( len( data['coord'] ) ):
                coord = data['coord'][ i ]
                x, ix = util.wrapCoord( coord[0], self.A, center=True )
                y, iy = util.wrapCoord( coord[1], self.B, center=True )
                z, iz = util.wrapCoord( coord[2], self.C, center=True )
                
                data['position'].append( ( x, y, z ) )
                data['image'].append( ( ix, iy, iz ) )
            
        return data

    def processBonds(self):
        """Make any bonds that were found during checkMove
        return Number of bonds made
        
        Args:
        addedBlockIdx - the block that was added
        """
        
        if not len( self._possibleBonds ):
            self.logger.debug("processBonds got no bonds" )
            return 0
        
        #self.logger.debug = lambda x: sys.stdout.write(x + "\n")
        
        # Here no atoms clash and we have a list of possible bonds - so bond'em!
        self.logger.debug("processBonds got bonds: {0}".format( self._possibleBonds ) )
        self.logger.debug("processBonds blocks are: {0}".format( sorted( self.blocks ) ) )
        
        bondsMade = 0
        for count, bond in enumerate( self._possibleBonds ):
            # With the bonding rules some endGroups may become not free when other endGroups in that fragment
            # are involved in bonds so we need to make sure they are free before we do
            if bond.endGroup1.free() and bond.endGroup2.free():
                self.bondBlock( bond )
                self.logger.debug("Added bond: {0}".format( self._possibleBonds[count] ) )
                bondsMade += 1
                #self.logger.debug( "process bonds after bond self.blocks is  ",sorted(self.blocks) )
        
        # Clear any other possible bonds
        self._possibleBonds = []
        
        return bondsMade

    def randomBlockId( self, checkFree=True ):
        """Return numBlocks random block ids"""
        
        MAXCOUNT=100
        
        blockId = random.choice( list( self.blocks.keys() ) )
        
        if checkFree:
            if self.numFreeEndGroups() == 0:
                return False
            
            count = 0
            while True:
                count += 1
                if count > MAXCOUNT:
                    return False
                
                block = self.blocks[ blockId ]
                if block.numFreeEndGroups > 0:
                    break
                
                blockId = random.choice( list( self.blocks.keys() ) )
        
        return blockId
    
    def randomMoveBlock(self, block, margin=None ):
        """Randomly move the given block
         If buffer is given, use this as a buffer from the edges of the cell
         when selecting the coord
        """
        # Get _coords of random point in the cell that we will move the block to after 
        # we've rotated at the origin
        if margin:
            x = random.uniform(margin,self.A-margin)
            y = random.uniform(margin,self.B-margin)
            z = random.uniform(margin,self.C-margin)
        else:
            x = random.uniform(0,self.A)
            y = random.uniform(0,self.B)
            z = random.uniform(0,self.C)
        
        coord = numpy.array([x,y,z], dtype=numpy.float64 )
        
         #print "Got random coord: {}".format(coord)
        
        # Move to origin, rotate there and then move to new coord
        # Use the cell axis definitions
        block.translateCentroid( self.origin )
        block.randomRotate( origin=self.origin, atOrigin=True )
        
        # Now move to new coord
        block.translateCentroid( coord )
        
        return
        
    def randomMoveAroundCenter(self, move_block, center, radius ):
        """
        Move the move_block to a random point so that the its centroid is withiin
        radius of the center
        """
        
        # Calculate new coord
        x = random.uniform(-radius,radius)
        y = random.uniform(-radius,radius)
        z = random.uniform(-radius,radius)
        xyz = numpy.array( [x,y,z], dtype=numpy.float64 )
        coord = numpy.add( center, xyz )
        
        move_block.translateCentroid( coord )
        
        move_block.randomRotateBlock( origin=self.origin )
        return
    
    def resizeCells( self, boxMargin ):
        # Change the cell size
        self.updateCellSize( boxMargin=boxMargin )
        self.repopulateCells()
        return
    
    def repopulateCells(self):
        """Add all the blocks to resized cells"""

        # Remove all blocks from their cells
        self.box1 = {}
        self.box3 = {}
        
        if len( self.blocks ):
            # Put all the blocks into the new cells
            # First copy the blocks dictionary
            blocks = copy.copy( self.blocks )
            
            self.blocks.clear() # Delete the old one and reset
            
            self.logger.debug("repopulateCells, adding blocks into new cells")
            for idxBlock, block in blocks.iteritems():
                self.addBlock( block, idxBlock=idxBlock )
                
            del blocks
        return

    def runMD(self,
              xmlFilename="hoomdMD.xml",
              doDihedral=False,
              doImproper=False,
              **kw ):
        
        if doDihedral and doImproper:
            raise RuntimeError,"Cannot have impropers and dihedrals at the same time"
        
        optimiser = opt.HoomdOptimiser()
        if 'rCut' in kw:
            self.rCut = kw['rCut']
        else:
            self.rCut = optimiser.rCut
        
        # Write out HoomdBlue xml file & get parameters
        self.writeHoomdXml( xmlFilename=xmlFilename,
                            doDihedral=doDihedral,
                            doImproper=doImproper )
        
        d = {}
        ok = optimiser.runMD( xmlFilename,
                                  doDihedral=doDihedral,
                                  doImproper=doImproper,
                                  d=d,
                                  **kw )
        
        self.analyse.stop('runMD', d )

        self.fromHoomdblueSystem( optimiser.system )

        return ok
    
    def runMDAndOptimise(self,
                         xmlFilename="hoomdMDOpt.xml",
                         doDihedral=False,
                         doImproper=False,
                         **kw ):
        
        if doDihedral and doImproper:
            raise RuntimeError,"Cannot have impropers and dihedrals at the same time"

        optimiser = opt.HoomdOptimiser()
        if 'rCut' in kw:
            self.rCut = kw['rCut']
        else:
            self.rCut = optimiser.rCut

        # Write out HoomdBlue xml file & get parameters
        self.writeHoomdXml( xmlFilename=xmlFilename,
                            doDihedral=doDihedral,
                            doImproper=doImproper )
        d = {}
        ok = optimiser.runMDAndOptimise( xmlFilename, 
                                             doDihedral=doDihedral,
                                             doImproper=doImproper,
                                             d=d,
                                             **kw )

        if ok:
            self.logger.info( "runMDAndOptimise succeeded" )
            
        
        self.analyse.stop('runMDAndOptimise', d )
        
        self.fromHoomdblueSystem( optimiser.system )

        return ok

    def seed( self, nblocks, fragmentType=None, maxTries=500, center=False ):
        """ Seed a cell with nblocks.
        
        Return the number of blocks we added
        """
        
        if self.A is None or self.B is None or self.C is None:
            raise RuntimeError,"Need to specify cell before seeding"
        
        #if not len( self._fragmentLibrary ) or not len( self.bondTypes):
        #    raise RuntimeError,"Must have set an initBlock and bondType before seeding."
        if not len( self._fragmentLibrary ):
            raise RuntimeError,"Must have set an initBlock before seeding."
        
        self.logger.info("seed adding {0} block of type {1}".format( nblocks, fragmentType ) )

        numBlocksAdded = 0
        # Loop through the nblocks adding the blocks to the cell
        for seedCount in range( nblocks ):
            
            # Create new block
            newblock = self.getInitBlock( fragmentType=fragmentType )
            
            tries = 0
            while True:
                # quit on maxTries
                if tries >= maxTries:
                    self.logger.critical("Exceeded maxtries when seeding after adding {0}".format(numBlocksAdded))
                    self.analyse.stop( 'seed',d={'num_tries':tries} )
                    return numBlocksAdded

                # if center put the first one in the center of the cell 
                # only if this is the first attempt as otherwise we always fail if there is already something there
                if center and seedCount==0 and tries==0:
                    newblock.translateCentroid( [ self.A/2, self.B/2, self.C/2 ] )
                else:
                    # Move the block and rotate it
                    self.randomMoveBlock( newblock )
                
                #Add the block so we can check for clashes/bonds
                idxBlock = self.addBlock( newblock )
                
                # Test for Clashes with other molecules
                if self.checkMove( idxBlock ):
                    if self.processBonds() > 0:
                        self.logger.info("Added bond in seed!")
                    self.logger.debug("seed added block {0} after {1} tries.".format( seedCount+1, tries ) )
                    self.analyse.stop('seed',d={'num_tries':tries} )
                    numBlocksAdded += 1
                    break
                
                # Unsuccessful so remove the block from cell
                self.delBlock(idxBlock)
                
                # If seed fails with center need to bail on first one.
                if center and seedCount == 0:
                    self.logger.warn("Seed with center failed to place first block in center!")
                    
                # increment tries counter
                tries += 1
            
            # End Clash loop
        # End of loop to seed cell
        
        self.logger.info("Seed added {0} blocks. Cell now contains {1} blocks".format( numBlocksAdded,
                                                                                       len(self.blocks) ) )
        
        return numBlocksAdded
    
    def setMaxBond(self, bondType, count ):
        # Get fragmentType and endGroupType
        fragmentType, endGroupType = bondType.split(self.ENDGROUPSEP)
        
        # Now get the library fragment to set it's maxBond parameter
        fragment = self._fragmentLibrary[ fragmentType ]
        return fragment.setMaxBond( bondType, count )

    def _setupAnalyse(self, logfile='ambuild.csv'):
        self.analyse = Analyse( self, logfile=logfile )
        return

    def setupLogging( self, logfile="ambuild.log", mode='w', doLog=False ):
        """
        Set up the various log files/console logging and return the logger
        """
        
        logger = logging.getLogger()
        #if not doLog:
        #    logging.disable(logging.DEBUG)

        # First check if there are any handlers active - if so we remove them
        if len(logger.handlers):
            # Need to copy as otherwise the list changes while we're cycling through it
            for hdlr in copy.copy(logger.handlers):
                logger.removeHandler(hdlr)
        
        # Not entirely sure why this needed - set overall level of the logger to debug
        logger.setLevel( logging.DEBUG )
        
        # create file handler and set level to debug
        self.logfile=logfile
        fl = logging.FileHandler( self.logfile, mode=mode )
        if doLog:
            fl.setLevel( logging.DEBUG )
        else:
            fl.setLevel( logging.INFO )
        
        # create formatter for fl
        formatter = logging.Formatter( '%(asctime)s - %(name)s - %(levelname)s - %(message)s' )
        
        # add formatter to fl
        fl.setFormatter( formatter )
        
        # add fl to logger
        logger.addHandler( fl )
        
        # Now create console logger for outputting stuff
        # create file handler and set level to debug
        # Seems they changed the api in python 2.6->2.7
        try:
            cl = logging.StreamHandler( stream=sys.stdout )
        except TypeError:
            cl = logging.StreamHandler( strm=sys.stdout )
        cl.setLevel( logging.INFO )

        # create formatter for fl
        # Always add a blank line after every print
        formatter = logging.Formatter( '%(message)s\n' )

        # add formatter to fl
        cl.setFormatter( formatter  )

        # add fl to logger
        logger.addHandler( cl )
        
        self.logger = logger
        return
    
    def surroundCells(self, key ):
        return self._surroundCells( key, self.numBoxA, self.numBoxB, self.numBoxC )
        
    def _surroundCells(self, key, numBoxA, numBoxB, numBoxC ):
        """
        return a list of the cells surrounding the one with the given key
        """
        
        #print "box size {} : {},{},{}".format( self.boxSize, self.numBoxA, self.numBoxB, self.numBoxC )
        
        # REM - max box num is numboxes - 1
        a,b,c = key
        l = []
        for  i in [ 0, -1, +1 ]:
            for j in [ 0, -1, +1 ]:
                for k in [ 0, -1, +1 ]:
                    # Impose periodic boundaries
                    ai = a+i
                    if ai < 0:
                        ai = numBoxA-1
                    elif ai > numBoxA-1:
                        ai = 0
                    bj = b+j
                    if bj < 0:
                        bj = numBoxB-1
                    elif bj > numBoxB-1:
                        bj = 0
                    ck = c+k
                    if ck < 0:
                        ck = numBoxC-1
                    elif ck > numBoxC-1:
                        ck = 0
                    skey = (ai, bj, ck)
                    #print "sKey ({},{},{})->({})".format(a,b,c,skey)
                    if skey not in l:
                        l.append(skey)
                        
        return l
    
#     def shimmy(self, nsteps=100, nmoves=50, stype=None):
#         """ Shuffle the molecules about making bonds where necessary for nsteps
#         minimoves is number of sub-moves to attempt when the blocks are close
#         """
#         
#         startBlocks=len(self.blocks)
# 
#         filename = "SHIMMY_0.xyz"
#         self.writeXyz( filename )
#         self.writeXyz( filename+".lab", label=True )
#         
#         for step in range( nsteps ):
#             
#             if len(self.blocks) == 1:
#                 filename = util.newFilename(filename)
#                 print "NO MORE BLOCKS!\nResult in file: {}".format(filename)
#                 self.writeXyz( filename )
#                 self.writeXyz( os.path.splitext(filename)[0]+"_incell.xyz", periodic=True )
#                 self.writeXyz( filename+".lab", label=True )
#                 break
#             
#             #if True:
#             if not step % 100:
#                 print "step {}".format(step)
#                 filename = util.newFilename(filename)
#                 self.writeXyz( filename )
#                 self.writeXyz( filename+".lab", label=True )
#                 self.writeXyz( os.path.splitext(filename)[0]+"_incell.xyz", periodic=True )
#                 
#             istatic_block = None
#             if stype == "block" or stype == "bond":
#                 imove_block, istatic_block = self.randomBlockId(numBlocks=2)
#                 static_block = self.blocks[istatic_block]    
#             else:
#                 imove_block = self.randomBlockId()
#                 
#             move_block = self.blocks[imove_block]
#             
#             # Copy the original coordinates so we can reject the move
#             orig_coords = copy.deepcopy( move_block._coords )
#             
#             center = None
#             if stype == "block":
#                 # Calculate how far to move
#                 circ = move_block.radius() + static_block.radius()
#                 radius = (circ/2) + self.atomMargin
#                 center = static_block.centroid()
#             elif stype == "bond":
#                 staticEndGroupIndex = static_block.randomEndGroup()
#                 moveEndGroupIndex = move_block.randomEndGroup()
#                 center = static_block.newBondPosition( staticEndGroupIndex, move_block, moveEndGroupIndex)
#                 # jmht - this is wrong!
#                 radius = self.atomMargin
#             else:
#                 nmoves=1
#             
#             for move in range(nmoves):
#                 
#                 #print "move ",move
#                 
#                 # Remove the move_block from the cell so we don't check against itself
#                 self.delBlock(imove_block)
#                 
#                 if stype == "block" or stype == "bond":
#                     self.randomMoveAroundCenter( move_block, center, radius )
#                 else:
#                     self.randomMoveBlock( move_block )
#                 
#                 #Add the move_block back so we can check for clashes/bonds
#                 icheck = self.addBlock(move_block)
#                 if icheck != imove_block:
#                     raise RuntimeError,"BAD ADD IN SHIMMY1"
#                 
#                 # Test for Clashes with other molecules
#                 if self.checkMove( imove_block ):
#                 # If the move failed, put the move_block back
#                     if self.processBonds( addedBlockIdx=imove_block ):
#                         # End the moves and go onto the next step
#                         break
#                     
#                 # Put it back where we got it from
#                 self.delBlock( imove_block )
#                 move_block._coords = copy.deepcopy(orig_coords)
#                 move_block.update()
#                 icheck = self.addBlock(move_block)
#                 if icheck != imove_block:
#                     raise RuntimeError,"BAD ADD IN SHIMMY1"
#         
#         # End of shimmy loop
#         
#         endBlocks = len(self.blocks)
#         made = startBlocks-endBlocks
#         if made > 0:
#             print "Shimmy bonded {} blocks".format(made)
#         else:
#             print "Shimmy made no bonds"
#         
#         return
#         #End shimmy

    def updateFromBlock(self, block ):
        """Update cell parameters from the block"""
        
        if block.maxAtomRadius <= 0:
            raise RuntimeError,"Error updating cell from block"
        
        if block.maxAtomRadius() > self.maxAtomRadius:
            
            # What happens to already added blocks if we call this after we've added them?
            # Not sure so being safe...
            if len( self.blocks ) > 0:
                raise RuntimeError,"Adding initblock after blocks have been added - not sure what to do!"
            
            self.updateCellSize( maxAtomRadius=block.maxAtomRadius() )
            
        return
    
    def updateCellSize(self, boxMargin=None, maxAtomRadius=None, MARGIN=0.01 ):
        """The cell size is the vdw radius of the largest atom plus the largest of atom or bondMargin
        plus a MARGIN to account for overflows
        """
        if maxAtomRadius != None:
            self.maxAtomRadius = maxAtomRadius
        
        if not boxMargin is None:
            self.boxMargin = boxMargin
        else:
            assert self.atomMargin and self.bondMargin
            # box margin is largest we'll be looking for plus a bit to account for arithmetic overflow
            self.boxMargin = max( self.atomMargin, self.bondMargin ) + MARGIN
        
        assert self.boxMargin != 0 and self.maxAtomRadius != 0
        
        self.boxSize = ( self.maxAtomRadius * 2 ) + self.boxMargin
        
        #jmht - ceil or floor
        self.numBoxA = int(math.ceil( self.A / self.boxSize ) )
        self.numBoxB = int(math.ceil( self.B / self.boxSize ) )
        self.numBoxC = int(math.ceil( self.C / self.boxSize ) ) 
        
        self.logger.debug( "updateCellSize: boxSize {0} nboxes: {1} maxR {2} margin {3}".format( self.boxSize,
                                                                                      ( self.numBoxA, self.numBoxB, self.numBoxC ),
                                                                                     self.maxAtomRadius, 
                                                                                     self.boxMargin)
                          )
        
        return

    def writePickle( self, fileName="cell.pkl" ):
        """Pickle ourselves"""
        
        # Need to close all open filehandles and the logger handlers
        #for l in self.logger.handlers:
        #    print "GOT HANDLER1 ",l
        
        # No idea why I can't get the log to close and then reopen with append mode
        # see _get_state_ and _set_state_ in this class
        if False:
            self._clLogHandler.close()
            self._flLogHandler.close()
            self.logger.removeHandler( self._clLogHandler )
            self.logger.removeHandler( self._flLogHandler )
            del self._clLogHandler
            del self._flLogHandler
            
        
        fileName = os.path.abspath( fileName )
        
        # Create the pickle file
        util.pickleObj( self, fileName )
         
        # Restart logging with append mode
        #self.setupLogging( mode='a' )
        
        self.logger.info( "Wrote pickle file: {0}".format(fileName) )
        
        return
        
    def writeCar( self, ofile="ambuild.car", data=None, periodic=True, skipDummy=False ):
        """Car File
        """
        
        if not data:
            data = self.dataDict()
        
        car = "!BIOSYM archive 3\n"
        if periodic:
            car += "PBC=ON\n"
        else:
            car += "PBC=OFF\n"
        
        car += "ambuild generated car file\n"
        tstr = time.strftime( "%a %b %d %H:%M:%S %Y", time.gmtime() )
        car += "!DATE {0}\n".format( tstr )
        
        if periodic:
            car += "PBC  {0: < 9.4F} {1: < 9.4F} {2: < 9.4F}  90.0000   90.0000   90.0000 (P1)\n".format( data['A'],
                                                                                                          data['B'],
                                                                                                          data['C'] )
#         for i, ( idxBlock, block ) in enumerate( self.blocks.iteritems() ):
#             for j, coord in enumerate( block.iterCoord() ):
        for i, coord in enumerate( data['coord'] ):
                if periodic:
                    x, ix = util.wrapCoord( coord[0], data['A'], center=False )
                    y, iy = util.wrapCoord( coord[1], data['B'], center=False )
                    z, iz = util.wrapCoord( coord[2], data['C'], center=False )
                else:
                    x = coord[0]
                    y = coord[1]
                    z = coord[2]
                
                atype = data['type'][ i ]
                charge = data['charge'][ i ]
                label = data['label'][ i ][:5]
                symbol = data['symbol'][ i ]
                car += "{0: <5} {1: >15.10} {2: >15.10} {3: >15.10} XXXX 1      {4: <4}    {5: <2} {6: > 2.3f}\n".format( label, x, y, z, atype, symbol, charge ) 
        
        car += "end\nend\n\n"
        
        with open( ofile, 'w' ) as f:
            fpath = os.path.abspath(f.name)
            f.writelines( car )
            
        self.logger.info( "Wrote car file: {0}".format(fpath) )
        return
    
    def writeCml(self, cmlFilename, data=None, allBonds=True, periodic=False, pruneBonds=False):

        # Get the data on the blocks
        if not data:
            data = self.dataDict()
        
        root = ET.Element( 'molecule')
        root.attrib['xmlns']       = "http://www.xml-cml.org/schema"
        root.attrib['xmlns:cml']   = "http://www.xml-cml.org/dict/cml"
        root.attrib['xmlns:units'] = "http://www.xml-cml.org/units/units"
        root.attrib['xmlns:xsd']   = "http://www.w3c.org/2001/XMLSchema"
        root.attrib['xmlns:iupac'] = "http://www.iupac.org"
        root.attrib['id']          = "mymolecule"
        
        # First set up the cell
        crystal = ET.SubElement( root, "crystal" )

        crystalANode = ET.SubElement( crystal,"scalar")
        crystalBNode = ET.SubElement( crystal,"scalar")
        crystalCNode = ET.SubElement( crystal,"scalar")
        crystalAlphaNode = ET.SubElement( crystal,"scalar")
        crystalBetaNode  = ET.SubElement( crystal,"scalar")
        crystalGammaNode = ET.SubElement( crystal,"scalar")

        crystalANode.attrib["title"] = "a"
        crystalBNode.attrib["title"] = "b"
        crystalCNode.attrib["title"] = "c"
        crystalAlphaNode.attrib["title"] = "alpha"
        crystalBetaNode.attrib["title"] =  "beta"
        crystalGammaNode.attrib["title"] = "gamma"
        
        crystalANode.attrib["units"] = "units:angstrom"
        crystalBNode.attrib["units"] = "units:angstrom"
        crystalCNode.attrib["units"] = "units:angstrom"
        crystalAlphaNode.attrib["units"] = "units:degree"
        crystalBetaNode.attrib["units"]  = "units:degree"
        crystalGammaNode.attrib["units"] = "units:degree"
        
        crystalANode.text = str( data['A'] )
        crystalBNode.text = str( data['B'] )
        crystalCNode.text = str( data['C'] )
        
        # Only support orthorhombic? cells
        crystalAlphaNode.text = "90"
        crystalBetaNode.text  = "90"
        crystalGammaNode.text = "90"
        
        # Hack to get vis working
        if pruneBonds:
            pcoords = []
            
        # Need to collate atomTypes
        for atype in set( data['type'] ):
            atomTypeNode = ET.SubElement( root, "atomType" )
            atomTypeNode.attrib['name'] = atype
            atomTypeNode.attrib['title'] = atype
        
        # Now atom data
        atomArrayNode = ET.SubElement( root, "atomArray" )
        for i, coord in enumerate( data['coord'] ):
            atomNode = ET.SubElement( atomArrayNode, "atom")
            atomNode.attrib['id'] = "a{0}".format( i )
            atomNode.attrib['elementType'] = data['symbol'][i]
            if periodic:
                x, ix = util.wrapCoord( coord[0], data['A'], center=False )
                y, iy = util.wrapCoord( coord[1], data['B'], center=False )
                z, iz = util.wrapCoord( coord[2], data['C'], center=False )
                if pruneBonds:
                    pcoords.append( numpy.array( [x,y,z] ) )
            else:
                x = coord[0]
                y = coord[1]
                z = coord[2]
            
            atomNode.attrib['x3'] = str( x )
            atomNode.attrib['y3'] = str( y )
            atomNode.attrib['z3'] = str( z )
            
            # Now add atomType as child node referring to the atomType
            atomTypeNode = ET.SubElement( atomNode, "atomType" )
            atomTypeNode.attrib['ref'] = data['type'][ i ]
        
        # Now do bonds
        bondArrayNode = None
        if len(data['bond']):
            bondArrayNode = ET.SubElement( root, "bondArray" )
            for i, b in enumerate( data['bond'] ):
                if pruneBonds:
                    # Complete hack - just see if it's longer then 0.5 the cell A distance
                    # - this assumes that the cell is cubic
                    if util.distance( pcoords[ b[0] ], pcoords[ b[1] ] ) >= data['A'] * 0.5:
                        continue
                bondNode = ET.SubElement( bondArrayNode, "bond")
                bondNode.attrib['atomRefs2'] = "a{0} a{1}".format( b[0], b[1]  )
                bondNode.attrib['order'] = "1"
        
        # internal fragment bonds
        if len(data['fragmentBond']) and allBonds:
            if bondArrayNode is None:
                bondArrayNode = ET.SubElement( root, "bondArray" )
            for i, b in enumerate( data['fragmentBond'] ):
                if pruneBonds:
                    # Complete hack - just see if it's longer then 0.5 the cell A distance
                    # - this assumes that the cell is cubic
                    if util.distance( pcoords[ b[0] ], pcoords[ b[1] ]  ) >= data['A'] * 0.5:
                        continue
                bondNode = ET.SubElement( bondArrayNode, "bond")
                bondNode.attrib['atomRefs2'] = "a{0} a{1}".format( b[0], b[1]  )
                bondNode.attrib['order'] = "1"

        tree = ET.ElementTree(root)
        
        #ET.dump(tree)
        
        cmlFilename = os.path.abspath( cmlFilename )
        #tree.write(file_or_filename, encoding, xml_declaration, default_namespace, method)
        tree.write( cmlFilename, encoding="utf-8", xml_declaration=True)
        
        self.logger.info( "Wrote cmlfile: {0}".format(cmlFilename) )
        
        return
    
    def writeXyz(self, ofile, data=None, periodic=False ):
        """Write out the cell atoms to an xyz file
        If label is true we write out the atom label and block, otherwise the symbol
        """
        
        if not data:
            data = self.dataDict()
        
        xyz = ""
        for i, coord in enumerate( data['coord'] ):
                
            if periodic:
                x, ix = util.wrapCoord( coord[0], self.A, center=False )
                y, iy = util.wrapCoord( coord[1], self.B, center=False )
                z, iz = util.wrapCoord( coord[2], self.C, center=False )
            else:
                x, y, z = coord
                
            xyz += "{0:5}   {1:0< 15}   {2:0< 15}   {3:0< 15}\n".format( data['symbol'][i], x, y, z )
        
        # Write out natoms and axes as title
        xyz = "{}\nAxes:{}:{}:{}\n".format( i+1, data['A'], data['B'], data['C'] ) + xyz
        
        with open( ofile, 'w' ) as f:
            fpath = os.path.abspath(f.name)
            f.writelines( xyz )
            
        self.logger.info( "Wrote cell file: {0}".format(fpath) )
        return

    def writeHoomdXml(self,
                      xmlFilename="ambuildhoomd.xml",
                      doCharges=True,
                      doDihedral=False,
                      doImproper=False,
                      data=None, 
                      ):
        """Write out a HOOMD Blue XML file.
        """
        
        # For time being use zero so just under LJ potential & bond
        #diameter += "{0}\n".format( frag._atomRadii[ k ] )
        
        data = self.prepareHoomdData(data=data)
        
        body     = "\n" + "\n".join( map( str, data['body'] ) ) + "\n"
        charge   = "\n" + "\n".join( map( str, data['charge'] ) ) + "\n"
        diameter = "\n" + "\n".join( map( str, data['diameter'] ) ) + "\n"
        mass     = "\n" + "\n".join( map( str, data['mass'] ) ) + "\n"
        ptype    = "\n" + "\n".join( map( str, data['type'] ) ) + "\n"
        
        image = "\n"
        position = "\n"
        for i in range( len( data['position'] ) ):
            image += "{0} {1} {2}\n".format( 
                                          data['image'][i][0],
                                          data['image'][i][1],
                                          data['image'][i][2],
                                          )
            position += "{0} {1} {2}\n".format( 
                                          data['position'][i][0],
                                          data['position'][i][1],
                                          data['position'][i][2],
                                          )
        
        # Now do all angles and bonds
        bond=False
        if len( data['bond'] ):
            bond = "\n"
            for i, b in enumerate( data['bond'] ):
                bond += "{0} {1} {2}\n".format( data['bondLabel'][i], b[0], b[1] )
        
        angle=False
        if len( data['angle'] ):
            angle = "\n"
            for i, a in enumerate( data['angle'] ):
                if data['angleLabel'][i] != "aatom":
                    angle += "{0} {1} {2} {3}\n".format( data['angleLabel'][i], a[0], a[1], a[2] )
        
        dihedral=False
        if len( data['dihedral'] ):
            dihedral = "\n"
            for i, dh in enumerate( data['dihedral'] ):
                dihedral += "{0} {1} {2} {3} {4}\n".format( data['dihedralLabel'][i], dh[0], dh[1], dh[2], dh[3] )
        
#         for f in fragmentBonds:
#             bond += "fbond {0} {1}\n".format( f[0], f[1] )


        root = ET.Element( 'hoomd_xml', version="1.4" )
        config = ET.SubElement( root, "configuration", timestep="0" )
        
        #e = ET.SubElement( config, "box", 
        ET.SubElement( config, "box", 
                        Lx=str(data['A']), 
                        Ly=str(data['B']), 
                        Lz=str(data['C']) )

        e = ET.SubElement(config, "position" )
        e.text = position
        e = ET.SubElement(config, "image" )
        e.text = image
        
        e = ET.SubElement(config, "body" )
        e.text = body
        if doCharges:
            e = ET.SubElement(config, "charge" )
            e.text = charge
        e = ET.SubElement(config, "diameter" )
        e.text = diameter
        e = ET.SubElement(config, "type" )
        e.text = ptype
        e = ET.SubElement(config, "mass" )
        e.text = mass
        
        if bond:
            e = ET.SubElement(config, "bond" )
            e.text = bond
        if angle:
            e = ET.SubElement(config, "angle" )
            e.text = angle
        if dihedral:
            if doDihedral:
                e = ET.SubElement(config, "dihedral" )
                e.text = dihedral
            elif doImproper:
                e = ET.SubElement(config, "improper" )
                e.text = dihedral
                
        
        tree = ET.ElementTree(root)
        
        #ET.dump(tree)
        
        #tree.write(file_or_filename, encoding, xml_declaration, default_namespace, method)
        tree.write( xmlFilename )
        
        self.logger.info( "Wrote HOOMD-blue xmlfile: {0}".format(xmlFilename) )
        
        return True
    
    def zipBlocks( self, bondMargin=None, bondAngleMargin=None  ):
        
        self.logger.info("Zipping blocks with bondMargin: {0} bondAngleMargin {1}".format(bondMargin, bondAngleMargin )  )
        
        # Convert to radians
        bondAngleMargin = math.radians(bondAngleMargin)
        
        # Calculate the number of boxes
        
        # Should calculate max possible bond length
        maxBondLength=2.5
        boxSize = maxBondLength + bondMargin
        numBoxA = int(math.ceil( self.A / boxSize ) )
        numBoxB = int(math.ceil( self.B / boxSize ) )
        numBoxC = int(math.ceil( self.C / boxSize ) ) 
        
        # Create empty cells to hold data
        cell1 = {}
        cell3 = {}
        
        # Get a list of all block, endGroups
        endGroups = []
        for block in self.blocks.itervalues():
            egs = block.freeEndGroups()
            if len(egs):
                block.zipCell = {}
                for endGroup in egs:
                    endGroups.append( ( block, endGroup.blockEndGroupIdx ) )

        if not len(endGroups) > 0:
            sys.logger.warn("zipBlocks found no free endGroups!")
            return 0
        
        # Add all (block, idxEndGroup) tuples to the cells
        for (block, idxEndGroup) in endGroups:
            
            coord = block.atomCoord( idxEndGroup )
            
            # Periodic Boundaries
            x = coord[0] % self.A
            y = coord[1] % self.B
            z = coord[2] % self.C
            
            # Calculate which cell the atom is in
            a=int( math.floor( x / boxSize ) )
            b=int( math.floor( y / boxSize ) ) 
            c=int( math.floor( z / boxSize ) )
            key = (a,b,c)
            block.zipCell[ idxEndGroup ] = key
            
            try:
                # Add the atom to the cell
                cell1[ key ].append( ( block, idxEndGroup ) )
            except KeyError:
                # Add the cell to the list and then add the atom
                cell1[ key ] = [ ( block, idxEndGroup ) ]
                # Map the cells surrounding this one
                cell3[ key ] = self._surroundCells( key, numBoxA, numBoxB, numBoxC )
        
        # Loop through all the end groups and run canBond
        self._possibleBonds = []
        egPairs             = []
        c1                  = []
        c2                  = []
        for block1, idxEndGroup1 in endGroups:
            
            # Get the box this atom is in
            key = block1.zipCell[ idxEndGroup1 ]
            
            # Get a list of the boxes surrounding this one
            surrounding = cell3[ key ]
            
            # For each box loop through all its atoms
            for i, sbox in enumerate( surrounding ):
                
                # Check if we have a box with anything in it
                # use exception so we don't have to search through the whole list
                try:
                    alist = cell1[ sbox ]
                except KeyError:
                    continue
                
                for (block2, idxEndGroup2) in alist:
                    
                    # Self-bonded blocks need special care
                    if block1 == block2:
                        # Don't check endGroups against themselves
                        if idxEndGroup1 == idxEndGroup2:
                            continue
                        # Make sure the two atoms are separated by at least 3 bonds - could
                        # probably put this check in canBond but it would slow the normal
                        # bonding down - need to think about best way to do this
                        if idxEndGroup2 in block1.atomBonded3( idxEndGroup1 ):
                            continue
                    
                    # PROBABLY A BETTER WAY OF DOING THIS
                    p1 = ( block1,idxEndGroup1, block2, idxEndGroup2 )
                    p2 = ( block2, idxEndGroup2, block1, idxEndGroup1 )
                    if p1 not in egPairs and p2 not in egPairs:
                        # Need to check if it is already in there as we loop over all endGroups
                        # so we will have both sides twice
                        egPairs.append( p1 )
                        c1.append( block1.atomCoord( idxEndGroup1 ) )
                        c2.append( block2.atomCoord( idxEndGroup2 ) )

        if not len(egPairs) > 0:
            self.logger.info("zipBlocks: no endGroups close enough to bond" )
            return 0 

        # Calculate distances between all pairs
        distances = self.distance(c1, c2)
        
        # Now check for bonds
        for i, ( block1, idxEndGroup1, block2, idxEndGroup2 ) in enumerate( egPairs ):
            got = self.canBond( block1,
                                idxEndGroup1,
                                block2,
                                idxEndGroup2,
                                distances[i],
                                bondMargin,
                                bondAngleMargin,
                                )
        
        # Process any bonds
        todo = len( self._possibleBonds )
        
        self.logger.info("zipBlocks: found {0} additional bonds".format( todo ) )
#         for b in self._possibleBonds:
#             print "Attempting to bond: {0} {1} {2} -> {3} {4} {5}".format( b.block1.id(),
#                                                                    b.endGroup1.blockEndGroupIdx,
#                                                                    b.block1.atomCoord( b.endGroup1.blockEndGroupIdx),
#                                                                    b.block2.id(),
#                                                                    b.endGroup2.blockEndGroupIdx,
#                                                                    b.block2.atomCoord( b.endGroup2.blockEndGroupIdx),
#                                                                 )
#         
        bondsMade = 0
        if todo > 0:
            bondsMade = self.processBonds()
            if bondsMade != todo:
                self.logger.debug("Made fewer bonds than expected in zip: {0} -> {1}".format(
                                                                                                todo, 
                                                                                                bondsMade ) )
            
        self.analyse.stop('zip')
        
        return bondsMade
    
    def __str__(self):
        """
        """
        s = ""
        s += "InitBlocks: {0}".format( self._fragmentLibrary )
        s += "Blocks: "
        for block in self.blocks.values():
            s+= str(block)
            
        return s
    
    def __getstate__(self):
        """
        Return a dict of objects we want to pickle.
        
        This is required as we can't pickle objects containing a logger as they have
        file handles (can remove by calling logging.shutdown() ) and lock objects (not removed
        by calling shutdown)."""
        
        # Return everything bar our logger
        d = dict(self.__dict__)
        del d['logger']
        d['analyseLogfile']=d['analyse'].logfile
        del d['analyse']
        return d
    
    def __setstate__(self, d):
        """Called when we are unpickled """
        self.__dict__.update(d)
        if 'logfile' in d: # Hack for older versions with no logfile attribute
            logfile = util.newFilename( d['logfile'] )
        else:
            logfile = 'ambuild_1.log'
        self.setupLogging( logfile=logfile )
        
        if 'analyseLogfile' in d:
            logfile = util.newFilename( d['analyseLogfile'] )
        else:
            logfile = 'ambuild_1.csv'
        self._setupAnalyse( logfile=logfile )
        
        return
    
class TestCell(unittest.TestCase):
    
#     def setUp(self):
#         
#         thisd =  os.path.abspath( os.path.dirname( __file__ ) )
#         paths = thisd.split( os.sep )
#         self.ambuildDir = os.sep.join( paths[ : -1 ] )
#         
#         self.cx4Car = os.path.join( self.ambuildDir, "blocks", "cx4.car" )
#         self.ch4Car = os.path.join( self.ambuildDir, "blocks", "ch4.car" )
#         self.capLinker = os.path.join( self.ambuildDir, "blocks", "cap_linker.car" )
#         self.benzeneCar = os.path.join( self.ambuildDir, "blocks", "benzene.car" )
#         self.benzene2Car = os.path.join( self.ambuildDir, "blocks", "benzene2.car" )
#         self.pafCar = os.path.join( self.ambuildDir, "blocks", "PAF_bb_typed.car" )
#         
#         return

    @classmethod
    def setUpClass(cls):
        
        thisd =  os.path.abspath( os.path.dirname( __file__ ) )
        paths = thisd.split( os.sep )
        cls.ambuildDir = os.sep.join( paths[ : -1 ] )
        
        cls.cx4Car = os.path.join( cls.ambuildDir, "blocks", "cx4.car" )
        cls.ch4Car = os.path.join( cls.ambuildDir, "blocks", "ch4.car" )
        cls.capLinker = os.path.join( cls.ambuildDir, "blocks", "cap_linker.car" )
        cls.benzeneCar = os.path.join( cls.ambuildDir, "blocks", "benzene.car" )
        cls.benzene2Car = os.path.join( cls.ambuildDir, "blocks", "benzene2.car" )
        cls.pafCar = os.path.join( cls.ambuildDir, "blocks", "PAF_bb_typed.car" )
        cls.dcxCar = os.path.join( cls.ambuildDir, "blocks", "DCX.car" )
        cls.ch4Ca2Car = os.path.join( cls.ambuildDir, "blocks", "ch4Ca2.car" )
        
        print "START TEST CELL"
        if True:
            # Cell dimensions need to be: L > 2*(r_cut+r_buff) and L < 3*(r_cut+r_buff)
            # From code looks like default r_buff is 0.4 and our default r_cut is 5.0 
            CELLA = CELLB = CELLC = 20.0
            mycell = Cell()
            mycell.cellAxis (A=CELLA, B=CELLB, C=CELLC )
            mycell.addInitBlock(filename=cls.benzene2Car, fragmentType='A')
            mycell.addBondType( 'A:a-A:a')
            mycell.seed( 5 )
            mycell.growBlocks( 8 )
            print "FINISHED TEST CELL"
            cls.testCell = mycell
        
        return

    def testCX4(self):
        """First pass"""

        CELLA = CELLB = CELLC = 30
        
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock( fragmentType='A', filename=self.cx4Car )
        mycell.addBondType( 'A:a-A:a' )
        mycell.seed( 1 )
        mycell.growBlocks( 1 )
        
        return

    def XXXtimeCheck(self):
        """NOT A TEST JUST CODE TO TIME CHECKMOVE"""
    
        def cellFromPickle(pickleFile):
            with open(pickleFile) as f:
                myCell=cPickle.load(f)
            return myCell
        
        mycell = cellFromPickle("step_1.pkl")
        # Get the last block
        idxb = mycell.blocks.keys()[-1]
        b = mycell.blocks[ idxb ]
        be = b.freeEndGroups()[0]
         
        i =  mycell.getInitBlock()
        ie = i.freeEndGroups()[0]
         
        def run():
            global b, be, i, ie
            for _ in xrange( 1000):
                b.positionGrowBlock( be, i, ie, dihedral=None )
                blockId = mycell.addBlock( i )
                mycell.checkMove( blockId )
                mycell.delBlock(blockId)
        
        cProfile.run('run()','restats')
        return
    
    def testAmbody(self):
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock(filename=self.ch4Ca2Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        added = mycell.seed( 3 )
        
        self.assertEqual(added, 3)
        
        return

    def testBond(self):
        """First pass"""

        CELLA = CELLB = CELLC = 30
        
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        fragmentType='A'
        mycell.addInitBlock( fragmentType=fragmentType, filename=self.benzeneCar )
        mycell.addBondType( 'A:a-A:a' )
        
        centralBlock = mycell.getInitBlock( fragmentType=fragmentType )
        
        block1 = mycell.getInitBlock( fragmentType=fragmentType )
        block2 = mycell.getInitBlock( fragmentType=fragmentType )
        
        centralBlock.positionGrowBlock( centralBlock.freeEndGroups()[ 0 ], block1, block1.freeEndGroups()[ 0 ] )
        centralBlock.positionGrowBlock( centralBlock.freeEndGroups()[ 1 ], block2, block2.freeEndGroups()[ 0 ] )
        
        # Now add growBlock to the cell so we can check for clashes
        mycell.addBlock( block1 )
        mycell.addBlock( block2 )
        
        # Now add the central block - it will have 2 bonds to make
        centralId = mycell.addBlock( centralBlock )
        
        self.assertTrue( mycell.checkMove( centralId ), "checkMove failed!" )
        self.assertEqual( mycell.processBonds(), 2 )
        
        return

    def testBlockTypes(self):
        """Test we can add a block correctly"""
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock( fragmentType='A', filename=self.ch4Car )
        mycell.addInitBlock( fragmentType='B', filename=self.ch4Car)
        mycell.addInitBlock( fragmentType='C', filename=self.ch4Car )
        mycell.addInitBlock( fragmentType='D', filename=self.ch4Car )
        
        mycell.addBondType( 'A:a-B:a' )
        mycell.addBondType( 'A:a-C:a' )
        mycell.addBondType( 'A:a-D:a' )
        
        mycell.seed( 1, fragmentType='A' )
        toGrow = 3
        grew = mycell.growBlocks( toGrow, endGroupType=None, maxTries=5)
        
        self.assertEqual( toGrow, grew, "testBlockTypes not ok")
        return

    def XtestCapBlocks(self):
        self.testCell.capBlocks(fragmentType='A', filename=self.capLinker )
        #mycell.dump()
        block = self.testCell.blocks[ self.testCell.blocks.keys()[0] ]
        return
    
    def testCellIO(self):
        """Check we can write out and then read in a cell
        """
        
        # Remember a coordinate for checking
        test_coord = self.testCell.blocks[ self.testCell.blocks.keys()[0] ].atomCoord(4)
        
        outfile = "./testCellIO.pkl"
        self.testCell.writePickle( outfile )
        
        with open( outfile ) as f:
            newCell = cPickle.load( f )
            
        self.assertTrue( numpy.allclose( test_coord, self.testCell.blocks[ self.testCell.blocks.keys()[0] ].atomCoord(4), rtol=1e-9, atol=1e-9 ),
                         msg="Incorrect testCoordinate of cell.")
        
        self.testCell.growBlocks( 5 )
        
        os.unlink( outfile ) 
        
        return

    def testCloseAtoms1(self):
        
        CELLA = CELLB = CELLC = 2.1
        
        mycell = Cell( atomMargin=0.1, bondMargin=0.1, bondAngleMargin=15 )
        
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        mycell.addInitBlock(filename=self.ch4Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        block1 = mycell.getInitBlock('A')
        
        natoms = block1.numAllAtoms()
        
        # block radius is 1.8
        block1.translateCentroid( [ mycell.A/2, mycell.B/2, mycell.C/2 ] )
        block1Idx = mycell.addBlock(block1)
        
        # Alone in cell but in center
        self.assertFalse( mycell.closeAtoms(block1Idx) )
        
        # Add second block overlapping first but in other image
        block2 = mycell.getInitBlock('A')
        block2.translateCentroid( [ mycell.A/2 + mycell.A, mycell.B/2 + mycell.B, mycell.C/2 + mycell.C ] )
        block2Idx = mycell.addBlock(block2)
        
        # Make sure every atom overlaps with ever other
        self.assertEquals( natoms*natoms, len(mycell.closeAtoms(block1Idx) ) )
        
        # See we have enough clashing atoms - NOT CHECKED THIS NUMBER
        self.assertEquals( 15, mycell._checkMove( block2Idx ) )
        
        return

    def testCloseAtoms(self):
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell( atomMargin=0.1, bondMargin=0.1, bondAngleMargin=15 )
        
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        mycell.addInitBlock(filename=self.ch4Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        block1 = mycell.getInitBlock('A')
        
        block1.translateCentroid( [ 1, 1, 1 ] )
        block1_id = mycell.addBlock(block1)
        block2 = mycell.getInitBlock('A')
        block2.translateCentroid( [ 2.2, 2.2, 2.2 ] )
        block2_id = mycell.addBlock(block2)
        
        closeList =  mycell.closeAtoms(block1_id)
        # Updated refPairs as now have 
        refPairs = [ (0, 3), (1, 3), (2, 3) ] # Also used to check PBC
        closePairs = []
        for iatom, block, ioatom, distance in closeList:
            closePairs.append( (iatom,ioatom) )
            
        #mycell.writeXyz("close1.xyz", label=False)
            
        self.assertEqual(closePairs,
                        refPairs,
                         "Many contacts: {0}".format(closePairs))
        
        # Too far for any contacts
        mycell.delBlock(block2_id)
        block2 = mycell.getInitBlock('A')
        block2.translateCentroid( [10,10,10] )
        block2_id = mycell.addBlock(block2)
        
        close = mycell.closeAtoms(block1_id)
        self.assertFalse(close, "No contacts: ".format(close))
        
        # Now check across periodic boundary
        mycell.delBlock(block2_id)
        block2 = mycell.getInitBlock('A')
        x = 2.2 + 2 * mycell.A
        y = 2.2 + 2 * mycell.B
        z = 2.2 + 2 * mycell.C
        
        block2.translateCentroid( [x,y,z] )
        block2_id = mycell.addBlock(block2)
        
        #mycell.writeXyz("close2.xyz", label=False)
        
        closeList =  mycell.closeAtoms(block1_id)
        closePairs = []
        for iatom, block, ioatom, distance in closeList:
            closePairs.append( (iatom,ioatom) )

        self.assertEqual(closePairs, refPairs, "Periodic boundary: {}".format(closePairs))
        
        return
    
    def testCloseDistance(self):
        """
        Test distance and close together
        """
        CELLA = 30
        CELLB = 30
        CELLC = 30
        
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        #mycell.initCell("../ch4_typed.car",incell=False)
        #block1 = mycell.initBlock.copy()
        mycell.addInitBlock(filename=self.ch4Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        block1 = mycell.getInitBlock('A')
        
        
        b1 = numpy.array([2,2,2], dtype=numpy.float64 )
        block1.translateCentroid( b1 )
        block1_id = mycell.addBlock(block1)
        
        #block2=mycell.initBlock.copy()
        block2 = mycell.getInitBlock('A')
        b2 = numpy.array([3,3,3], dtype=numpy.float64 )
        block2.translateCentroid( b2 )
        block2_id = mycell.addBlock(block2)
        
        #mycell.writeXyz("close1.xyz", label=False)
        
#        closeList =  mycell.closeAtoms(block1_id)
#        for iatom, ioblock, ioatom in closeList:
#            b1c = block1._coords[iatom]
#            b2c = mycell.blocks[ioblock]._coords[ioatom]
#            distance = mycell.distance(b1c,b2c)
#            print "{}: {} -> {}:{} = {}".format(iatom,b1c,ioatom,b2c,distance)
            
        # Distance measured with Avogadro so it MUST be right...
        refd = 0.673354948616
        distance = mycell.distance( block1.atomCoord(1), mycell.blocks[ block2_id ].atomCoord(3) )
        self.assertAlmostEqual( refd, distance, 12, "Closest atoms: {}".format(distance) )
        
        return

    def testDistance(self):
        """Test the distance under periodic boundary conditions"""
        
        CELLA = CELLB = CELLC = 10
        
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        v1 = [ 2.46803012, 1.67131881, 1.96745421]
        v2 = [ 1.07988345, 0.10567109, 1.64897769]
        
        nv1 = numpy.array( v1 )
        nv2 = numpy.array( v2 )
        
        dc1 = mycell.distance(nv1,nv2)
        dn = numpy.linalg.norm(nv2-nv1)
        self.assertEqual( dc1, dn, "Distance within cell:{} | {}".format(dc1,dn) )
        
        x = v2[0] + 2 * CELLA
        y = v2[1] + 2 * CELLB
        z = v2[2] + 2 * CELLC
        nv2 = numpy.array([ x, y, z ])
        dc2 = mycell.distance(nv1,nv2)
        self.assertAlmostEqual( dc1, dc2, 11,"Distance across multiple cells +ve: {} | {}".format(dc1,dc2) )
        
        x = v2[0] - 2 * CELLA
        y = v2[1] - 2 * CELLB
        z = v2[2] - 2 * CELLC
        nv2 = numpy.array([ x, y, z ])
        dc3 = mycell.distance(nv1,nv2)
        self.assertAlmostEqual( dc1, dc3, 11, "Distance across multiple cells -ve: {} | {}".format(dc1,dc3) )
        
        v1 = numpy.array([ 0.0, 0.0, 0.0 ])
        v2 = numpy.array([ 0.0, 0.0, 8.0 ])
        dc = mycell.distance(v1,v2)
        self.assertEqual( dc, 2.0, "Distance across boundary cell:{}".format(dc) )
        
        return
        
    def testEndGroupTypes(self):
        """Test we can add a block correctly"""
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock( fragmentType='A', filename=self.ch4Car )
        mycell.addInitBlock( fragmentType='B', filename=self.ch4Car)
        mycell.addInitBlock( fragmentType='C', filename=self.ch4Car )
        mycell.addInitBlock( fragmentType='D', filename=self.ch4Car )
        
        # Everything can bond to A (apart from A itself), but nothing can bond to anything else 
        mycell.addBondType( 'A:a-B:a' )
        mycell.addBondType( 'A:a-C:a' )
        mycell.addBondType( 'A:a-D:a' )
        
        mycell.seed( 1, fragmentType='A' )
        mycell.seed( 1, fragmentType='B' )
        mycell.seed( 1, fragmentType='C' )
        
        banned = ['B:a','C:a','D:a']
        for _ in xrange( 5 ):
            cellEndGroup, libraryEndGroup = mycell.libraryEndGroupPair()
            if cellEndGroup.type() != 'A:a':
                self.assertNotIn( libraryEndGroup.type(),
                                  banned,
                                  "cell: {0} library: {1}".format( cellEndGroup.type(), libraryEndGroup.type() )
                                  )
        
        # Check it works if we give a cellEndGroup to bond
        cellEndGroup, libraryEndGroup = mycell.libraryEndGroupPair(cellEndGroups='B:a')
        
        # Check it fails if we ask for a block not in the cell
        self.assertRaises(RuntimeError, mycell.libraryEndGroupPair,{'cellEndGroups','D:a'} )
        
        # Check it works if we give it a list of libraryBlocks
        cellEndGroup, libraryEndGroup = mycell.libraryEndGroupPair(libraryEndGroups='B:a')
        self.assertEqual(  libraryEndGroup.type(),'B:a' )
        
        return
        
    def testGrowBlocks(self):
        """Test we can add blocks correctly"""
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock(filename=self.benzeneCar, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        added = mycell.seed( 1 )
        self.assertEqual( added, 1, 'seed')
        
        natoms = mycell.blocks.values()[0].numAllAtoms()
        
        nblocks=3
        added = mycell.growBlocks( nblocks, endGroupType=None, maxTries=1 )
        
        self.assertEqual( added, nblocks, "growBlocks did not return ok")
        self.assertEqual(1,len(mycell.blocks), "Growing blocks found {0} blocks".format( len(mycell.blocks) ) )
        
        natoms2 = mycell.blocks.values()[0].numAllAtoms()
        self.assertEqual( natoms2, natoms*(nblocks+1) )
        
        return
    
    def testGrowLimited(self):
        """Test we can add blocks correctly"""
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell(doLog=False)
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock(filename=self.dcxCar, fragmentType='A')
        mycell.addBondType( 'A:CH-A:CCl' )
        mycell.setMaxBond( 'A:CH', 1 )
        
        added = mycell.seed( 1 )
        mycell.growBlocks(10, endGroupType='A:CH')
        
        #mycell.dump()
        
        return

    def testGrowBlocks2(self):
        """Test we can add blocks correctly"""
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock(filename=self.benzeneCar, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')

        block1 = mycell.getInitBlock('A')
        
        # Position block so that it's aligned along x-axis
        # - use two opposing C-atoms 0 & 3
        block1.alignAtoms( 0, 3, [ 1, 0, 0 ] )
        
        # Now put it at the center of the cell
        block1.translateCentroid( [mycell.A/2, mycell.B/2, mycell.C/2] )
        
        # Add to the cell
        mycell.addBlock(block1)
        
        # Try adding 6 blocks - only 5 will fit
        nblocks=6
        added = mycell.growBlocks( nblocks, endGroupType=None, maxTries=5 )
        
        self.assertEqual( added, 5, "growBlocks did not add 5 blocks")
        self.assertEqual(1,len(mycell.blocks), "Growing blocks found {0} blocks".format( len(mycell.blocks) ) )
        
        return

    def testGrowBlocksDihedral(self):
        """Test we can add blocks correctly"""
        
        CELLA = CELLB = CELLC = 10
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock(filename=self.benzeneCar, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')

        added = mycell.seed( 1, center=True )
        
        nblocks=2
        dihedral=90
        added = mycell.growBlocks( nblocks, endGroupType=None, dihedral=dihedral, maxTries=5 )
        
        # Check angle between two specified dihedrals is correct
        block1 = mycell.blocks[ mycell.blocks.keys()[0] ]
        bond1 = block1.bonds()[0]
        
        p1 = block1.atomCoord( bond1.endGroup1.blockDihedralIdx )
        p2 = block1.atomCoord( bond1.endGroup1.blockEndGroupIdx )
        p3 = block1.atomCoord( bond1.endGroup2.blockEndGroupIdx )
        p4 = block1.atomCoord( bond1.endGroup2.blockDihedralIdx )
        
        self.assertAlmostEqual( math.degrees( util.dihedral( p1, p2, p3, p4) ), dihedral )
        
        return

    
    def testJoinBlocks(self):
        """Test we can add a block correctly"""
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        #mycell.addInitBlock(filename=self.pafCar, fragmentType='A')
        mycell.addInitBlock(filename=self.benzene2Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        toAdd = 5
        added = mycell.seed( toAdd )
        self.assertEqual( added, toAdd, 'seed')
        nc = 0
        for block in mycell.blocks.itervalues():
            nc += block.numAllAtoms()
        
        toJoin=4
        added = mycell.joinBlocks( toJoin, cellEndGroups=None, maxTries=1 )
        
        mycell.dump()
        
        self.assertEqual( added, toJoin, "joinBlocks did join enough")
        
        self.assertEqual( 1, len(mycell.blocks), "joinBlocks found {0} blocks".format( len( mycell.blocks ) ) )
        
        nc2 = 0
        for block in mycell.blocks.itervalues():
            nc2 += block.numAllAtoms()
            
        self.assertEqual(nc, nc2, "Growing blocks found {0} coords".format( nc2 ) )
        
        return
    
    def testOptimiseGeometry(self):
        """
        """
        
        #self.testCell.dump()
        self.testCell.optimiseGeometry( quiet=True )
        return
    
    def XtestOptimiseGeometryMinCell(self):
        """
        """
        
        # Create a large cell and populate it with a block
        CELLA = CELLB = CELLC = 100
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        mycell.addInitBlock( filename=self.benzeneCar, fragmentType='A' )
        mycell.addBondType( 'A:a-A:a' )

        mycell.seed( 1 )
        mycell.growBlocks(3,'A')
        
        # Get the block and put it in the centre of the cell
        block = mycell.blocks[ mycell.blocks.keys()[0] ]
        block.translateCentroid(  [ CELLA/2, CELLB/2, CELLC/2 ] )
        
        #mycell.dump()
        # Center of mass shouldn't have changed
        com = 0.0
        for blockIdx, block in mycell.blocks.iteritems():
            com += block.centerOfMass()
        
        mycell.optimiseGeometry(minCell=True, optAttempts=1 )
        
        comA = 0.0
        for blockIdx, block in mycell.blocks.iteritems():
            comA += block.centerOfMass()
        
        self.assertTrue( numpy.allclose( com, comA) )
            
        return
    
    def testOptimiseGeometryDihedral(self):
        """
        """
        self.testCell.optimiseGeometry( doDihedral=True, quiet=True )
        return
    
    def testRunMDAndOptimise(self):
        """
        """
        self.testCell.runMDAndOptimise( doDihedral=True, quiet=True )
        return
    
    def testRunMDandOpt(self):
        """
        """
        
        CELLA = CELLB = CELLC = 20.0
        mycell = Cell()
        mycell.cellAxis (A=CELLA, B=CELLB, C=CELLC )
        
        mycell.addInitBlock(filename=self.benzene2Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        mycell.seed( 5 )
        mycell.growBlocks( 8 )
        
        mycell.runMDAndOptimise( mdCycles=100, optCycles=10000, quiet=True )
        
        return
    
    def testPeriodic(self):
        
        import hoomdblue
        
        mycell = self.testCell
        
        # Grab coords
        coords = []
        for block in mycell.blocks.itervalues():
            for i, coord in enumerate( block.iterCoord() ):
                if block.ignoreAtom( i ):
                    continue
                coords.append( coord )
                
        # Wrap them
        wcoords = []
        images = []
        for c in coords:
            x, xi = util.wrapCoord( c[0], mycell.A, center=False )
            y, yi = util.wrapCoord( c[1], mycell.B, center=False )
            z, zi = util.wrapCoord( c[2], mycell.C, center=False )
            wcoords.append( [ x, y, z ] )
            images.append( [ xi, yi, zi ] )
        
        # Now umwrap them
        for i, c in enumerate( wcoords ):
            x = util.unWrapCoord( c[0], images[i][0], mycell.A, centered=False )
            y = util.unWrapCoord( c[1], images[i][1], mycell.B, centered=False )
            z = util.unWrapCoord( c[2], images[i][2], mycell.C, centered=False )
            
            self.assertAlmostEqual( x,
                                    coords[ i ][ 0 ],
                                    places=9,
                                    msg = "{0} {1}".format( x, coords[ i ][ 0 ] ) )
            self.assertAlmostEqual( y,
                                    coords[ i ][ 1 ],
                                    places=9,
                                    msg = "{0} {1}".format( y, coords[ i ][ 1 ] ) )
            self.assertAlmostEqual( z,
                                    coords[ i ][ 2 ],
                                    places=9,
                                    msg = "{0} {1}".format( z, coords[ i ][ 2 ] ) )
        
        # Now wrap them with centering
        wcoords = []
        images = []
        for c in coords:
            x, xi = util.wrapCoord( c[0], mycell.A, center=True )
            y, yi = util.wrapCoord( c[1], mycell.B, center=True )
            z, zi = util.wrapCoord( c[2], mycell.C, center=True )
            wcoords.append( [ x, y, z ] )
            images.append( [ xi, yi, zi ] )
        
        # Now umwrap them
        for i, c in enumerate( wcoords ):
            x = util.unWrapCoord( c[0], images[i][0], mycell.A, centered=True )
            y = util.unWrapCoord( c[1], images[i][1], mycell.B, centered=True )
            z = util.unWrapCoord( c[2], images[i][2], mycell.C, centered=True )
            
            self.assertAlmostEqual( x,
                                    coords[ i ][ 0 ],
                                    places=9,
                                    msg = "{0} {1}".format( x, coords[ i ][ 0 ] ) )

            self.assertAlmostEqual( y,
                                    coords[ i ][ 1 ],
                                    places=9,
                                    msg = "{0} {1}".format( y, coords[ i ][ 1 ] ) )
            self.assertAlmostEqual( z,
                                    coords[ i ][ 2 ],
                                    places=9,
                                    msg = "{0} {1}".format( z, coords[ i ][ 2 ] ) )
            
        # Now test with HOOMD-Blue
        filename = "periodicTest.xml"
        mycell.writeHoomdXml( xmlFilename=filename )
        if hoomdblue.init.is_initialized():
            hoomdblue.init.reset()
        system = hoomdblue.init.read_xml( filename=filename )
        
        wcoords = []
        for i, p in enumerate( system.particles ):
            x, y, z  = p.position
            ix, iy, iz = p.image
            
            x = util.unWrapCoord( x, ix, mycell.A, centered=True )
            y = util.unWrapCoord( y, iy, mycell.B, centered=True )
            z = util.unWrapCoord( z, iz, mycell.C, centered=True )
            
            self.assertAlmostEqual( x,
                                    coords[ i ][ 0 ],
                                    places=6,
                                    msg = "{0} {1}".format( x, coords[ i ][ 0 ] ) )

            self.assertAlmostEqual( y,
                                    coords[ i ][ 1 ],
                                    places=6,
                                    msg = "{0} {1}".format( y, coords[ i ][ 1 ] ) )
            self.assertAlmostEqual( z,
                                    coords[ i ][ 2 ],
                                    places=6,
                                    msg = "{0} {1}".format( z, coords[ i ][ 2 ] ) )
            
        
        os.unlink( filename )

        return
    
    def testSeed(self):
        """Test we can seed correctly"""
        
        
        CELLA = CELLB = CELLC = 50
        
        mycell = Cell()
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        
        mycell.addInitBlock( filename=self.benzeneCar, fragmentType='A' )
        mycell.addBondType( 'A:a-A:a' )
        
        nblocks = 10
        added = mycell.seed( nblocks )
        
        self.assertEqual( nblocks, added, "Incorrect number of cell blocks" )
        self.assertEqual( nblocks, len(mycell.blocks), "Incorrect number of cell blocks" )
        
        # Check no block is outside the unit cell
        # We seed by the centroid so the edges could stick out by radius
        #radius = ch4.radius()
        
        bad = []
        for i,b in mycell.blocks.iteritems():
            radius = b.radius()
            for c in b.iterCoord():
                if ( 0-radius > c[0] > CELLA[0]+ radius ) or \
                   ( 0-radius > c[1] > CELLB[1]+ radius ) or \
                   ( 0-radius > c[2] > CELLC[2]+ radius ):
                    
                    bad.append( b )
        
        self.assertEqual( 0, len(bad), "Got {} blocks outside cell: {}".format( len(bad), bad ) )
        
        #mycell.writeXyz("seedTest.xyz")
        
        return

    def testSurroundBoxes(self):
        """
        """
        mycell = Cell( )
        mycell.cellAxis( A=5, B=5, C=5 )
        # box size=1 - need to set manually as not reading in a block
        mycell.maxAtomRadius = 0.5
        mycell.atomMargin = 0.0
        
        mycell.boxSize = ( mycell.maxAtomRadius * 2 ) + mycell.atomMargin
        mycell.numBoxA = int(math.floor( mycell.A / mycell.boxSize ) )
        mycell.numBoxB = int(math.floor( mycell.B / mycell.boxSize ) )
        mycell.numBoxC = int(math.floor( mycell.C / mycell.boxSize ) )
        
        s = [(2, 2, 2), (2, 2, 1), (2, 2, 3), (2, 1, 2), (2, 1, 1), (2, 1, 3), (2, 3, 2), (2, 3, 1), 
         (2, 3, 3), (1, 2, 2), (1, 2, 1), (1, 2, 3), (1, 1, 2), (1, 1, 1), (1, 1, 3), (1, 3, 2),
          (1, 3, 1), (1, 3, 3), (3, 2, 2), (3, 2, 1), (3, 2, 3), (3, 1, 2), (3, 1, 1), (3, 1, 3), 
          (3, 3, 2), (3, 3, 1), (3, 3, 3)]
        self.assertEqual(s, mycell.surroundCells( (2,2,2) ), "in center")
        
        sb = mycell.surroundCells( (0,0,0) )
        s = [ (0, 0, 0), (0, 0, 4), (0, 0, 1), (0, 4, 0), (0, 4, 4), (0, 4, 1), (0, 1, 0), (0, 1, 4), 
        (0, 1, 1), (4, 0, 0), (4, 0, 4), (4, 0, 1), (4, 4, 0), (4, 4, 4), (4, 4, 1), (4, 1, 0), (4, 1, 4),
         (4, 1, 1), (1, 0, 0), (1, 0, 4), (1, 0, 1), (1, 4, 0), (1, 4, 4), (1, 4, 1), (1, 1, 0), (1, 1, 4), (1, 1, 1)]
        self.assertEqual(s, sb , "periodic: {0}".format( sb ) )
        return
    
    def testZipBlocks(self):

        CELLA = CELLB = CELLC = 12.0
        mycell = Cell(doLog=True)
        mycell.cellAxis (A=CELLA, B=CELLB, C=CELLC )
        
        ch4Car=self.ch4Car
        #mycell.addInitBlock(filename=self.benzeneCar, fragmentType='A')
        mycell.addInitBlock(filename=ch4Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        # Create block manually
        b1 = buildingBlock.Block( filePath=ch4Car, fragmentType='A'  )
        b2 = buildingBlock.Block( filePath=ch4Car, fragmentType='A'  )
        b3 = buildingBlock.Block( filePath=ch4Car, fragmentType='A'  )
        b4 = buildingBlock.Block( filePath=ch4Car, fragmentType='A'  )
        
        # b1 in center of cell
        b1.translateCentroid( [ mycell.A/2, mycell.B/2, mycell.C/2 ] )
        mycell.addBlock(b1)
        endGroup1 = b1.freeEndGroups()[ 0 ]
        endGroup2 = b2.freeEndGroups()[ 0 ]
        
        # Position b2 - all blocks will be positioned around this one
        b1.positionGrowBlock( endGroup1, b2, endGroup2, dihedral=180 )
        mycell.addBlock(b2)
        
        # Position b3
        endGroup1 = b2.freeEndGroups()[ 1 ]
        endGroup2 = b3.freeEndGroups()[ 0 ]
        b2.positionGrowBlock( endGroup1, b3, endGroup2, dihedral=180 )
        mycell.addBlock(b3)
        
        # Position b4
        endGroup1 = b2.freeEndGroups()[ 2 ]
        endGroup2 = b4.freeEndGroups()[ 0 ]
        b2.positionGrowBlock( endGroup1, b4, endGroup2, dihedral=180 )
        mycell.addBlock(b4)
        
        made = mycell.zipBlocks( bondMargin=0.5, bondAngleMargin=0.5 )
        
        self.assertEqual(made,3)
        
        return

    def testZipBlocks2(self):

        CELLA = CELLB = CELLC = 12.0
        mycell = Cell(doLog=True)
        mycell.cellAxis (A=CELLA, B=CELLB, C=CELLC )
        
        mycell.addInitBlock(filename=self.benzeneCar, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        # Create block manually
        b1 = buildingBlock.Block( filePath=self.benzeneCar, fragmentType='A'  )
        b2 = buildingBlock.Block( filePath=self.benzeneCar, fragmentType='A'  )
        
        # Position block so that it's aligned along x-axis
        # - use two opposing C-atoms 0 & 3
        b1.alignAtoms( 0, 3, [ 1, 0, 0 ] )
        
        b1.translateCentroid( [ mycell.A/2, mycell.B/2, mycell.C/2 ] )
        
        endGroup1 = b1.freeEndGroups()[ 0 ]
        endGroup2 = b2.freeEndGroups()[ 0 ]
        
        # Position the block
        b1.positionGrowBlock( endGroup1, b2, endGroup2 )
        
        # and bond
        bond = buildingBlock.Bond(endGroup1, endGroup2)
        b1.bondBlock( bond )
        
        b1_id = mycell.addBlock(b1)
        
        made = mycell.zipBlocks( bondMargin=5, bondAngleMargin=5 )
        
        self.assertEqual( made, 1)
        return

    def testZipBlocks3(self):
        """Bonding with margin"""

        CELLA = CELLB = CELLC = 12.0
        mycell = Cell(doLog=True)
        mycell.cellAxis (A=CELLA, B=CELLB, C=CELLC )
        
        ch4Car=self.ch4Car
        mycell.addInitBlock(filename=ch4Car, fragmentType='A')
        mycell.addBondType( 'A:a-A:a')
        
        # Create block manually
        b1 = buildingBlock.Block( filePath=ch4Car, fragmentType='A' )
        b2 = buildingBlock.Block( filePath=ch4Car, fragmentType='A' )
        
        # Align bond along x-axis
        b1.alignAtoms( 0, 1, [ 1, 0, 0 ] )
        
        # b1 in center of cell
        b1.translateCentroid( [ mycell.A/2, mycell.B/2, mycell.C/2 ] )
        mycell.addBlock(b1)
        
        endGroup1 = b1.freeEndGroups()[ 0 ]
        endGroup2 = b2.freeEndGroups()[ 0 ]
        
        # Position b2
        b1.positionGrowBlock( endGroup1, b2, endGroup2, dihedral=180 )
        mycell.addBlock(b2)
        
        # Rotate on y-axis so that it's slightly off
        b2.rotateT([0,1,0],math.radians(15))
        
        made = mycell.zipBlocks( bondMargin=0.5, bondAngleMargin=5 )
        self.assertEqual( made, 0 )
        
        made = mycell.zipBlocks( bondMargin=0.5, bondAngleMargin=16 )
        self.assertEqual( made, 1 )
        
        return
    
    def testWriteHoomdblue(self):
        """
        write out hoomdblue xml
        """
        
        import hoomdblue
        
        CELLA = CELLB = CELLC = 30
        
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        #mycell.addInitBlock( filename=self.ch4Car, fragmentType='A' )
        mycell.addInitBlock( filename=self.benzeneCar, fragmentType='A' )
        mycell.addBondType( 'A:a-A:a' )
        
        added = mycell.seed( 3 )
        ok = mycell.growBlocks( 3, maxTries=5 )
        
        initcoords = []
        for block in mycell.blocks.itervalues():
            for c in block.iterCoord():
                initcoords.append( c )
        
        filename = "testWriteHoomdblue.xml"
        natoms = mycell.writeHoomdXml( xmlFilename=filename )

        # Init the sytem from the file
        if hoomdblue.init.is_initialized():
            hoomdblue.init.reset()
        system = hoomdblue.init.read_xml( filename=filename )
        
        # Read it back in to make sure we get the same values
        mycell.fromHoomdblueSystem( system )
        
        finalcoords = []
        for block in mycell.blocks.itervalues():
            for c in block.iterCoord():
                finalcoords.append( c )
        
        self.assertTrue( all( map( lambda x : numpy.allclose( x[0], x[1] ),  zip( initcoords, finalcoords ) ) ),
                         "coords don't match")
        
        #os.unlink( filename )
        
        return

    def XtestWriteHoomdblueMinCell(self):
        """
        write out hoomdblue xml
        """
        
        import hoomdblue
        
        # Create a large cell and populate it with a block
        CELLA = CELLB = CELLC = 100
        mycell = Cell( )
        mycell.cellAxis(A=CELLA, B=CELLB, C=CELLC)
        mycell.addInitBlock( filename=self.ch4Car, fragmentType='A' )
        mycell.addBondType( 'A:a-A:a' )

        mycell.seed( 1 )
        mycell.growBlocks(3,'A')
        
        # Get the block and put it in the centre of the cell
        block = mycell.blocks[ mycell.blocks.keys()[0] ]
        block.translateCentroid(  [ CELLA/2, CELLB/2, CELLC/2 ] )

        initcoords = []
        for block in mycell.blocks.itervalues():
            initcoords += block._coords
        
        filename = "testWriteHoomdblue.xml"
        natoms = mycell.writeHoomdXml( xmlFilename=filename )

        # Init the sytem from the file
        if hoomdblue.init.is_initialized():
            hoomdblue.init.reset()
        system = hoomdblue.init.read_xml( filename=filename )
        
        # Read it back in to make sure we get the same values
        mycell.fromHoomdblueSystem( system, minCell=True )
        
        finalcoords = []
        for block in mycell.blocks.itervalues():
            finalcoords += block._coords
        
        self.assertEqual( initcoords, finalcoords, "coords don't match")
        
        os.unlink( filename )
        
        return

if __name__ == '__main__':
    """
    Run the unit tests
    """
    unittest.main()
