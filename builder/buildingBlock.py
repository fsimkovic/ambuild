'''
Created on Jan 15, 2013

@author: abbietrewin

Things to look at:
http://stackoverflow.com/questions/11108869/optimizing-python-distance-calculation-while-accounting-for-periodic-boundary-co

http://en.wikipedia.org/wiki/Periodic_boundary_conditions

http://mail.scipy.org/pipermail/scipy-dev/2012-March/017177.html
https://groups.google.com/forum/?fromgroups=#!topic/scipy-user/P6k8LEo30ws
https://github.com/patvarilly/periodic_kdtree
'''

# Python imports
import copy
import os
import random
import unittest

# external imports
import numpy

# local imports
import util

class Block():
    '''
    classdocs
    '''

    def __init__( self, infile=None ):
        '''
        Constructor
        '''
        
        
        # List of all the blocks that constitute this one
        # start by adding ourselves - needs to be the instances we 
        # we use these to loop over all coordinates, etc
        self.blocks = [ self ]
        
        # The _endGroups where the blocks are attached: id(block) : idxEG
        self.blockEndGroups = {}
        
        # The id of the parent block of this one (if we have one)
        self.parent = None
        # the coordinates for this block - see __getattr__ for how coords are dealt with
        self.coords = []
        
        # ordered array of labels
        self.labels = []
        
        # ordered array of symbols (in upper case)
        self.symbols = []
        
        # ordered array of masses
        self.masses = []
        
        # orderd array of atom radii
        self.atom_radii = []
        
        # List of the cell (3-tuple) to which each atom belongs
        self.atomCell = []
        
        # Dict of dicts mapping atom types to their bond lengths for this block
        # used so we only check the types of atoms for this type of block
        # For now we assume that both blocks have the same atom types
        self._labels2bondlength = {}
        
        # A list of the indices of the atoms that are _endGroups
        self._endGroups = []
        
        # List of the indices of the atoms that define the angle for the _endGroups - need
        # to be in the same order as the _endGroups
        self._angleAtoms = []
        
        # Holds the center of mass of the molecule
        self._centerOfMass = numpy.zeros( 3 )
        # Holds the center of geometry of the molecule
        self._centerOfGeometry = numpy.zeros( 3 )
        
        # The radius of the block assuming it is a circle centered on the centroid
        self._radius = 0
        
        # Total mass of the block
        self._mass = None
        
        # Flag to indicate if block has changed and parameters (such as centerOfMass)
        # need to be changed
        self._changed = True
        
        if infile:
            if infile.endswith(".car"):
                self.fromCarFile( infile )
            elif infile.endswith(".xyz"):
                self.fromXyzFile( infile )
            else:
                raise RuntimeError("Unrecognised file suffix: {}".format(infile) )
            

    def alignBond(self, idxBlockEG, refVector ):
        """
        Align this block, so that the bond defined by idxBlockEG is aligned with
        the refVector
        
        This assumes that the block has already been positioned with the contact atom at the origin
        """
        
        endGroup = self.endGroupCoord( idxBlockEG )
        
        # Check neither is zero
        if numpy.array_equal( refVector, [0,0,0] ) or numpy.array_equal( endGroup, [0,0,0] ):
            raise RuntimeError, "alignBlock - one of the vectors is zero!\nrefVector: {0} endGroup: {1}".format( refVector, endGroup )
        
        # Makes no sense if they are already aligned
        if numpy.array_equal( endGroup/numpy.linalg.norm(endGroup), refVector/numpy.linalg.norm(refVector) ):
            print "alignBlock - block already aligned along vector. May not be a problem, but you should know..."
            return

#        print "alignBlock BEFORE: {0} | {1}".format( endGroup, refVector )

        # Calculate normalised cross product to find an axis orthogonal 
        # to both that we can rotate about
        cross = numpy.cross( refVector, endGroup )
        
        if numpy.array_equal( cross, [0,0,0] ):
            # They must be already aligned but anti-parallel, so we flip
            print "alignBlock - vectors are anti-parallel so flipping"
            self.flip( refVector )
        else:
            
            # Find angle
            angle = util.vectorAngle( refVector, endGroup )
            
            # Normalised cross to rotate about
            ncross = cross / numpy.linalg.norm( cross )
            
            # Rotate
            self.rotate( ncross, angle )
            
