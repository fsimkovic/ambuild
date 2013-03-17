'''
Created on Jan 15, 2013

@author: abbietrewin



'''

import cell
import cPickle


INFILE = "../PAF_bb_typed.car" 
#INFILE = "../ch4_typed.car" 
#INFILE = "./afterSeed.bust.xyz"
OUTFILE1 = "afterSeed.xyz"
#OUTFILE2 = "afterSeedLabel.xyz"
#OUTFILE2 = "../SHIMMY_0_lab.xyz"
OUTFILE3 = "afterShimmy.xyz"
# for ch4: 4,4,4,4
# 35,10,10,10
#
#for paf: 4, 15, 15, 15
nblocks = 30
CELLA = 40
CELLB = 40
CELLC = 40

STEPS = 1000
MOVES=100

# Create Cell and seed it with the blocks
mycell = cell.Cell()
mycell.cellAxis( CELLA, CELLB, CELLC )

#import pdb
#pdb.set_trace()
mycell.seed( nblocks, INFILE )
pfile = open("pickle1.pkl","w")
cPickle.dump(mycell,pfile)
pfile.close()
#mycell.writeXyz( OUTFILE1 )
#mycell.writeXyz( OUTFILE2, label=True )
#mycell.writeXyz("canBond.xyz", label=False)


mycell.shimmy(nsteps=STEPS, nmoves=MOVES)
pfile = open("pickle2.pkl","w")
cPickle.dump(mycell,pfile)
pfile.close()
#mycell.writeXyz( OUTFILE3 )


## Loop through as many shimmy stages as required
#while True:
#    OUTFILE=util.newFilename(OUTFILE)
#    #cell.shimmy( nsteps=STEPS, nmoves=NMOVES, bondAngle=BONDANGLE  )
#    new_cell.directedShimmy( nsteps=STEPS, nmoves=NMOVES, bondAngle=BONDANGLE )
#    new_cell.write( OUTFILE )
#    response = raw_input('Do we have to do this _again_? (y/n)')
#    if response.lower() == 'n':
#        break
    

