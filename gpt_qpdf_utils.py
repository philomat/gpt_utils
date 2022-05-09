from cmath import phase
from math import gamma
import gpt as g
import numpy as np


#ordered list of gamma matrix identifiers, needed for the tag in the correlator output
my_gammas = ["5", "T", "T5", "X", "X5", "Y", "Y5", "Z", "Z5", "I", "SXT", "SXY", "SXZ", "SYT", "SYZ", "SZT"]

ordered_list_of_gammas = [g.gamma[5], g.gamma["T"], g.gamma["T"]*g.gamma[5],
                                      g.gamma["X"], g.gamma["X"]*g.gamma[5], 
                                      g.gamma["Y"], g.gamma["Y"]*g.gamma[5],
                                      g.gamma["Z"], g.gamma["Z"]*g.gamma[5], 
                                      g.gamma["I"], g.gamma["SigmaXT"], 
                                      g.gamma["SigmaXY"], g.gamma["SigmaXZ"], 
                                      g.gamma["SigmaZT"]
                            ]

class pion_measurement:
    def __init__(self, parameters):
        self.plist = parameters["plist"]
        self.width = parameters["width"]
        self.pos_boost = parameters["pos_boost"]
        self.neg_boost = parameters["neg_boost"]
        self.save_propagators = parameters["save_propagators"]

    def set_output_facilites(self, corr_file, prop_file):
        self.output_correlator = g.corr_io.writer(corr_file)
        
        if(self.save_propagators):
            self.output = g.gpt_io.writer(prop_file)

    def propagator_output(self, tag, prop_f, prop_b):

        g.message("Saving forward propagator")
        prop_f_tag = "%s/%s" % (tag, str(self.pos_boost)) 
        self.output.write({prop_f_tag: prop_f})
        self.output.flush()
        g.message("Saving backward propagator")
        prop_b_tag = "%s/%s" % (tag, str(self.neg_boost))
        self.output.write({prop_b_tag: prop_b})
        self.output.flush()
        g.message("Propagator IO done")


    #make the inverters needed for the 96I lattices
    def make_96I_inverter(self, U, evec_file):

        l_exact = g.qcd.fermion.mobius(
            U,
            {
                "mass": 0.00054,
                "M5": 1.8,
                "b": 1.5,
                "c": 0.5,
                "Ls": 12,
                "boundary_phases": [1.0, 1.0, 1.0, -1.0],},
        )

        l_sloppy = l_exact.converted(g.single)

        eig = g.load(evec_file, grids=l_sloppy.F_grid_eo)
        # ## pin coarse eigenvectors to GPU memory
        pin = g.pin(eig[1], g.accelerator)


        light_innerL_inverter = g.algorithms.inverter.preconditioned(
            g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd),
            g.algorithms.inverter.sequence(
                g.algorithms.inverter.coarse_deflate(
                    eig[1],
                    eig[0],
                    eig[2],
                    block=400,
                    fine_block=4,
                    linear_combination_block=32,
                ),
                g.algorithms.inverter.split(
                    g.algorithms.inverter.cg({"eps": 1e-8, "maxiter": 200}),
                    mpi_split=g.default.get_ivec("--mpi_split", None, 4),
                ),
            ),
        )

        light_innerH_inverter = g.algorithms.inverter.preconditioned(
            g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd),
            g.algorithms.inverter.sequence(
                g.algorithms.inverter.coarse_deflate(
                    eig[1],
                    eig[0],
                    eig[2],
                    block=400,
                    fine_block=4,
                    linear_combination_block=32,
                ),
                g.algorithms.inverter.split(
                    g.algorithms.inverter.cg({"eps": 1e-8, "maxiter": 300}),
                    mpi_split=g.default.get_ivec("--mpi_split", None, 4),
                ),
            ),
        )

        light_exact_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerH_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=10,
        )

        light_sloppy_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerL_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=2,
        )


        ############### final inverter definitions
        prop_l_sloppy = l_exact.propagator(light_sloppy_inverter).grouped(6)
        prop_l_exact = l_exact.propagator(light_exact_inverter).grouped(6)

        return prop_l_exact, prop_l_sloppy, pin

    def make_debugging_inverter(self, U):

        l_exact = g.qcd.fermion.mobius(
            U,
            {
                "mass": 0.00054,
                "M5": 1.8,
                "b": 1.5,
                "c": 0.5,
                "Ls": 12,
                "boundary_phases": [1.0, 1.0, 1.0, -1.0],},
        )

        l_sloppy = l_exact.converted(g.single)

        light_innerL_inverter = g.algorithms.inverter.preconditioned(g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd), g.algorithms.inverter.cg(eps = 1e-8, maxiter = 200))
        light_innerH_inverter = g.algorithms.inverter.preconditioned(g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd), g.algorithms.inverter.cg(eps = 1e-8, maxiter = 300))

        light_exact_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerH_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=10,
        )

        light_sloppy_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerL_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=2,
        )

        prop_l_sloppy = l_exact.propagator(light_sloppy_inverter).grouped(6)
        prop_l_exact = l_exact.propagator(light_exact_inverter).grouped(6)
        return prop_l_exact, prop_l_sloppy


    ############## make list of complex phases for momentum proj.
    def make_mom_phases(self, grid):    
        one = g.complex(grid)
        pp = [-2 * np.pi * np.array(p) / grid.fdimensions for p in self.plist]
        P = g.exp_ixp(pp)
        mom = [g.eval(pp*one) for pp in P]
        return mom

    # create Wilson lines from all --> all + dz for all dz in 0,zmax
    def create_WL(self, U):
        W = []
        W.append(g.qcd.gauge.unit(U[2].grid)[0])
        for dz in range(0, self.zmax):
            W.append(g.eval(W[dz-1] * g.cshift(U[2], 2, dz)))
                
        return W


    #function that does the contractions for the smeared-smeared pion 2pt function
    def contract_2pt(self, prop_f, prop_b, phases, trafo, tag):

        g.message("Begin sink smearing")
        tmp_trafo = g.convert(trafo, prop_f.grid.precision)

        prop_f = g.create.smear.boosted_smearing(tmp_trafo, prop_f, w=self.width, boost=self.pos_boost)
        prop_b = g.create.smear.boosted_smearing(tmp_trafo, prop_b, w=self.width, boost=self.neg_boost)
        g.message("Sink smearing completed")

        # corr = g.slice(
            # g.trace( P *prop_f * g.adj(prop_b) ), 3
        # ) 

        corr = g.slice_trDA(prop_f,g.adj(prop_b),phases, 3) #one could also use trQPDF... doesnt matter

        #do correlator output
        corr_tag = "%s/2pt" % (tag)
        corr_p = corr[0]
        for i, corr_mu in enumerate(corr_p):
            out_tag = f"{corr_tag}/p{self.plist[i]}"
            for j, corr_t in enumerate(corr_mu):
                out_tag = f"{out_tag}/{my_gammas[j]}"
                self.output_correlator.write(out_tag, corr_t)
                #g.message("Correlator %s\n" % out_tag, corr_t)

    #function that creates boosted, smeared src.
    def create_src_2pt(self, pos, trafo, grid):
        
        srcD = g.mspincolor(grid)
        srcD[:] = 0
        
        g.create.point(srcD, pos)
        g.message("point src set")
        srcDm = g.create.smear.boosted_smearing(trafo, srcD, w=self.width, boost=self.neg_boost)
        g.message("pos. boosted src done")
        srcDp = g.create.smear.boosted_smearing(trafo, srcD, w=self.width, boost=self.pos_boost)
        g.message("neg. boosted src done")
        del srcD
        g.message("deleted pt. src, now returning")

        return srcDp, srcDm



