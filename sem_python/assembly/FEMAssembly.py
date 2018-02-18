from copy import deepcopy
import numpy as np

from .Assembly import Assembly, AssemblyParameters
from ..base.enums import ModelType, VariableName
from ..utilities.assembly_utilities import initializeDerivativeData


class FEMAssemblyParameters(AssemblyParameters):

    def __init__(self, factory):
        AssemblyParameters.__init__(self, factory)
        self.registerParameter("quadrature", "Quadrature")
        self.registerParameter("stabilization", "Stabilization")
        self.registerBoolParameter("group_fem", "Use group FEM?", False)
        self.registerBoolParameter("lump_mass_matrix", "Lump the mass matrix?", False)


class FEMAssembly(Assembly):

    def __init__(self, params):
        Assembly.__init__(self, params)
        self.quadrature = params.get("quadrature")
        stabilization = params.get("stabilization")
        self.group_fem = params.get("group_fem")
        self.lump_mass_matrix = params.get("lump_mass_matrix")

        self.need_solution_gradients = stabilization.needSolutionGradients()

        # FE values
        fe_values_params = {
            "quadrature": self.quadrature,
            "dof_handler": self.dof_handler,
            "meshes": self.meshes
        }
        self.fe_values = self.factory.createObject("FEValues", fe_values_params)

        # set local solution update function
        if self.model_type == ModelType.OnePhase:
            self.computeLocalCellSolution = self.computeLocalCellSolutionOnePhase
            self.computeLocalNodeSolution = self.computeLocalNodeSolutionOnePhase
            self.getLocalNodalSolution = self.getLocalNodalSolutionOnePhase
        else:
            self.computeLocalCellSolution = self.computeLocalCellSolutionTwoPhase
            self.computeLocalNodeSolution = self.computeLocalNodeSolutionTwoPhase
            self.getLocalNodalSolution = self.getLocalNodalSolutionTwoPhase

        # add aux from stabilization
        self.aux_list += stabilization.createAuxQuantities()

        # get list of aux quantities
        self.aux_names = [aux.name for aux in self.aux_list]

        # create nodal aux quantities if needed by group FEM
        if self.group_fem:
            self.nodal_aux_list = deepcopy(self.aux_list) + self.createNodalAuxQuantities()
            self.nodal_aux_names = [aux.name for aux in self.nodal_aux_list]

            self.group_fem_interp_aux_list = self.createInterpolatedAux()
            self.group_fem_aux_names = [aux.name for aux in self.group_fem_interp_aux_list]
        else:
            self.nodal_aux_list = list()
            self.nodal_aux_names = list()
            self.group_fem_interp_aux_list = list()
            self.group_fem_aux_names = list()

        # create advection kernels
        self.fem_kernels = self.createAdvectionKernels() + stabilization.createKernels()

        # add source kernels to kernel lists
        self.fem_kernels += self.source_kernels

    def createNodalAuxQuantities(self):
        aux_list = list()
        for phase in self.model.phases:
            for aux_name in ["MassFlux", "MomentumFlux", "EnergyFlux"]:
                aux_list.append(self.factory.createObject(aux_name, {"phase": phase}))

        return aux_list

    def createInterpolatedAux(self):
        aux_list = list()

        for phase in self.model.phases:
            phase_str = str(phase + 1)
            arhoA = "arhoA" + phase_str
            arhouA = "arhouA" + phase_str
            arhoEA = "arhoEA" + phase_str

            # mass
            var = "inviscflux_arhoA" + phase_str
            params = {
                "variable": var,
                "dependencies": [arhouA],
                "n_test_functions": self.dof_handler.n_dof_per_cell_per_var
            }
            aux_list.append(self.factory.createObject("InterpolatedAux", params))

            # momentum
            var = "inviscflux_arhouA" + phase_str
            params = {
                "variable": var,
                "dependencies": ["aA1", arhoA, arhouA, arhoEA],
                "n_test_functions": self.dof_handler.n_dof_per_cell_per_var
            }
            aux_list.append(self.factory.createObject("InterpolatedAux", params))

            # energy
            var = "inviscflux_arhoEA" + phase_str
            params = {
                "variable": var,
                "dependencies": ["aA1", arhoA, arhouA, arhoEA],
                "n_test_functions": self.dof_handler.n_dof_per_cell_per_var
            }
            aux_list.append(self.factory.createObject("InterpolatedAux", params))

        return aux_list

    def createAdvectionKernels(self):
        kernels = list()
        for phase in self.model.phases:
            if self.group_fem:
                phase_str = str(phase + 1)
                var_enums = [VariableName.ARhoA, VariableName.ARhoUA, VariableName.ARhoEA]
                aux_vars = [
                    "inviscflux_arhoA" + phase_str, "inviscflux_arhouA" + phase_str,
                    "inviscflux_arhoEA" + phase_str
                ]
                for var_enum, aux_var in zip(var_enums, aux_vars):
                    params = {
                        "var_enum": var_enum,
                        "aux_name": aux_var,
                        "phase": phase,
                        "dof_handler": self.dof_handler
                    }
                    kernels.append(self.factory.createObject("InterpolatedAdvection", params))
            else:
                params = {"phase": phase, "dof_handler": self.dof_handler}
                kernel_name_list = [
                    "MassAdvection", "MomentumAdvection", "MomentumAreaGradient", "EnergyAdvection"
                ]
                for kernel_name in kernel_name_list:
                    kernels.append(self.factory.createObject(kernel_name, params))

        if self.model.phase_interaction:
            params1 = {"phase": 0, "dof_handler": self.dof_handler}
            params2 = {"phase": 1, "dof_handler": self.dof_handler}

            kernels.append(self.factory.createObject("VolumeFractionAdvection", params1))
            kernels.append(self.factory.createObject("MomentumVolumeFractionGradient", params1))
            kernels.append(self.factory.createObject("MomentumVolumeFractionGradient", params2))
            kernels.append(self.factory.createObject("EnergyVolumeFractionGradient", params1))
            kernels.append(self.factory.createObject("EnergyVolumeFractionGradient", params2))

        return kernels

    # computes the steady-state residual and Jacobian without applying strong BC
    def assembleSteadyStateSystemWithoutConstraints(self, U):
        r = np.zeros(self.dof_handler.n_dof)
        J = np.zeros(shape=(self.dof_handler.n_dof, self.dof_handler.n_dof))

        # volumetric terms
        self.addVolumetricTerms(U, r, J)

        # BCs
        for bc in self.bcs:
            bc.applyWeakBC(U, r, J)

        # junctions
        for junction in self.junctions:
            junction.applyWeaklyToNonlinearSystem(U, r, J)

        return (r, J)

    def performTransientSetup(self):
        self.M = self.computeMassMatrix()

    def computeMassMatrix(self):
        M = np.zeros(shape=(self.dof_handler.n_dof, self.dof_handler.n_dof))

        self.addMassMatrixPhase(M, 0)
        if (self.model_type != ModelType.OnePhase):
            self.addMassMatrixPhase(M, 1)
        if (self.model_type == ModelType.TwoPhase):
            self.addMassMatrixVolumeFraction(M)

        return M

    def addMassMatrixPhase(self, M, phase):
        phi = self.fe_values.get_phi()

        arhoA_index = self.dof_handler.variable_index[VariableName.ARhoA][phase]
        arhouA_index = self.dof_handler.variable_index[VariableName.ARhoUA][phase]
        arhoEA_index = self.dof_handler.variable_index[VariableName.ARhoEA][phase]

        for e in range(self.dof_handler.n_cell):
            M_cell = np.zeros(
                shape=(self.dof_handler.n_dof_per_cell, self.dof_handler.n_dof_per_cell))

            JxW = self.fe_values.get_JxW(e)
            for q in range(self.quadrature.n_q):
                for k_local in range(self.dof_handler.n_dof_per_cell_per_var):
                    i_arhoA = self.dof_handler.i(k_local, arhoA_index)
                    i_arhouA = self.dof_handler.i(k_local, arhouA_index)
                    i_arhoEA = self.dof_handler.i(k_local, arhoEA_index)
                    for l_local in range(self.dof_handler.n_dof_per_cell_per_var):
                        if self.lump_mass_matrix:
                            M_cell[i_arhoA, i_arhoA] += phi[k_local, q] * phi[l_local, q] * JxW[q]
                            M_cell[i_arhouA, i_arhouA] += phi[k_local, q] * phi[l_local, q] * JxW[q]
                            M_cell[i_arhoEA, i_arhoEA] += phi[k_local, q] * phi[l_local, q] * JxW[q]
                        else:
                            j_arhoA = self.dof_handler.i(l_local, arhoA_index)
                            j_arhouA = self.dof_handler.i(l_local, arhouA_index)
                            j_arhoEA = self.dof_handler.i(l_local, arhoEA_index)

                            M_cell[i_arhoA, j_arhoA] += phi[k_local, q] * phi[l_local, q] * JxW[q]
                            M_cell[i_arhouA, j_arhouA] += phi[k_local, q] * phi[l_local, q] * JxW[q]
                            M_cell[i_arhoEA, j_arhoEA] += phi[k_local, q] * phi[l_local, q] * JxW[q]

            # aggregate cell matrix into global matrix
            self.dof_handler.aggregateLocalCellMatrix(M, M_cell, e)

    def addMassMatrixVolumeFraction(self, M):
        phi = self.fe_values.get_phi()

        aA1_index = self.dof_handler.variable_index[VariableName.AA1][0]

        for e in range(self.dof_handler.n_cell):
            M_cell = np.zeros(
                shape=(self.dof_handler.n_dof_per_cell, self.dof_handler.n_dof_per_cell))

            JxW = self.fe_values.get_JxW(e)
            for q in range(self.quadrature.n_q):
                for k_local in range(self.dof_handler.n_dof_per_cell_per_var):
                    i_aA1 = self.dof_handler.i(k_local, aA1_index)
                    for l_local in range(self.dof_handler.n_dof_per_cell_per_var):
                        if self.lump_mass_matrix:
                            M_cell[i_aA1, i_aA1] += phi[k_local, q] * phi[l_local, q] * JxW[q]
                        else:
                            j_vf1 = self.dof_handler.i(l_local, aA1_index)
                            M_cell[i_aA1, j_vf1] += phi[k_local, q] * phi[l_local, q] * JxW[q]

            # aggregate cell matrix into global matrix
            self.dof_handler.aggregateLocalCellMatrix(M, M_cell, e)

    def assembleTransientSystem(self, U, U_old):
        M_dU = np.matmul(self.M, U - U_old)
        return (M_dU, self.M)

    ## Applies constraints to a nonlinear system solved with Newton's method
    # @param[in] U  implicit solution vector
    # @param[in] r  nonlinear system residual vector
    # @param[in] J  nonlinear system Jacobian matrix
    def applyConstraintsToNonlinearSystem(self, U, r, J):
        # BCs
        for bc in self.bcs:
            bc.applyStrongBCNonlinearSystem(U, r, J)

        # junctions
        for junction in self.junctions:
            junction.applyStronglyToNonlinearSystem(U, r, J)

    ## Applies constraints to a linear system matrix.
    #
    # This is separated from the corresponding RHS vector modification function
    # because the matrix needs to be modified only once; the RHS vector might
    # depend on time or the solution vector.
    #
    # @param[in] A      linear system matrix
    def applyConstraintsToLinearSystemMatrix(self, A):
        # BCs
        for bc in self.bcs:
            bc.applyStrongBCLinearSystemMatrix(A)

        # junctions
        for junction in self.junctions:
            junction.applyStronglyToLinearSystemMatrix(A)

    ## Applies strong constraints to a linear system RHS vector.
    # @param[in] U   solution, needed if Dirichlet values are solution-dependent
    # @param[in] b   linear system RHS vector
    def applyConstraintsToLinearSystemRHSVector(self, U, b):
        # BCs
        for bc in self.bcs:
            bc.applyStrongBCLinearSystemRHSVector(U, b)

        # junctions
        for junction in self.junctions:
            junction.applyStronglyToLinearSystemRHSVector(U, b)

    ## Computes the steady-state residual and Jacobian
    def addVolumetricTerms(self, U, r, J):
        data = dict()
        der = initializeDerivativeData(
            self.aux_names + self.group_fem_aux_names, self.quadrature.n_q)
        nodal_data = dict()
        nodal_der = initializeDerivativeData(
            self.nodal_aux_names, self.dof_handler.n_dof_per_cell_per_var)

        data["phi"] = self.fe_values.get_phi()
        for elem in range(self.dof_handler.n_cell):
            r_cell = np.zeros(self.dof_handler.n_dof_per_cell)
            J_cell = np.zeros(
                shape=(self.dof_handler.n_dof_per_cell, self.dof_handler.n_dof_per_cell))

            i_mesh = self.dof_handler.elem_to_mesh_index[elem]

            data["grad_phi"] = self.fe_values.get_grad_phi(elem)
            data["JxW"] = self.fe_values.get_JxW(elem)
            data["dx"] = self.dof_handler.h[elem]
            data["g"] = np.dot(self.meshes[i_mesh].orientation, self.gravity)
            data["T_wall"] = self.ht_data[i_mesh].T_wall
            data["htc_wall"] = self.ht_data[i_mesh].htc_wall
            data["P_heat"] = self.ht_data[i_mesh].P_heat

            # group FEM
            if self.group_fem:
                # compute nodal solution on element
                self.getLocalNodalSolution(U, elem, nodal_data)

                # compute nodal aux on element
                # NOTE: It would be approximately half as expensive (but more memory intensive)
                # to compute the nodal auxes as a global vector.
                for aux in self.nodal_aux_list:
                    aux.compute(nodal_data, nodal_der)

                # compute flux auxes for group fem
                for aux in self.group_fem_interp_aux_list:
                    aux.compute(nodal_data, nodal_der, data, der)

            # compute elemental solution
            self.computeLocalCellSolution(U, elem, data)

            # compute elemental auxiliary quantities
            for aux in self.aux_list:
                aux.compute(data, der)

            # compute the local residual and Jacobian
            for kernel in self.fem_kernels:
                kernel.apply(data, der, r_cell, J_cell)

            # aggregate cell residual and matrix into global residual and matrix
            self.dof_handler.aggregateLocalCellVector(r, r_cell, elem)
            self.dof_handler.aggregateLocalCellMatrix(J, J_cell, elem)

    ## Computes the local cell solution and gradients for 1-phase flow
    def computeLocalCellSolutionOnePhase(self, U, elem, data):
        data["A"] = self.fe_values.computeLocalArea(elem)
        data["aA1"] = self.fe_values.computeLocalVolumeFractionSolution(U, elem)
        data["arhoA1"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoA, 0, elem)
        data["arhouA1"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoUA, 0, elem)
        data["arhoEA1"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoEA, 0, elem)
        data["grad_A"] = self.fe_values.computeLocalAreaGradient(elem)
        if self.need_solution_gradients:
            data["grad_aA1"] = self.fe_values.computeLocalVolumeFractionSolutionGradient(U, elem)
            data["grad_arhoA1"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoA, 0, elem)
            data["grad_arhouA1"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoUA, 0, elem)
            data["grad_arhoEA1"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoEA, 0, elem)

    ## Computes the local node solution for 1-phase flow
    def computeLocalNodeSolutionOnePhase(self, U, k, data):
        arhoA1_index = self.dof_handler.arhoA_index[0]
        arhouA1_index = self.dof_handler.arhouA_index[0]
        arhoEA1_index = self.dof_handler.arhoEA_index[0]
        data["A"] = self.dof_handler.A[k]
        data["aA1"] = self.dof_handler.aA1(U, k)
        data["arhoA1"] = U[self.dof_handler.i(k, arhoA1_index)]
        data["arhouA1"] = U[self.dof_handler.i(k, arhouA1_index)]
        data["arhoEA1"] = U[self.dof_handler.i(k, arhoEA1_index)]

    ## Computes the local cell solution and gradients for 2-phase flow
    def computeLocalCellSolutionTwoPhase(self, U, elem, data):
        data["A"] = self.fe_values.computeLocalArea(elem)
        data["aA1"] = self.fe_values.computeLocalVolumeFractionSolution(U, elem)
        data["arhoA1"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoA, 0, elem)
        data["arhouA1"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoUA, 0, elem)
        data["arhoEA1"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoEA, 0, elem)
        data["arhoA2"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoA, 1, elem)
        data["arhouA2"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoUA, 1, elem)
        data["arhoEA2"] = self.fe_values.computeLocalSolution(U, VariableName.ARhoEA, 1, elem)
        data["grad_A"] = self.fe_values.computeLocalAreaGradient(elem)
        data["grad_aA1"] = self.fe_values.computeLocalVolumeFractionSolutionGradient(U, elem)
        if self.need_solution_gradients:
            data["grad_arhoA1"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoA, 0, elem)
            data["grad_arhouA1"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoUA, 0, elem)
            data["grad_arhoEA1"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoEA, 0, elem)
            data["grad_arhoA2"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoA, 1, elem)
            data["grad_arhouA2"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoUA, 1, elem)
            data["grad_arhoEA2"] = self.fe_values.computeLocalSolutionGradient(
                U, VariableName.ARhoEA, 1, elem)

    ## Computes the local node solution for 2-phase flow
    def computeLocalNodeSolutionTwoPhase(self, U, k, data):
        arhoA1_index = self.dof_handler.arhoA_index[0]
        arhouA1_index = self.dof_handler.arhouA_index[0]
        arhoEA1_index = self.dof_handler.arhoEA_index[0]
        arhoA2_index = self.dof_handler.arhoA_index[1]
        arhouA2_index = self.dof_handler.arhouA_index[1]
        arhoEA2_index = self.dof_handler.arhoEA_index[1]
        data["A"] = self.dof_handler.A[k]
        data["aA1"] = self.dof_handler.aA1(U, k)
        data["arhoA1"] = U[self.dof_handler.i(k, arhoA1_index)]
        data["arhouA1"] = U[self.dof_handler.i(k, arhouA1_index)]
        data["arhoEA1"] = U[self.dof_handler.i(k, arhoEA1_index)]
        data["arhoA2"] = U[self.dof_handler.i(k, arhoA2_index)]
        data["arhouA2"] = U[self.dof_handler.i(k, arhouA2_index)]
        data["arhoEA2"] = U[self.dof_handler.i(k, arhoEA2_index)]

    def getLocalNodalSolutionOnePhase(self, U, elem, data):
        data["A"] = self.fe_values.getLocalNodalArea(elem)
        data["arhoA1"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoA, 0, elem)
        data["arhouA1"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoUA, 0, elem)
        data["arhoEA1"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoEA, 0, elem)

    def getLocalNodalSolutionTwoPhase(self, U, elem, data):
        data["A"] = self.fe_values.getLocalNodalArea(elem)
        data["aA1"] = self.fe_values.getLocalNodalVolumeFractionSolution(U, elem)
        data["arhoA1"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoA, 0, elem)
        data["arhouA1"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoUA, 0, elem)
        data["arhoEA1"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoEA, 0, elem)
        data["arhoA2"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoA, 1, elem)
        data["arhouA2"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoUA, 1, elem)
        data["arhoEA2"] = self.fe_values.getLocalNodalSolution(U, VariableName.ARhoEA, 1, elem)