#        endGroup =self.coords[ idxBlockEG ]
#        print "alignBlock AFTER: {0} | {1}".format( endGroup, refVector )
        return

    def angleAtomCoord(self, idxEndGroup):
        """Return the coordinate of the angleAtom for the endGroup with the given index."""
        
        idxCoord = self._angleAtoms[ idxEndGroup ]
        return self.coords[ idxCoord ]
    
    def bond(self, block, bond):
        """Bond the two blocks at the given bond - tuple is indices of self and other bond
        """
        
        #print block
        #print "with"
        #print self
        
        # Needed to work out how much to add to the block indices
        lcoords = len(self.coords)
        
        self.coords.extend( block.coords )
        self.atom_radii.extend( block.atom_radii )
        self.labels.extend( block.labels )
        
        #jmht hack
#        print "CHANGING LABEL TO Cl AS BONDING! "
#        for i,l in enumerate(self.labels):
#            if l[0] == 'H':
#                self.labels[i] = 'Cl'+l[1:]

        self.symbols.extend( block.symbols )
        self.masses.extend( block.masses )
        self.atomCell.extend( block.atomCell )
        
        # Need to remove the end groups used in the bond
        #i = self._endGroups.index( bond[0] )
        #self._endGroups.pop( i )
        self._endGroups.pop( bond[0] )
        #i = block._endGroups.index( bond[1] )
        #block._endGroups.pop( i )
        block._endGroups.pop( bond[1] )
        
        # Now add block to self, updating index
        for i in block._endGroups:
            self._endGroups.append( i+lcoords )
        
        del self._angleAtoms[ bond[0] ]
        del block._angleAtoms[ bond[1] ]
        
        #for k,v in block._angleAtoms.iteritems():
        #    self._angleAtoms[ k+lcoords ] = v+lcoords
            
        for i in block._angleAtoms:
            self._angleAtoms.append( i+lcoords )
            
        self.update()

    def join( self, idxEG, block, idxBlockEG ):
        """Bond block to this one at the _endGroups specified by the two indices
        endGroup = [ 7, 12, 17, 22 ]
        defAtom = [ 5, 6, 7, 8 ]
        
        idxEndGroup = randomEndGroupIndex()
        
        endGroup = block.coords[ block._endGroups[idxEndGroup] ]
        
        angleAtom = block.coords[ block._angleAtoms[idxEndGroup] ]
        
              H1
              |
              C0
          /  |  \
        H2   H3  H4
        
              H1             H6
              |              |
             C0             C5
          /  |  \        /  |  \
        H2   H3  H4 -- H7   H8  H9
        
        CH4 - 1
        _endGroups = [ 1,2,3,4 ]
        _angleAtoms = [ 0,0,0,0 ]
        bondedEndGroups = []
        
        CH4 - 2
        _endGroups = [ 1,2,3,4 ]
        _angleAtoms = [ 0,0,0,0 ]
        bondedEndGroups = []
        
        join 2,3 
        _endGroups = [ 1,2,4,6,7,8 ]
        _angleAtoms = [ 0,0,0,5,5,5 ]
        
        
        # Need to remember the _endGroups/_angleAtoms for each block
        # First is this block - although not used unless all blocks removed to leave us with ourselves
        blockEndGroups = [  [ 1,2,3,4 ], [ 1,2,3,4 ] ]
        blockAngleAtoms = [ [ 0,0,0,0 ], [ 0,0,0,0 ] ]
        
        So remove the bond we are making from both blocks and then add the new _endGroups/_angleAtoms
        # Remember the actual indices of the _endGroups for the parent block in the bondedEndGroups array of tuples
        bondedEndGroups.append(  ( _endGroups.pop( 2 ), _angleAtoms.pop( 2 ) ) )
        
        # Add the new free endgroups and their _angleAtoms to the array - we increment their indices accordingly
        for i, EG in enumerate( block._endGroups ):
            _endGroups.append( EG + start )
            _angleAtoms.append( block._angleAtoms[i] + start )
            
        
        # random
        0 1 2 3
        H-C=C-H
        _endGroups = [ 0,3 ]
        _angleAtoms = [ 1,2 ]
        
        0 1 2 3 4 5 6 7
        H-C=C-H_H-C=C-H
        _endGroups = [ 0, 7 ]
        _angleAtoms = [ 1, 6 ]
        
        0 1 2 3 4 5 6 7 8 9 1011
        H-C=C-H_H-C=C-H_H-C=C-H
        _endGroups = [ 0, 11 ]
        _angleAtoms = [ 1, 10 ]
        
        removeBlock( 0 )
        0 1 2 3 4 5 6 7
        H-C=C-H_H-C=C-H
        _endGroups = [ 0, 7 ]
        _angleAtoms = [ 1, 6 ]
        
        and 
        0 1 2 3
        H-C=C-H
        _endGroups = [ 0,3 ]
        _angleAtoms = [ 1,2 ]
        
        
        
        """
        
        # Needed to work out how much to add to the block indices
        start = len( self.coords )
        end = len( block.coords )
        
        # Keep track of where the new block starts and ends so we can remove it
        self.blocks.append[ (start, end)  ]
        
        # Add all the data structures together
        self.coords.extend( block.coords )
        self.atom_radii.extend( block.atom_radii )
        self.labels.extend( block.labels )
        self.symbols.extend( block.symbols )
        self.masses.extend( block.masses )
        self.atomCell.extend( block.atomCell )
        
        # Need to remove the end groups used in the bond
        self.bondedEndGroups.append( )
        
        i = self._endGroups.index( bond[0] )
        self._endGroups.pop( i )
        i = block._endGroups.index( bond[1] )
        block._endGroups.pop( i )
        
        # Now add block to self, updating index
        for i in block._endGroups:
            self._endGroups.append( i+start )
        
        del self._angleAtoms[ bond[0] ]
        del block._angleAtoms[ bond[1] ]
        
        for k,v in block._angleAtoms.iteritems():
            self._angleAtoms[ k+start ] = v+start
        
        self.update()

    def bondLength(self,symbola, symbolb):
        """Return the bond length between two atoms of the given type"""
        return self._labels2bondlength[symbola][symbolb]
    
        
    def createFromArgs(self, coords, labels, endGroups, angleAtoms ):
        """ Create from given arguments
        """
        # could check if numpy array here
        self.coords = coords
        self.labels = labels
        self._endGroups = endGroups
        self._angleAtoms = angleAtoms
        
        # Fill atomCell list
        self.atomCell = [None]*len(self.coords)
        
        self.fillData()
        
        self.update()
        
    def createFromLabelAndCoords(self, labels, coords):
        """ Given an array of labels and another of coords, create a block
        This requires determining the end groups and contacts from the label
        """
        
        # array of indexes
        endGroups = []
        egAaLabel = []
        
        # For tracking the mapping of the label used to mark the angle atom
        # to the true index of the atom
        aaLabel2index = {}
        
        for i, label in enumerate(labels):
            
            # End groups and the atoms which define their bond angles 
            # are of the form XX_EN for endgroups and XX_AN for the defining atoms
            # where N can be any number, but linking the two atoms together 
            # The indexing of the atoms starts from 1!!!!
            if "_" in label:
                _, ident = label.split("_")
                atype=ident[0]
                anum=int(ident[1:])
                
                if atype.upper() == "E":
                    # An endGroup
                    if i in endGroups:
                        raise RuntimeError,"Duplicate endGroup key for: {0} - {1}".format( i, endGroups )
                    endGroups.append(i)
                    egAaLabel.append( anum )
                    
                elif atype.upper() == "A":
                    if aaLabel2index.has_key(anum):
                        raise RuntimeError,"Duplicate angleAtom key for: {0} - {1}".format(anum, aaLabel2index)
                    aaLabel2index[ anum ] = i
                else:
                    raise RuntimeError,"Got a duff label! - {}".format(label)
        
