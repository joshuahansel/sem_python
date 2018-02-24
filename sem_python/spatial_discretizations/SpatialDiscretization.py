from abc import ABCMeta, abstractmethod

from ..input.Parameters import Parameters


class SpatialDiscretizationParameters(Parameters):

    def __init__(self, factory):
        Parameters.__init__(self, factory)
        self.registerParameter("factory", "Factory")


## Base class for spatial discretizations
class SpatialDiscretization(object, metaclass=ABCMeta):
    def __init__(self, params):
        self.factory = params.get("factory")

        self.createDoFHandler()

    @abstractmethod
    def createDoFHandler(self):
        pass

    @abstractmethod
    def createAssemblyObjects(self):
        pass