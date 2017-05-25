import os
import sys
base_dir = os.environ["SEM_PYTHON_DIR"]

import unittest

sys.path.append(base_dir + "src/aux")
from Pressure import Pressure, PressureParameters
from TestAux import TestAux, TestAuxParameters

sys.path.append(base_dir + "testing/src/utilities")
from AuxDerivativesTester import AuxDerivativesTester

def computePressure(v, e):
  v_slope = 2.0
  e_slope = 3.0
  p = v_slope * v + e_slope * e
  return (p, v_slope, e_slope)

# pressure aux
params = PressureParameters()
params.set("p_function", computePressure)
test_aux = Pressure(params)
test_var = "p"

# specific volume aux
params = TestAuxParameters()
params.set("var", "v")
params.set("other_vars", ["vf1", "arho"])
params.set("coefs", [2.0, 3.0])
v_aux = TestAux(params)

# specific internal energy aux
params = TestAuxParameters()
params.set("var", "e")
params.set("other_vars", ["arho", "arhou", "arhoE"])
params.set("coefs", [2.5, 3.5, 4.5])
e_aux = TestAux(params)

other_aux = {"v" : v_aux, "e" : e_aux}
other_vars = ["v", "e"]
root_vars = ["vf1", "arho", "arhou", "arhoE"]

class PressureDerivativesTester(unittest.TestCase):
  def setUp(self):
    self.derivatives_tester = AuxDerivativesTester()

  def test(self):
    rel_diffs = self.derivatives_tester.checkDerivatives(
      test_aux, test_var, other_aux, other_vars, root_vars)
    for key in rel_diffs:
      self.assertLessEqual(rel_diffs[key], 1e-6)

if __name__ == "__main__":
  derivatives_tester = AuxDerivativesTester(True)
  _ = derivatives_tester.checkDerivatives(
    test_aux, test_var, other_aux, other_vars, root_vars)