class pion_DA_measurement(pion_measurement):
    def __init__(self, parameters):
        self.zmax = parameters["zmax"]
        self.pzmin = parameters["pzmin"]
        self.pzmax = parameters["pzmax"]
        self.plist = [ [0,0, pz, 0] for pz in range(self.pzmin, self.pzmax)]
        self.width = parameters["width"]
        self.pos_boost = parameters["pos_boost"]
        self.neg_boost = parameters["neg_boost"]
        self.save_propagators = parameters["save_propagators"]

    # Creating list of W*prop_b for all z
    def constr_backw_prop_for_DA(self, prop_b, W):
        g.message("Creating list of W*prop_b for all z")
        prop_list = [prop_b,]

        for z in range(1,self.zmax):
            prop_list.append(g.eval(g.adj(W[z] * g.cshift(prop_b,2,z))))
        
        return prop_list

    # Function that essentially defines our version of DA
    def contract_DA(self, prop_f, prop_b, phases, tag):

        # create and save correlators
        corr = g.slice_trDA(prop_b,prop_f,phases, 3)

        # corr = g.slice(
        #      g.trace(g.adj(prop_b) * W * g.gamma["Z"] * P * prop_f), 3)

        g.message("Starting IO")       
        for z, corr_p in enumerate(corr):
            corr_tag = "%s/DA/z%s" % (tag, str(z))
            for i, corr_mu in enumerate(corr_p):
                p_tag = f"{corr_tag}/p{self.plist[i]}"
                for j, corr_t in enumerate(corr_mu):
                    out_tag = f"{p_tag}/{my_gammas[j]}"
                    self.output_correlator.write(out_tag, corr_t)
                    #g.message("Correlator %s\n" % out_tag, corr_t)

