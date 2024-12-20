"""
----------------------------------------------------------------------
Run closed loop from LCO
----------------------------------------------------------------------
"""

from __future__ import print_function
import time
import numpy as np
import main_flowsolver as flo
import utils_flowsolver as flu
import importlib
importlib.reload(flu)
importlib.reload(flo)

import sys
import getopt

#from scipy import signal as ss
#import scipy.io as sio 

# FEniCS log level
flo.set_log_level(flo.LogLevel.INFO) # DEBUG TRACE PROGRESS INFO


def main(argv):
    flu.MpiUtils.check_process_rank()

    # Process argv
    ######################################################################
    # Argument = scenario nr (file + {system G OR controller Kss})
    k_arg = 1
    opts, args = getopt.getopt(argv, "k:") # what is the parameter?
    for opt, arg in opts:
        if opt=='-k':
            k_arg = int(arg)
            if k_arg not in range(1, 6): # authorized range is [1-5]
                print('Invalid argument: setting arg=1')
                k_arg = 1


    ######################################################################
    t000 = time.time()
    
    print('Trying to instantiate FlowSolver...')
    params_flow={'Re': 100.0, 
                 'uinf': 1.0, 
                 'd': 1.0,
                 'sensor_location': np.array([[3.0, 0.0]]), ## TODO 
                 'sensor_type': 'v',
                 'actuator_angular_size': 10,
                 }
    params_save={'save_every': 2000, 
                 'save_every_old': 2000,
                 'savedir0': '/scratchm/wjussiau/fenics-results/cylinder_o1_ms_cl_' + str(k_arg) + '/'}
    params_solver={'solver_type': 'Krylov', 
                   'equations': 'ipcs',
                   'throw_error': True,
                   'perturbations': True, ####
                   'NL': True, ############## NL=False only works with perturbations=True
                   'init_pert': 1,
                   'compute_norms': True}
    params_mesh = flu.make_mesh_param('o1')
    
    params_time = {'dt': 0.005, # not recommended to modify dt between runs 
                   'dt_old': 0.005,
                   'restart_order': 1, # required 1 if dt old is not dt
                   'Tstart': 500, # start of this sim
                   'Trestartfrom': 0, # last restart file
                   'num_steps': 60000, # 1000tc 
                   'Tc': 0} 
    fs = flo.FlowSolver(params_flow=params_flow,
                        params_time=params_time,
                        params_save=params_save,
                        params_solver=params_solver,
                        params_mesh=params_mesh,
                        verbose=100)
    print('__init__(): successful!')

    print('Compute steady state...')
    u_ctrl_steady = 0.0
    #fs.compute_steady_state(method='picard', nip=50, tol=1e-7, u_ctrl=u_ctrl_steady)
    #fs.compute_steady_state(method='newton', max_iter=25, u_ctrl=u_ctrl_steady)
    fs.load_steady_state(assign=True)

    print('Init time-stepping')
    fs.init_time_stepping()

    print('Step several times')
    # controller
    sspath = '/scratchm/wjussiau/fenics-python/cylinder/data/o1/lco/'
    Glist = [4, 6, 8, 10, 14] # available orders for G
    G = flu.read_ss(sspath + 'G' + str(Glist[k_arg-1]) + '.mat')
    import youla_utils as yu
    Kss, _, _ = yu.lqg_regulator(G=G, Qx=1, Ru=1e3, Qv=1, Rw=1e0) # lqg weights 

    x_ctrl = np.zeros((Kss.nstates,))
    #x_ctrl = np.loadtxt(fs.savedir0 + 'x_ctrl_t={:.1f}.npy'.format(fs.Tstart))
    #x_ctrl = np.hstack((x_ctrl, np.zeros((Kss2.nstates,))))
    y_steady = 0 if fs.perturbations else fs.y_meas_steady # reference measurement
    u_ctrl = 0 # control amplitude at time 0
    
    # loop
    for i in range(fs.num_steps):
        # compute control 
        if fs.t>=fs.Tc:
            y_meas = flu.MpiUtils.mpi_broadcast(fs.y_meas)
            y_meas_err = +np.array([y_meas - y_steady]) #### feedback sign was +
            u_ctrl, x_ctrl = flu.step_controller(Kss, x_ctrl, y_meas_err, fs.dt)
            #u_ctrl = flu.saturate(u_ctrl, -2, 2)

        # step
        if fs.perturbations:
            fs.step_perturbation(u_ctrl=u_ctrl, NL=fs.NL, shift=0.0)
        else:
            fs.step(u_ctrl)

    np.savetxt(fs.savedir0 + 'x_ctrl_t={:.1f}.npy'.format(fs.Tf+fs.Tstart), x_ctrl) # TODO add time stamp
    flu.end_simulation(fs, t0=t000)
    fs.write_timeseries()


if __name__=='__main__':
    main(sys.argv[1:])

## ---------------------------------------------------------------------------------
## ---------------------------------------------------------------------------------
## ---------------------------------------------------------------------------------