#        #Now match up the endgroups with their angle atoms
        angleAtoms = []
        for label in egAaLabel:
            angleAtoms.append( aaLabel2index[ label ]  )
        
        #self.createFromArgs(coords, labels, endGroups, endGroupContacts)
        self.createFromArgs( coords, labels, endGroups, angleAtoms )
  
    def calcCenterOfMassAndGeometry(self):
        """Calculate the center of mass and geometry
        """
        
        sumG = numpy.zeros( 3 )
        sumM = numpy.zeros( 3 )
        
        totalMass = 0.0
        for i, coord in enumerate( self.coords ):
            mass = self.masses[i]
            totalMass += mass
            sumG += coord
            sumM += mass * coord
        
        self._centerOfGeometry = sumG / (i+1)
        self._centerOfMass = sumM / totalMass
        
        
    def calcRadius(self):
        """
        Calculate a simple size metric of the block so that we can screen for whether
        two blocks are within touching distance
        
        First try a simple approach with a loop just to get a feel for things
        - Find the largest distance between any atom and the center of geometry
        - Get the covalent radius of that atom
        - return that distance + radius + buffer
        
        Should move to use scipy as detailed here:
        http://stackoverflow.com/questions/6430091/efficient-distance-calculation-between-n-points-and-a-reference-in-numpy-scipy
        """
        
        cog = self.centroid()
        
        distances = []
        for coord in self.coords:
            #distances.append( numpy.linalg.norm(coord-cog) )
            distances.append( util.distance(cog, coord) )
            
        imax = numpy.argmax( distances )
        dist = distances[ imax ]
        atomR = self.atom_radii[ imax ]
        
        # Set radius
        self._radius = dist + atomR
        
        
    def centroid(self):
        """
        Return or calculate the center of geometry for the building block.
        """
        
        if self._changed:
            self.calcCenterOfMassAndGeometry()
            self._changed = False
        
        return self._centerOfGeometry
        
    def centerOfMass(self):
        """
        Return or calculate the center of mass for the building block.
        """
        if self._changed:
            self.calcCenterOfMassAndGeometry()
            self._changed = False
        
        return self._centerOfMass
    
    def copy( self ):
        """
        Create a copy of ourselves and return it.
        Hit problem when passing in the distance function from the cell as the deepcopy
        also had a copy of the cell
        """
        return copy.deepcopy(self)

    def endGroupCoord(self, idxEndGroup):
        """Return the coordinate of the endGroup with the given index."""
        return self.coords[ self.endGroupCoordIdx( idxEndGroup ) ]
    
    def endGroupCoordIdx(self, idxEndGroup):
        """Return the index of the coordinate of the endGroup with the given index."""
        return self._endGroups[ idxEndGroup ]
    
    def endGroupSymbol(self, idxEndGroup ):
        """Return the symbol of this endGroup"""
        return self.symbols[ self.endGroupCoordIdx( idxEndGroup ) ]
    
    def flip( self, fvector ):
        """Rotate perpendicular to fvector so we  facing the opposite way along the fvector
        """
        
        # Find vector perpendicular to the bond axis
        # Dot product needs to be 0
        # xu + yv + zw = 0 - set u and v to 1, so w = (x + y)/z
        # vector is 1, 1, w
        w =  -1.0 * ( fvector[0] + fvector[1] ) / fvector[2]
        orth = numpy.array( [1.0, 1.0, w] )
        
        # Find axis that we can rotate about
        rotAxis = numpy.cross( fvector, orth )
        
        # Rotate by 180
        self.rotate( rotAxis, numpy.pi )
        
        return


    def fillData(self):
        """ Fill the data arrays from the label """
        
        if len(self.labels) < len(self.coords):
            raise RuntimeError("fillData needs labels filled!")
        
        symbol_types=[]
        for label in self.labels:
            
            # Symbols
            symbol = util.label2symbol( label )
            self.symbols.append( symbol )
            
            # For checking bonding
            if symbol not in symbol_types:
                symbol_types.append(symbol)
                
            # Masses
            self.masses.append( util.ATOMIC_MASS[ symbol ] )
            
            # Radii
            z = util.SYMBOL_TO_NUMBER[ symbol ]
            r = util.COVALENT_RADII[z] * util.BOHR2ANGSTROM
            self.atom_radii.append(r)
            #print "ADDING R {} for label {}".format(r,label)
            
            # Add bond lengths
            
        
        # make a dict mapping all atom types to their bonds to speed lookups
        # not sure if this actually saves anything...
        for i_symbol in symbol_types:
            self._labels2bondlength [ i_symbol ] = {}
            for j_symbol in symbol_types:
                bond_length = util.bondLength( i_symbol , j_symbol )
                self._labels2bondlength[ i_symbol ][ j_symbol ] = bond_length

    def fromCarFile(self, carFile):
        """"Abbie did this.
        Gulp...
        """
        labels = []
        
        # numpy array
        coords = []
        
        reading = True
        with open( carFile, "r" ) as f:
            
            # First 4 lines just info - not needed
            f.readline()
            f.readline()
            f.readline()
            f.readline()
            
            count=0
            while reading:
                line = f.readline()
                
                line = line.strip()
                fields = line.split()
                label = fields[0]
                
                # Check end of coordinates
                if label.lower() == "end":
                    reading=False
                    break
                     
                labels.append(label)
                
                coords.append( numpy.array(fields[1:4], dtype=numpy.float64) )
                
                count+=1
        
        self.createFromLabelAndCoords( labels, coords )

    def fromXyzFile(self, xyzFile ):
        """"Jens did this.
        """
        
        labels = []
        
        # numpy array
        coords = []
        
        with open( xyzFile ) as f:
            
            # First line is number of atoms
            line = f.readline()
            natoms = int(line.strip())
            
            # Skip title
            line = f.readline()
            
            count = 0
            for _ in range(natoms):
                
                line = f.readline()
                line = line.strip()
                fields = line.split()
                label = fields[0]
                labels.append(label) 
                coords.append( numpy.array(fields[1:4], dtype=numpy.float64) )
                
                count += 1

        self.createFromLabelAndCoords( labels, coords )

    def maxAtomRadius(self):
        """Return the maxium atom radius
        """
        
        rmax=0
        for r in self.atom_radii:
            if r>rmax:
                rmax=r
        return rmax
    
    def mass(self):
        """Total mass of the molecule
        """
        if not self._mass:
            self._mass = 0.0
            for m in self.masses:
                self._mass += m
        return self._mass
                

    def positionGrowBlock( self, idxBlockEG, growBlock, idxGrowBlockEG ):
        """
        Position growBlock so it can bond to us, using the given _endGroups
        
        Arguments:
        idxBlockEG: the index of the endGroup to use for the bond
        growBlock: the block we are positioning
        idxGrowBlockEG: the index of the endGroup to use for the bond
        """

        # The vector we want to align along is the vector from the angleAtom
        # to the endGroup
        endGroup = self.endGroupCoord( idxBlockEG )
        angleAtom = self.angleAtomCoord( idxBlockEG )
        refVector =  endGroup - angleAtom
        
        # Get the angleAtom for the growBlock
        #idxGrowBlockContact = growBlock._angleAtoms[ idxGrowBlockEG ]
        #growBlockAngleAtom = growBlock.coords[ idxGrowBlockContact ]
        growBlockAngleAtom = growBlock.angleAtomCoord( idxGrowBlockEG )
        
        # get the coord where the next block should bond
        # symbol of endGroup tells us the sort of bond we are making which determines
        # the bond length
        symbol = growBlock.symbols[ growBlock._endGroups[ idxGrowBlockEG ] ]
        bondPos = self.newBondPosition( idxBlockEG, symbol )
        #print "got bondPos: {}".format( bondPos )
        
        # Shift block so angleAtom at center, so the vector of the endGroup can be
        # aligned with the refVector
        growBlock.translate( -growBlockAngleAtom )
        
        # Align along the staticBlock bond
        growBlock.alignBond( idxGrowBlockEG, refVector )
        
        # Now turn the second block around
        # - need to get the new vectors as these will have changed due to the moves
        growBlockEG = growBlock.endGroupCoord( idxGrowBlockEG )
        
        # Flip by 180 along bond axis
        growBlock.flip( growBlockEG )
        
        # Now need to place the endGroup at the bond coord - at the moment
        # the contact atom is on the origin so we need to subtract the vector to the endGroup
        # from the translation vector
        #jmht FIX!
        growBlock.translate( bondPos + growBlockEG )
        
        return

    def newBondPosition(self, idxTargetEG, symbol ):
        """Return the position where a bond to an atom of type 'symbol'
        would be placed if bonding to the target endgroup
         I'm sure this algorithm is clunky in the extreme...
        """
        
        targetEndGroupIdx = self._endGroups[ idxTargetEG ] 
        targetEndGroup = self.coords[ targetEndGroupIdx ]
        targetContactIndex = self._angleAtoms[ idxTargetEG ]
        targetContact = self.coords[ targetContactIndex ]
        targetSymbol = self.symbols[ targetEndGroupIdx ]
        
        # Get the bond length between these two atoms
        bondLength = util.bondLength( targetSymbol, symbol )
        
        # vector from target EndGroup contact to Endgroup
        bondVec =  targetEndGroup - targetContact 
        
        # Now extend it by Bondlength
        vLength = numpy.linalg.norm( bondVec )
        ratio = ( vLength + bondLength ) / vLength
        newVec = bondVec * ratio
        diff = newVec-bondVec
        newPosition = targetEndGroup + diff
        
        return newPosition
 
    def radius(self):
        
        if self._changed:
            self.calcCenterOfMassAndGeometry()
            self.calcRadius()
            self._changed = False
        
        return self._radius

    def randomEndGroupIndex(self):
        """Select a random endGroup - return the index in the _endGroup array"""
        #return random.choice( self._endGroups )
        return random.randint( 0, len(self._endGroups)-1 )

    def randomRotate( self, origin=[0,0,0], atOrigin=False ):
        """Randomly rotate a block.
        
         Args:
         atOrigin -- flag to indicate if the block is already positioned at the origin
        """
        
        if not atOrigin:
            position = self.centroid()
            self.translateCentroid( origin )
            
        
        xAxis = [ 1, 0, 0 ]
        yAxis = [ 0, 1, 0 ]
        zAxis = [ 0, 0, 1 ]
        
        angle = random.uniform( 0, 2*numpy.pi)
        self.rotate( xAxis, angle )
        
        angle = random.uniform( 0, 2*numpy.pi)
        self.rotate( yAxis, angle )
        
        angle = random.uniform( 0, 2*numpy.pi)
        self.rotate( zAxis, angle )
        
        if not atOrigin:
            self.translateCentroid( position )

    def rotate( self, axis, angle, center=None ):
        """ Rotate the molecule about the given axis by the angle in radians
        """
        
        if center==None:
            center = numpy.array([0,0,0])
        
        rmat = util.rotation_matrix( axis, angle )
        
        # loop through all blocks and change all coords
        # Need to check that the center bit is the best way of doing this-
        # am almost certainly doing more ops than needed
        for block in self.blocks:
            for i,coord in enumerate( block.coords ):
                #self.coords[i] = numpy.dot( rmat, coord )
                coord = coord - center
                coord = numpy.dot( rmat, coord )
                block.coords[i] = coord + center
        
        self._changed = True

    def translate(self, tvector):
        """ translate the molecule by the given vector"""
        
        # Make sure its a numpy array - is this needed?
        if isinstance(tvector,list):
            tvector = numpy.array( tvector )

        for block in self.blocks:
            # Use len as we don't need to return hthe coords
            for i in range( len (block.coords ) ):
                block.coords[i] += tvector
        
        self._changed = True
    
    def translateCentroid( self, position ):
        """Translate the molecule so the center of geometry moves
        to the given coord
        """
        self.translate( position - self.centroid() )
        
    def update(self):
        """
        Run any methods that need to be done when the coordinates are changed
        """
        # Recalculate the data for this new block
        self.calcCenterOfMassAndGeometry()
        self.calcRadius()
        
    def writeXyz(self,name=None):
        
        if not name:
            name = str(id(self))+".xyz"
            
        with open(name,"w") as f:
            fpath = os.path.abspath(f.name)
            f.write( "{}\n".format(len(self.coords)) )
            f.write( "id={}\n".format(str(id(self))) )
                             
            for i,c in enumerate(self.coords):
                f.write("{0:5} {1:0< 15}   {2:0< 15}   {3:0< 15}\n".format( util.label2symbol(self.labels[i]), c[0], c[1], c[2]))
        
        print "Wrote file: {0}".format(fpath)
        
    def __str__(self):
        """
        Return a string representation of the molecule
        """
        
        mystr = ""
        mystr += "BlockID: {}\n".format(id(self))
        mystr += "{}\n".format(len(self.coords))
        for i,c in enumerate(self.coords):
            #mystr += "{0:4}:{1:5} [ {2:0< 15},{3:0< 15},{4:0< 15} ]\n".format( i+1, self.labels[i], c[0], c[1], c[2])
            mystr += "{0:5} {1:0< 15} {2:0< 15} {3:0< 15} \n".format( self.labels[i], c[0], c[1], c[2])
            
        mystr += "radius: {}\n".format( self.radius() )
        mystr += "COM: {}\n".format( self._centerOfMass )
        mystr += "COG: {}\n".format( self._centerOfGeometry )
        mystr += "_endGroups: {}\n".format( self._endGroups )
        mystr += "_angleAtoms: {}\n".format( self._angleAtoms )
        
        return mystr
    
    def __add__(self, other):
        """Add two blocks - INCOMPLETE AND ONLY FOR TESTING"""
        self.coords += other.coords
        self.labels += other.labels
        self.symbols += other.symbols
        
        return self
        
        