class pion_ff_measurement(pion_measurement):
    def __init__(self, parameters):
        self.p = parameters["pf"]
        self.q = parameters["q"]
        self.plist = [self.q,] 
        self.t_insert = parameters["t_insert"]
        self.width = parameters["width"]
        self.boost_in = parameters["boost_in"]
        self.boost_out = parameters["boost_out"]
        self.pos_boost = self.boost_in
        self.neg_boost = [-self.pos_boost[0], -self.pos_boost[1], -self.pos_boost[2]]
        self.save_propagators = parameters["save_propagators"]

    def contract_FF(self, prop_f, prop_b, phases, tag):

        #This should work, as both prop are not lists! 
        corr = g.slice_trQPDF(prop_b, prop_f, phases, 3)


        g.message("Starting IO")    
        for z, corr_p in enumerate(corr):
            corr_tag = "%s/FF" % (tag)
            for i, corr_mu in enumerate(corr_p):
                p_tag = f"{corr_tag}/pf{self.p}/q{self.q}"
                for j, corr_t in enumerate(corr_mu):
                    out_tag = f"{p_tag}/{my_gammas[j]}"
                    self.output_correlator.write(out_tag, corr_t)
                    #g.message("Correlator %s\n" % out_tag, corr_t)

    def create_bw_seq(self, inverter, prop, trafo):

        tmp_trafo = g.convert(trafo, prop.grid.precision)

        ss_prop = g.create.smear.boosted_smearing(tmp_trafo, prop, w=self.width, boost=self.boost_out)

        del prop

        pp = 2.0 * np.pi * np.array(self.p) / ss_prop.grid.fdimensions
        P = g.exp_ixp(pp)

        # sequential solve through t=insertion_time
        t_op = self.t_insert
        src_seq = g.lattice(ss_prop)
        src_seq[:] = 0
        src_seq[:, :, :, t_op] = ss_prop[:, :, :, t_op]

        del ss_prop

        src_seq @=  g.gamma[5]* src_seq
        #multiply with complex conjugate phase because it's a backwards prop.
        src_seq @= g.adj(P)* src_seq 


        #does overwriting on the fly work?
        bw_boost = [-self.boost_out[0], -self.boost_out[1], -self.boost_out[2]]
        src_seq = g.create.smear.boosted_smearing(tmp_trafo, src_seq, w=self.width, boost=bw_boost)

        dst_seq = g.lattice(src_seq)
        dst_seq @= inverter * src_seq

        #This is now in principle B^dagger_zx but with the complex conj phase and a missing factor of gamma5 

        return (g.adj(dst_seq)*g.gamma[5])

