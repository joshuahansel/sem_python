import os
import sys
base_dir = os.environ["SEM_PYTHON_DIR"]

sys.path.append(base_dir + "src/aux")
from AuxQuantity1Phase import AuxQuantity1Phase, AuxQuantity1PhaseParameters

class SoundSpeedParameters(AuxQuantity1PhaseParameters):
  def __init__(self):
    AuxQuantity1PhaseParameters.__init__(self)
    self.registerFunctionParameter("c_function", "Sound speed function from EOS")

class SoundSpeed(AuxQuantity1Phase):
  def __init__(self, params):
    AuxQuantity1Phase.__init__(self, params)
    self.c_function = params.get("c_function")

  def compute(self, data, der):
    c, dc_dv, dc_de = self.c_function(data[self.v], data[self.e])
    data[self.c] = c

    dc_dvf1 = dc_dv * der[self.v]["vf1"]
    dc_darho = dc_dv * der[self.v][self.arho] + dc_de * der[self.e][self.arho]
    dc_darhou = dc_de * der[self.e][self.arhou]
    dc_darhoE = dc_de * der[self.e][self.arhoE]
    der[self.c] = {"vf1" : dc_dvf1, self.arho : dc_darho, self.arhou : dc_darhou, self.arhoE : dc_darhoE}