class TestBuildingBlock(unittest.TestCase):

    def makeCh4(self):
        """Create a CH4 molecule for testing"""
        
#        coords = [ numpy.array([  0.000000,  0.000000,  0.000000 ] ),
#        numpy.array([  0.000000,  0.000000,  1.089000 ]),
#        numpy.array([  1.026719,  0.000000, -0.363000 ]),
#        numpy.array([ -0.513360, -0.889165, -0.363000 ]),
#        numpy.array([ -0.513360,  0.889165, -0.363000 ]) ]
#
#        #numpy.array([ -0.513360,  0.889165, -0.363000 ]) ]
#        labels = [ 'C', 'H', 'H', 'H', 'H' ]
#        
#        _endGroups = [ 1,2,3,4 ]
#        
#        endGroupContacts = { 1:0, 2:0, 3:0, 4:0 }
#        
#        ch4 = Block()
#        ch4.createFromArgs( coords, labels, _endGroups, endGroupContacts )

        ch4 = Block()
        ch4.fromXyzFile("../ch4.xyz")
        return ch4
    
    def makePaf(self):
        """Return the PAF molecule for testing"""
        
        paf = Block()
        paf.fromCarFile("../PAF_bb_typed.car")
        return paf
    
    
    def testAaaReadCar(self):
        """
        Test we can read a car file - needs to come first
        """
        
        paf = self.makePaf()
        self.assertTrue( paf._angleAtoms == [ 1, 2, 3, 4 ], "Incorrect reading of endGroup contacts: {0}".format(paf._angleAtoms))

    def testAaaReadXyz(self):
        """
        Test we can read an xyz file - needs to come first
        """
        
        paf = self.makeCh4()
        self.assertTrue( paf._angleAtoms == [0,0,0,0], "Incorrect reading of endGroup contacts")
        
    def testAlignBlocks(self):
        """Test we can align two blocks correctly"""
    
        blockS = self.makePaf()
        block = blockS.copy()
        
        block.translateCentroid( [3,4,5] )
        block.randomRotate()
        
        # Get the atoms that define things
        idxEndGroup = 2
        blockSEndGroup = blockS.endGroupCoord( idxEndGroup )
        blockSContact = blockS.angleAtomCoord( idxEndGroup )
        
        idxEndGroup = 3
        blockContact = block.angleAtomCoord( idxEndGroup )
        
        # we want to align along block1Contact -> block1EndGroup
        refVector = blockSEndGroup - blockSContact 
        
        # Position block so contact is at origin
        block.translate( -blockContact )
        
        block.alignBond( idxEndGroup, refVector )
        
        # Check the relevant atoms are in the right place
        blockEndGroup  = block.endGroupCoord( idxEndGroup )
        blockContact = block.angleAtomCoord( idxEndGroup )
        
        newVector = blockEndGroup - blockContact
        
        # Normalise two vectors so we can compare them
        newNorm = newVector / numpy.linalg.norm(newVector)
        refNorm = refVector / numpy.linalg.norm(refVector)
        
        # Slack tolerances - need to work out why...
        self.assertTrue( numpy.allclose( newNorm, refNorm),
                         msg="End Group incorrectly positioned: {0} | {1}".format(newNorm, refNorm )  )

    def testPositionGrowBlock(self):
        
        blockS = self.makePaf()
        growBlock = blockS.copy()
        
        growBlock.translateCentroid( [3,4,5] )
        growBlock.randomRotate()
        
