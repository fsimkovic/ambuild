'''
Created on 4 Mar 2018

@author: jmht
'''
import os
import unittest

import context
BLOCKS_DIR = context.ab_paths.BLOCKS_DIR
PARAMS_DIR = context.ab_paths.PARAMS_DIR
from context import ab_fragment
from context import xyz_util

xyz_util.setModuleBondLength(os.path.join(PARAMS_DIR, "bond_params.csv"))


class Test(unittest.TestCase):
    def testFragmentConfigStr(self):
        ch4 = os.path.join(BLOCKS_DIR, "ch4.car")
        ftype = 'A'
        f1 = ab_fragment.Fragment(filePath=ch4, fragmentType=ftype)
        cstr = ftype + "0000"
        self.assertEqual(cstr, f1.configStr)
        
        for eg in f1.endGroups():
            eg.bonded = True
        f1.update()
        cstr = ftype + "1111"
        self.assertEqual(cstr, f1.configStr)

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()