"""
----------------------------------------------------------------------
Run optimization
Youla
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
print = flu.print0

from scipy import signal as ss
import scipy.io as sio 
import scipy.optimize as so

import youla_utils
import optim_utils

flo.set_log_level(flo.LogLevel.ERROR) # DEBUG TRACE PROGRESS INFO WARNING CRITICAL ERROR

import pdb
import sys
import warnings
import getopt

x_data = []
y_data = []

######################################################################
def make_controller(G, K0, x, scaling):
    '''Make Youla controller based on stable closed-loop (G,K0), with parameter x'''
    print('grep before scaling (seen by optim): ', x)
    x_scaled = scaling(x)
    print('grep after scaling (seen by controller) :', x_scaled)

    p = x_scaled[0]
    theta = x_scaled[1:]

    # Youla formulas
    Q = youla_utils.basis_laguerre_ss(p=p, theta=theta)
    K = youla_utils.youla(G=G, K0=K0, Q=Q)
    #K = youla_utils.youla_left_coprime(G=G, K=K0, Q=Q)

    #Q00 = youla_utils.basis_laguerre_K00(G, K0, p=p, theta=theta)
    #Q = youla_utils.basis_laguerre_ss(p=p, theta=theta)
    #K = youla_utils.youla(G=G, K0=K0, Q=Q00)
    #K = youla_utils.youla_laguerre_K00(G=G, K0=K0, p=p, theta=theta, check=True)

    #K = youla_utils.youla_left_coprime(G=G, K=K0, Q=Q)
    print('feedback is stable: ', youla_utils.isstablecl(G, K, +1)) 
    return K 


def eval_controller(G, K0, x, scaling, criterion,
                    params_flow, params_time, params_save, params_solver, params_mesh,
                    verbose=False, Kss=None, write_csv=False):
    # Ensure x is 1D
    x = x.reshape(-1,)

    # Build controller
    Kss = make_controller(G, K0, x=x, scaling=scaling)


    # Initialize FlowSolver
    fs = flo.FlowSolver(params_flow=params_flow, 
                        params_time=params_time, 
                        params_save=params_save,
                        params_solver=params_solver, 
                        params_mesh=params_mesh, 
                        verbose=verbose)

    fs.load_steady_state(assign=True)
    fs.init_time_stepping()

    #print('controller is: ', Kss)

    # Initialize time loop
    y_steady = 0 if fs.perturbations else fs.y_meas_steady # reference measurement
    x_ctrl = np.zeros((Kss.nstates,))
    diverged = False
    for i in range(fs.num_steps):
        if fs.t>=fs.Tc:
            # measurement
            ####fs.y_meas += fs.y_meas_steady
            y_meas = flu.MpiUtils.mpi_broadcast(fs.y_meas)
            # compute error relative to base flow
            # y_meas_ctrl = +(y_meas - y_steady)
            y_meas_ctrl = +np.array([y_meas])
            # step controller
            u_ctrl, x_ctrl = flu.step_controller(Kss, x_ctrl, y_meas_ctrl, fs.dt)
            # saturation
            #u_ctrl = flu.saturate(u_ctrl, -0.5, 0.5)

            #print('measurement is: ', y_meas_err)
            #print('control is: ', u_ctrl)

        # step fluid
        if fs.perturbations:
            ret = fs.step_perturbation(u_ctrl=u_ctrl, NL=fs.NL, shift=0.0)
        else:
            ret = fs.step(u_ctrl)
        # or step perturbation!!! big mistake here
        if ret==-1:
            print('Problem in solver -- exiting loop...')
            diverged = True
            break

    #import pdb
    #pdb.set_trace()
          
    ## TODO
    # x**2
    J = flu.compute_cost(fs=fs, criterion=criterion, u_penalty=0.1 * 1e-2, fullstate=True, verbose=True,
        diverged=diverged, diverged_penalty=1)
    J *= 100 
    # y**2
    #J = flu.compute_cost(fs=fs, criterion=criterion, u_penalty=0.1, fullstate=False, verbose=True,
    #    diverged=diverged, diverged_penalty=50)

    # Write CSV
    flu.write_optim_csv(fs, x, J, diverged=False, write=write_csv)

    global x_data, y_data
    x_data += [x.copy()]
    y_data += [J]

    return J, fs, Kss


def main(argv):
    # Process argv
    ######################################################################
    k_arg = None
    opts, args = getopt.getopt(argv, "k:") # controller nr
    for opt, arg in opts:
        if opt=='-k':
            k_arg = arg


    # Flow parameters
    ######################################################################
    params_flow={'Re': 7500.0, 
                 'uinf': 1.0, 
                 'd': 1.0, 
                 'sensor_location': np.array([[3.0, 0.0]]), 
                 'sensor_type': ['v'], 
                 'actuator_angular_size': 10,}
    params_time={'dt': 0.005, 
                 'Tstart': 0, 
                 'num_steps': 40000,
                 'Tc': 0.0} 
    params_save={'save_every': 2000,
                 'save_every_old': 2000,
                 'savedir0': '',
                 'compute_norms': True}
    params_solver={'solver_type': 'Krylov', 
                   'equations': 'ipcs',
                   'throw_error': True,
                   'perturbations': True, ####
                   'NL': True, ############## NL=False only works with perturbations=True
                   'init_pert': 0}
    params_mesh = {'genmesh': False,
                   'remesh': False,
                   'nx': 1,
                   'meshpath': '/stck/wjussiau/fenics-python/mesh/', 
                   'meshname': 'cavity_byhand_n200.xdmf',
                   'xinf': 2.5,
                   'xinfa': -1.2,
                   'yinf': 0.5,
                   'segments': 540,
                   }

    # Control parameters
    ######################################################################
    sspath = '/scratchm/wjussiau/fenics-python/cavity/data/regulator/'
    #G = flu.read_ss(sspath + 'sysid_o24_ssest_QB.mat')
    G = flu.read_ss(sspath + 'sysid_o24_for_QB.mat')
    #K0 = flu.read_ss(sspath + 'K0_o4_S_KS_clpoles1.mat')

    sspath_multiK = '/scratchm/wjussiau/fenics-python/cavity/data/regulator/multiK/'
    if k_arg is None:
        k_arg = 'K1'
    K0 = flu.read_ss(sspath_multiK + k_arg + '.mat') # K1 to K004
    #K0 = flu.read_ss(sspath_multiK + 'K_1.mat') # K1 to K004

    # Cost function definition
    ######################################################################
    def costfun(x, scaling, allout=False, giveK=None, verbose=10000):
        '''Evaluate cost function on one point x'''
        print('Params seen: ', x)
        J, fs, Kss = eval_controller(x=x, G=G, K0=K0, criterion='integral',
            params_flow=params_flow, params_time=params_time, params_solver=params_solver,
            params_mesh=params_mesh, params_save=params_save, verbose=verbose, Kss=giveK,
            write_csv=True, scaling=scaling)
        print('Cost functional is: ', J)
        print('###########################################################')
        if allout:
            return J, fs, Kss
        return J
    
    #def costfun_array(x, **kwargs):
    #    return optim_utils.fun_array(x, costfun, **kwargs)

    #def costfun_parallel(x):
    #    return optim_utils.parallel_function_wrapper(x, [0], costfun)
    
    # Simulation parameters
    ######################################################################
    print('FlowSolver parameters common to all controller evaluations...')
    tbegin = 1000
    NUM_STEPS_OPTIM = 50000
    params_time['dt'] = 0.001
    params_time['Tstart'] = tbegin
    params_time['num_steps'] = NUM_STEPS_OPTIM # TODO
    params_time['Tc'] = tbegin
    params_save['save_every'] = 0
    params_save['save_every_old'] = 10000
    params_solver['throw_error'] = False

    ## TODO ##
    optim_path = '/scratchm/wjussiau/fenics-results/cavity_opt_' + k_arg + '/'
    params_save['savedir0'] = optim_path

    ###print('optim path is: ', optim_path)
    ###print('controller is: ', k_arg)
    ###print('was read from: ', sspath_multiK + k_arg + '.mat')

    ###return 1

    # Optimization
    flu.MpiUtils.check_process_rank()
    rank = flu.MpiUtils.get_rank()
        
    # GOTO
    ndim = 4 # Youla p + theta

    colnames = ['J'] + ['x'+str(i+1) for i in range(ndim)] # [y, x1, x2...]

    ### -----------------------------------------------------------------------
    # Limits
    # in log
    xmin = -1 #TODO
    xmax = 1
    xlimits = np.array([[xmin, xmax]])
    xlimits = np.repeat(xlimits, ndim, axis=0)
    xlimits[1:] = np.repeat(np.array([[-1, 1]]), ndim-1, axis=0)

    scaling_factor = 1 / youla_utils.norm(youla_utils.control.feedback(G, K0, 1))
    #scaling_factor = 0.01
    scaling = lambda x: np.hstack((10**x[0], scaling_factor*x[1:]))

    # Multi-start
    n_doe = 10  # TODO
    #sampling = optim_utils.LHS(xlimits=xlimits, random_state=5)
    #xlist = sampling(n_doe)
    xlist = optim_utils.sobol_sample(ndim=ndim, npt=n_doe, xlimits=xlimits, shuffle=10) 
    # add prescribed point around K0:
    # 1 0 0 0 0...
    ####### xadd = np.hstack((np.array([1]), np.zeros(ndim-1,)))
    ####### xlist = np.vstack((xadd, xlist))

    ## -----------------------------------------------------------------------

    maxfev = 50 # TODO
    costfun_parallel = lambda x: costfun(x, scaling=scaling)
    #costfun_parallel = lambda x: optim_utils.parallel_function_wrapper(x, stop_all=[0], fun=costfun)

    idx_current_slice = 0
    y_cummin_all = np.empty((0, 1))
    x_cummin_all = np.empty((0, ndim))
    for x in xlist:
        print('***************** Multi-start ++++ New point')
        # if nm, construct initial simplex around x
        initial_simplex = optim_utils.construct_simplex(x, rectangular=True, edgelen=0.25)
    
        # run algorithm: bfgs, nm, cobyla, dfo
        res = optim_utils.minimize(costfun=costfun_parallel, x0=x, alg='dfo',
            options=dict(maxfev=maxfev, maxiter=maxfev,
            adaptive=True, initial_simplex=initial_simplex, 
            init_delta=1,
            # for BO
            xlimits=xlimits, n_doe=5, random_state=1, n_iter=maxfev,
            corr='matern52', criterion='SBO')) # TODO
            #corr='squar_exp' or 'matern52', criterion='EI' or 'SBO')) 

        # write optimization result
        x_cummin_all, y_cummin_all, idx_current_slice = optim_utils.write_results(
            x_data=x_data, y_data=y_data, optim_path=optim_path, colnames=colnames,
            x_cummin_all=x_cummin_all, y_cummin_all=y_cummin_all, idx_current_slice=idx_current_slice,
            nfev=res.nfev, verbose=True)


    print('Finishing and closing...')
    sys.exit()
       

if __name__=='__main__':
    main(sys.argv[1:])