#        testb = blockS.copy()
#        testb += growBlock
#        testb.writeXyz("b4.xyz")
        
        # Get the atoms that define things
        idxBlockEndGroup = 2
        idxGrowBlockEndGroup = 3
        
        
        # Get position to check
        newPos = blockS.newBondPosition( idxBlockEndGroup, growBlock.endGroupSymbol( idxGrowBlockEndGroup ) )
        
        # Position the block
        blockS.positionGrowBlock( idxBlockEndGroup, growBlock, idxGrowBlockEndGroup )
        
        # After move, the endGroup of the growBlock should be at newPos
        endGroupCoord = growBlock.endGroupCoord( idxGrowBlockEndGroup )
        self.assertTrue( numpy.allclose( newPos, endGroupCoord, rtol=1e-9, atol=1e-7 ),
                         msg="testCenterOfMass incorrect COM.")
        
#        testb = blockS.copy()
#        testb += growBlock
#        testb.writeXyz("after.xyz")


    def XtestBond(self):
        """Test we can correctly bond two blocks at the given bond"""
        
        ch4 = self.makeCh4()
        m2 = ch4.copy()
        m2.translate( numpy.array( [2, 2, 2] ) )
        
        bond = (3,2)
        ch4.bond(m2, bond)
        
        self.assertTrue( ch4._endGroups == [1,2,4,6,8,9], "Incorrect calculation of _endGroups")
        self.assertTrue( ch4._angleAtoms == {1: 0, 2: 0, 4: 0, 6: 5, 8: 5, 9: 5}, "Incorrect calculation of endGroup contacts")
    

    def testCenterOfGeometry(self):
        """
        Test calculation of Center of Geometry
        """
        
        correct = numpy.array([  0.000000,  0.000000,  0.000000 ])
        ch4 = self.makeCh4()
        cog = ch4.centroid()
        self.assertTrue( numpy.allclose( correct, cog, rtol=1e-9, atol=1e-6 ),
                         msg="testCenterOfGeometry incorrect COM.")

    def testCenterOfMass(self):
        """
        Test calculation of Center of Mass
        """
        
        correct = numpy.array([  0.000000,  0.000000,  0.000000 ])
        ch4 = self.makeCh4()
        com = ch4.centerOfMass()
        self.assertTrue( numpy.allclose( correct, com, rtol=1e-9, atol=1e-7 ),
                         msg="testCenterOfMass incorrect COM.")
        