class pion_qpdf_measurement(pion_measurement):
    def __init__(self, parameters):
        self.zmax = parameters["zmax"]
        self.p = parameters["pf"]
        self.q = parameters["q"]
        self.plist = [self.q,]
        self.t_insert = parameters["t_insert"]
        self.width = parameters["width"]
        self.boost_in = parameters["boost_in"]
        self.boost_out = parameters["boost_out"]
        self.pos_boost = self.boost_in
        self.neg_boost = [-self.pos_boost[0], -self.pos_boost[1], -self.pos_boost[2]]
        self.save_propagators = parameters["save_propagators"]

    def contract_QPDF(self, prop_f, prop_b, phases, tag):
 
        corr = g.slice_trQPDF(prop_b, prop_f, phases, 3)


        g.message("Starting IO")
        for z, corr_p in enumerate(corr):
            corr_tag = "%s/QPDF" % (tag)
            for i, corr_mu in enumerate(corr_p):
                p_tag = f"{corr_tag}/pf{self.p}/q{self.q}"
                for j, corr_t in enumerate(corr_mu):
                    out_tag = f"{p_tag}/{my_gammas[j]}"
                    self.output_correlator.write(out_tag, corr_t)
                    #g.message("Correlator %s\n" % out_tag, corr_t)


    def create_fw_prop_QPDF(self, prop_f, W):
        g.message("Creating list of W*prop_f for all z")
        prop_list = [prop_f,]

        for z in range(1,self.zmax):
            prop_list.append(g.eval(W[z]*g.cshift(prop_f,2,z)))
        
        return prop_list      

    def create_bw_seq(self, inverter, prop, trafo):

        tmp_trafo = g.convert(trafo, prop.grid.precision)

        ss_prop = g.create.smear.boosted_smearing(tmp_trafo, prop, w=self.width, boost=self.boost_out)

        del prop

        pp = 2.0 * np.pi * np.array(self.p) / ss_prop.grid.fdimensions
        P = g.exp_ixp(pp)

        # sequential solve through t=insertion_time
        t_op = self.t_insert
        src_seq = g.lattice(ss_prop)
        src_seq[:] = 0
        src_seq[:, :, :, t_op] = ss_prop[:, :, :, t_op]

        del ss_prop

        src_seq @=  g.gamma[5]* src_seq
        #multiply with complex conjugate phase because it's a backwards prop.
        src_seq @= g.adj(P)* src_seq


        #does overwriting on the fly work?
        bw_boost = [-self.boost_out[0], -self.boost_out[1], -self.boost_out[2]]
        src_seq = g.create.smear.boosted_smearing(tmp_trafo, src_seq, w=self.width, boost=bw_boost)

        dst_seq = g.lattice(src_seq)
        dst_seq @= inverter * src_seq

        #This is now in principle B^dagger_zx but with the complex conj phase and a missing factor of gamma5 

        return (g.adj(dst_seq)*g.gamma[5])

