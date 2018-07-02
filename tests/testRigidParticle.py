'''
Created on 4 Mar 2018

@author: jmht
'''
import math
import os
import unittest
import numpy as np

import context
BLOCKS_DIR = context.ab_paths.BLOCKS_DIR
PARAMS_DIR = context.ab_paths.PARAMS_DIR
from context import ab_fragment
from context import ab_rigidparticle
from context import xyz_core
from context import xyz_util

# Not sure where best to do this
xyz_util.setModuleBondLength(os.path.join(PARAMS_DIR, "bond_params.csv"))

class Test(unittest.TestCase):
    
    def testRigidParticleConfig(self):
        class Cell(object):
            """Mock Cell object for testing"""
            def __init__(self, rigidParticleMgr):
                self.rigidParticleMgr = rigidParticleMgr
        
        rigidParticleMgr = ab_rigidparticle.RigidParticleManager()
        cell = Cell(rigidParticleMgr)
        
        ch4ca = os.path.join(BLOCKS_DIR, "ch4Ca2.car")
        ftype = 'A'
        f1 = ab_fragment.Fragment(filePath=ch4ca, fragmentType=ftype, cell=cell)
        
        configStr = {'1AA0000': 'AB', '2AA0000': 'AC', '0AA0000': 'AA'}
        self.assertEqual(rigidParticleMgr._configStr, configStr)
        self.assertEqual(len(rigidParticleMgr._configStr), len(rigidParticleMgr._configs))
        
        b1 = list(f1.bodies())[0]
        quat_origin = np.array([1.0, 0.0, 0.0, 0.0])
        self.assertTrue(np.allclose(rigidParticleMgr.orientation(b1), quat_origin, rtol=0.0001))
        self.assertEqual(rigidParticleMgr.configStr(b1), "AA")
        
        # Rotate fragment and see if we get a different orientation
        axis = np.array([1, 0, 0])
        angle = math.pi / 3
        rotationMatrix = xyz_core.rotation_matrix(axis, angle)
        f1.rotate(rotationMatrix, f1._centerOfMass)
        b1 = list(f1.bodies())[0]
        ref_q = np.array([0.866, 0.5, 0.0, 0.0]) 
        self.assertTrue(np.allclose(rigidParticleMgr.orientation(b1), ref_q, atol=0.0001))
        
        return
    
    def testRigidParticle(self):
        class Cell(object):
            """Mock Cell object for testing"""
            def __init__(self, rigidParticleMgr):
                self.rigidParticleMgr = rigidParticleMgr
        
        rigidParticleMgr = ab_rigidparticle.RigidParticleManager()
        cell = Cell(rigidParticleMgr)    

        ch4 = os.path.join(BLOCKS_DIR, "ch4.car")
        ftype = 'A'
        f1 = ab_fragment.Fragment(filePath=ch4, fragmentType=ftype, cell=cell)
        
        rp = list(f1.bodies())[0].rigidParticle()
        quat_origin = np.array([1.0, 0.0, 0.0, 0.0])
        self.assertTrue(np.allclose(rp.orientation, quat_origin, rtol=0.0001))

#     def testFragmentMgrConfig(self):
#         ch4 = os.path.join(BLOCKS_DIR, "ch4.car")
#         f1 = ab_fragment.Fragment(filePath=ch4, fragmentType='A')
#         self.assertTrue(f1.fragmentType in ab_fragment.configManager.configs)
#         self.assertTrue(len(ab_fragment.configManager.configs) == 1)
#         
#         f2 = f1.copy()
#         self.assertTrue(len(ab_fragment.configManager.configs) == 1)
# 
#         eg1 = f1.freeEndGroups()[0]
#         eg2 = f2.freeEndGroups()[0]
#         bond = ab_bond.Bond(eg1, eg2)
#         bond.endGroup1.setBonded(bond)
#         bond.endGroup2.setBonded(bond)
#         self.assertTrue(len(ab_fragment.configManager.configs[f1.fragmentType]) == 2)
# 
#         eg1 = f1.freeEndGroups()[-1]
#         eg2 = f2.freeEndGroups()[0]
#         bond = ab_bond.Bond(eg1, eg2)
#         bond.endGroup1.setBonded(bond)
#         bond.endGroup2.setBonded(bond)
#         self.assertTrue(len(ab_fragment.configManager.configs[f1.fragmentType]) == 4)
# 
#         f1 = ab_fragment.Fragment(filePath=ch4, fragmentType='B')
#         self.assertTrue(len(ab_fragment.configManager.configs) == 2)
#         
#     def testFragmentMgrConfigCalc(self):
#         idx = 0
#         cid = ab_fragment.FragmentConfigManager.calcConfigStr(idx)
#         self.assertTrue(cid, 'AA')
#         
#         idx = 26 * 26 - 1
#         cid = ab_fragment.FragmentConfigManager.calcConfigStr(idx)
#         self.assertTrue(cid, 'ZZ')
#         
#         idx = idx + 1
#         try:
#             ab_fragment.FragmentConfigManager.calcConfigStr(idx)
#         except AssertionError:
#             pass
#         except Exception as e:
#             self.fail("Unexpected exception: {}".format(e))
#     
#     def testFragmentConfigStr(self):
#         ch4 = os.path.join(BLOCKS_DIR, "ch4.car")
#         ftype = 'A'
#         f1 = ab_fragment.Fragment(filePath=ch4, fragmentType=ftype)
#         self.assertEqual(ftype + "0000", f1.configStr)
#         
#         for eg in f1.endGroups():
#             eg.bonded = True
#         f1.update()
#         self.assertEqual(ftype + "1111", f1.configStr)


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
