"""
Created on 4 Mar 2018

@author: jmht
"""
import os
import shutil
import unittest

from context import ab_cell
from context import ab_poreblazer
from context import PARAMS_DIR, BLOCKS_DIR


class Test(unittest.TestCase):
    def testDummy(self):
        """Run with a dummy executable just to make sure the code runs"""
        boxWidth = 20.0
        boxDim = [boxWidth, boxWidth, boxWidth]
        mycell = ab_cell.Cell(boxDim, paramsDir=PARAMS_DIR)
        ch4Car = os.path.join(BLOCKS_DIR, "ch4.car")
        mycell.libraryAddFragment(filename=ch4Car, fragmentType="A")
        mycell.addBondType("A:a-A:a")
        mycell.seed(
            3,
            fragmentType="A",
            point=[boxWidth / 2, boxWidth / 2, boxWidth / 2],
            radius=5,
        )
        mycell.growBlocks(4)
        # Run with a dummy executable
        mycell.poreblazer("/bin/cat")
        pdir = "{}_{}".format(ab_poreblazer.NAME_STEM, 0)
        self.assertTrue(os.path.isfile(os.path.join(pdir, "ambuild.xyz")))
        self.assertTrue(os.path.isfile(os.path.join(pdir, "defaults.dat")))
        os.unlink("ambuild.csv")
        os.unlink("ambuild.log")
        shutil.rmtree(pdir)
        return


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