class proton_measurement:
    def __init__(self, parameters):
        self.plist = parameters["plist"]
        self.pol_list = ["P+_Sz+","P+_Sx+","P+_Sx-"]
        self.width = parameters["width"]
        self.pos_boost = parameters["pos_boost"]


    def set_output_facilites(self, corr_file, prop_file):
        self.output_correlator = g.corr_io.writer(corr_file)

        if(self.save_propagators):
            self.output = g.gpt_io.writer(prop_file)


    def propagator_output(self, tag, prop_f):

        g.message("Saving forward propagator")
        prop_f_tag = "%s/%s" % (tag, str(self.pos_boost))
        self.output.write({prop_f_tag: prop_f})
        self.output.flush()
        g.message("Propagator IO done")


     #make the inverters needed for the 96I lattices
    def make_96I_inverter(self, U, evec_file):

        l_exact = g.qcd.fermion.mobius(
            U,
            {
                "mass": 0.00054,
                "M5": 1.8,
                "b": 1.5,
                "c": 0.5,
                "Ls": 12,
                "boundary_phases": [1.0, 1.0, 1.0, -1.0],},
        )

        l_sloppy = l_exact.converted(g.single)

        eig = g.load(evec_file, grids=l_sloppy.F_grid_eo)
        # ## pin coarse eigenvectors to GPU memory
        pin = g.pin(eig[1], g.accelerator)


        light_innerL_inverter = g.algorithms.inverter.preconditioned(
            g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd),
            g.algorithms.inverter.sequence(
                g.algorithms.inverter.coarse_deflate(
                    eig[1],
                    eig[0],
                    eig[2],
                    block=400,
                    fine_block=4,
                    linear_combination_block=32,
                ),
                g.algorithms.inverter.split(
                    g.algorithms.inverter.cg({"eps": 1e-8, "maxiter": 200}),
                    mpi_split=g.default.get_ivec("--mpi_split", None, 4),
                ),
            ),
        )

        light_innerH_inverter = g.algorithms.inverter.preconditioned(
            g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd),
            g.algorithms.inverter.sequence(
                g.algorithms.inverter.coarse_deflate(
                    eig[1],
                    eig[0],
                    eig[2],
                    block=400,
                    fine_block=4,
                    linear_combination_block=32,
                ),
                g.algorithms.inverter.split(
                    g.algorithms.inverter.cg({"eps": 1e-8, "maxiter": 300}),
                    mpi_split=g.default.get_ivec("--mpi_split", None, 4),
                ),
            ),
        )

        light_exact_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerH_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=10,
        )

        light_sloppy_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerL_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=2,
        )


        ############### final inverter definitions
        prop_l_sloppy = l_exact.propagator(light_sloppy_inverter).grouped(6)
        prop_l_exact = l_exact.propagator(light_exact_inverter).grouped(6)

        return prop_l_exact, prop_l_sloppy, pin

    def make_debugging_inverter(self, U):

        l_exact = g.qcd.fermion.mobius(
            U,
            {
                "mass": 0.00054,
                "M5": 1.8,
                "b": 1.5,
                "c": 0.5,
                "Ls": 12,
                "boundary_phases": [1.0, 1.0, 1.0, -1.0],},
        )

        l_sloppy = l_exact.converted(g.single)

        light_innerL_inverter = g.algorithms.inverter.preconditioned(g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd), g.algorithms.inverter.cg(eps = 1e-8, maxiter = 200))
        light_innerH_inverter = g.algorithms.inverter.preconditioned(g.qcd.fermion.preconditioner.eo1_ne(parity=g.odd), g.algorithms.inverter.cg(eps = 1e-8, maxiter = 300))

        light_exact_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerH_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=10,
        )

        light_sloppy_inverter = g.algorithms.inverter.defect_correcting(
            g.algorithms.inverter.mixed_precision(light_innerL_inverter, g.single, g.double),
            eps=1e-8,
            maxiter=2,
        )

        prop_l_sloppy = l_exact.propagator(light_sloppy_inverter).grouped(6)
        prop_l_exact = l_exact.propagator(light_exact_inverter).grouped(6)
        return prop_l_exact, prop_l_sloppy


    ############## make list of complex phases for momentum proj.
    def make_mom_phases(self, grid):    
        one = g.complex(grid)
        pp = [-2 * np.pi * np.array(p) / grid.fdimensions for p in self.plist]
        P = g.exp_ixp(pp)
        mom = [g.eval(pp*one) for pp in P]
        return mom

    # create Wilson lines from all --> all + dz for all dz in 0,zmax
    def create_WL(self, U):
        W = []
        W.append(g.qcd.gauge.unit(U[2].grid)[0])
        for dz in range(0, self.zmax):
            W.append(g.eval(W[dz-1] * g.cshift(U[2], 2, dz)))
                
        return W


    #function that does the contractions for the smeared-smeared pion 2pt function
    def contract_2pt(self, prop_f, phases, trafo, tag):

        g.message("Begin sink smearing")
        tmp_trafo = g.convert(trafo, prop_f.grid.precision)

        prop_f = g.create.smear.boosted_smearing(tmp_trafo, prop_f, w=self.width, boost=self.pos_boost)
        g.message("Sink smearing completed")

        #This ans the IO still need work
        corr = g.slice_proton(prop_f, phases, 3) 

        #do correlator output 
        corr_tag = "%s/2pt" % (tag)
        for i, corr_pol in enumerate(corr):
            out_tag = f"{corr_tag}/Pol{self.pol_list[i]}"
            for j, corr_p in enumerate(corr_pol):
                out_tag = f"{corr_tag}/p{self.plist[j]}"
                self.output_correlator.write(out_tag, corr_p)
                #g.message("Correlator %s\n" % out_tag, corr_t)

    #function that creates boosted, smeared src.
    def create_src(self, pos, trafo, grid):
        
        srcD = g.mspincolor(grid)
        srcD[:] = 0
        
        g.create.point(srcD, pos)

        srcDp = g.create.smear.boosted_smearing(trafo, srcD, w=self.width, boost=self.pos_boost)

        del srcD

        return srcDp     


