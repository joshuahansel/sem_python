import unittest

import sem
from InputFileModification import InputFileModification
from CSVTester import CSVTester
from JunctionTester import JunctionTester

class CompressibleJunctionTester(unittest.TestCase):
  def runDerivativeTest(self, test_weak, use_momentum_flux_balance):
    tester = JunctionTester("CompressibleJunction")
    rel_diffs = tester.checkJacobian(test_weak,
      junction_params={"use_momentum_flux_balance": use_momentum_flux_balance})
    n_i, n_j = rel_diffs.shape
    for i in xrange(n_i):
      for j in xrange(n_j):
        self.assertLessEqual(rel_diffs[i,j], 1e-6)

  def testJacobianWeakTechnique1(self):
    self.runDerivativeTest(True, False)

  def testJacobianStrongTechnique1(self):
    self.runDerivativeTest(False, False)

  def testJacobianWeakTechnique2(self):
    self.runDerivativeTest(True, True)

  def testJacobianStrongTechnique2(self):
    self.runDerivativeTest(False, True)

if __name__ == "__main__":
  tester = JunctionTester("CompressibleJunction", verbose=True)
  print "\nTECHNIQUE 1: Stagnation pressure"
  _ = tester.checkJacobian(True, junction_params={"use_momentum_flux_balance": False})
  _ = tester.checkJacobian(False, junction_params={"use_momentum_flux_balance": False})
  print "\nTECHNIQUE 2: Momentum flux balance"
  _ = tester.checkJacobian(True, junction_params={"use_momentum_flux_balance": True})
  _ = tester.checkJacobian(False, junction_params={"use_momentum_flux_balance": True})
