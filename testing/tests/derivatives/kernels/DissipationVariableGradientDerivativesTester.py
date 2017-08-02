import unittest

import os
import sys
base_dir = os.environ["SEM_PYTHON_DIR"]

sys.path.append(base_dir + "src/base")
from enums import ModelType, VariableName

sys.path.append(base_dir + "testing/src/utilities")
from KernelDerivativesTester import KernelDerivativesTester

class DissipationVariableGradientDerivativesTester(unittest.TestCase):
  def setUp(self):
    self.derivatives_tester = KernelDerivativesTester()

  def test1Phase(self):
    aux = {"visccoef_arhou1": ["arho1", "arhou1", "arhoE1"]}
    kernel_params = {"var": VariableName.ARhoU}
    rel_diffs = self.derivatives_tester.checkDerivatives("DissipationVariableGradient", ModelType.OnePhase, 0, aux, kernel_params)
    for key in rel_diffs:
      self.assertLessEqual(rel_diffs[key], 1e-6)

  def test2Phase(self):
    aux = {"visccoef_vf1": ["vf1", "arho1", "arhou1", "arhoE1"]}
    kernel_params = {"var": VariableName.VF1}
    rel_diffs = self.derivatives_tester.checkDerivatives("DissipationVariableGradient", ModelType.TwoPhase, 0, aux, kernel_params)
    for key in rel_diffs:
      self.assertLessEqual(rel_diffs[key], 5e-6)

if __name__ == "__main__":
  aux = {"visccoef_arhou1": ["vf1", "arho1", "arhou1", "arhoE1"]}
  kernel_params = {"var": VariableName.ARhoU}
  derivatives_tester = KernelDerivativesTester(True)
  _ = derivatives_tester.checkDerivatives("DissipationVariableGradient", ModelType.TwoPhase, 0, aux, kernel_params)