class proton_qpdf_measurement(proton_measurement):
   
    def __init__(self, parameters):
        self.zmax = parameters["zmax"]
        self.p = parameters["pf"]
        self.q = parameters["q"]
        self.plist = [self.q,]
        self.pol_list = ["P+_Sz+","P+_Sx+","P+_Sx-"]
        #self.Gamma = parameters["gamma"]
        self.t_insert = parameters["t_insert"]
        self.width = parameters["width"]
        self.boost_in = parameters["boost_in"]
        self.boost_out = parameters["boost_out"]
        self.pos_boost = self.boost_in
        self.save_propagators = parameters["save_propagators"]



    def create_fw_prop_QPDF(self, prop_f, W):
        g.message("Creating list of W*prop_f for all z")
        prop_list = [prop_f,]

        for z in range(1,self.zmax):
            prop_list.append(g.eval(W[z]*g.cshift(prop_f,2,z)))
        
        return prop_list  

    def create_bw_seq(self, inverter, prop, trafo):
        tmp_trafo = g.convert(trafo, prop.grid.precision)

        #Make SS propagator
        prop = g.create.smear.boosted_smearing(tmp_trafo, prop, w=self.width, boost=self.boost_out)

        pp = 2.0 * np.pi * np.array(self.p) / prop.grid.fdimensions
        P = g.exp_ixp(pp)

        # sequential solve through t=insertion_time for all 3 proton polarizations
        src_seq = [g.mspincolor(prop.grid) for i in range(3)]
        dst_seq = []
        #g.qcd.baryon.proton_seq_src(prop, src_seq, self.t_insert)

        dst_tmp = g.mspincolor(prop.grid)
        for i in range(3):

            dst_tmp @= inverter * g.create.smear.boosted_smearing(tmp_trafo, g.eval(g.gamma[5]* P* g.conj(src_seq[i])), w=self.width, boost=self.boost_out)
            #del src_seq[i]
            dst_seq.append(g.eval(g.gamma[5] * g.conj( dst_tmp)))
        g.message("bw. seq propagator done")
        return dst_seq            


    def contract_QPDF(self, prop_f, prop_bw, phases, tag):
 
        #This and the IO still need work

        for pol in self.pol_list:
            corr = g.slice_trQPDF(prop_bw, prop_f, phases, 3)

            corr_tag = f"{tag}/QPDF/Pol{pol}"
            for z, corr_p in enumerate(corr):
                for i, corr_mu in enumerate(corr_p):
                    p_tag = f"{corr_tag}/pf{self.p}/q{self.q}"
                    for j, corr_t in enumerate(corr_mu):
                        out_tag = f"{p_tag}/{my_gammas[j]}"
                        self.output_correlator.write(out_tag, corr_t)