#        #m.writeXyz(name="after.xyz")
#        print m
#        print m.centerOfMass()
#        m.translate([1,1,1])
#        
#        #m.writeXyz(name="trans.xyz")
#        print m
#        print m.centerOfMass()


    def testMove(self):
        """Test we can move correctly"""
        
        paf = self.makePaf()
        m = paf.copy()
        m.translate( numpy.array( [5,5,5] ) )
        c = m.centroid()
        paf.translateCentroid( c )
        p = paf.centroid()
        
        self.assertTrue( numpy.allclose( p, c, rtol=1e-9, atol=1e-9 ), "simple move")
        
    def testRadius(self):
        """
        Test calculation of the radius
        """
        
        ch4 = self.makeCh4()
        r = ch4.radius()
        #jmht - check...- old was: 1.78900031214
        self.assertAlmostEqual(r, 1.45942438719, 7, "Incorrect radius: {}".format(str(r)) )
        
    def testRotate(self):
        """
        Test the rotation
        """
        
        ch4 = self.makeCh4()
        array1 = numpy.array([ -0.51336 ,  0.889165, -0.363 ])
        self.assertTrue( numpy.array_equal( ch4.coords[4], array1 ),
                         msg="testRotate arrays before rotation incorrect.")
        
        axis = numpy.array([1,2,3])
        angle = 2
        ch4.rotate(axis, angle)
        
        array2 = numpy.array([  1.05612011, -0.04836936, -0.26113713 ])

        # Need to use assertTrue as we get a numpy.bool returned and need to test this will
        # bool - assertIs fails
        self.assertTrue( numpy.allclose( ch4.coords[4], array2, rtol=1e-9, atol=1e-8 ),
                         msg="testRotate arrays after rotation incorrect.")

    def makeH2C2(self):
        """
        Return H2C2 molecule for testing
        """
        coords = [ 
                  numpy.array([  0.000000,  0.000000,  0.000000 ] ),
                  numpy.array([  0.000000,  0.000000,  1.000000 ]),
                  numpy.array([  0.000000,  0.000000,  2.000000 ]),
                  numpy.array([  0.000000,  0.000000,  3.000000 ]),
                  ]

        labels = [ 'H', 'C', 'C', 'H' ]
        endGroups = [ 0, 3 ]
        angleAtoms = [ 1, 2 ]
        b = Block()
        b.createFromArgs( coords, labels, endGroups, angleAtoms )
        return b
        
    def XtestNew(self):
        """
        test new coordinate class
        """
        
        b1 = self.makeH2C2()
        b2 = b1.copy()
        
        idxB1EG = 0
        idxB2EG = 1
        
        
        #print b1
        b1.positionGrowBlock( idxB1EG, b2, idxB2EG )
        
        #print b1
        #print b2
        
        #b1.join( idxB1EG, b2, idxB2EG )
        
        #b1.writeXyz()
        
        
        
        
        
if __name__ == '__main__':
    """
    Run the unit tests
    """
    unittest.main()
        